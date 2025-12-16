"""
IPC TCP Server Transport (Agent Mode)

TCP server transport for network-accessible daemon ("Agent Mode").
Uses the modular security layer for TLS negotiation and authentication.

Security Model:
- Server sends hello response with TLS capability
- If TLS enabled on server, it's required (client can't downgrade)
- After optional TLS upgrade, challenge-response auth occurs
- Raw password is NEVER transmitted over the network
"""

import os
import socket
import ssl
import threading
from pathlib import Path
from typing import Optional, Tuple

# Import from existing IPC modules
from ipc_client import DaemonTransport, LineBufferedTransport

# Import security layer
from ipc_security import (
    negotiate_tls_server,
    authenticate_server,
    TlsNegotiationError
)

# Import constants
from constants import (
    DEFAULT_AGENT_PORT,
    AUTH_TIMEOUT_SECONDS
)

# Import credential reading
from config_manager import (
    PASSWORD_INFO_KEY,
    _read_credentials
)

# Debug logging
from debug_logging import log_debug, log_info, log_error

# TLS manager (lazy import)
TLS_AVAILABLE = None


# =============================================================================
# Server Side: TCPClientHandler (per-connection handler)
# =============================================================================

class TCPClientHandler:
    """
    Thread-safe handler for a single authenticated TCP client connection.
    Similar to SocketClientHandler but for TCP with auth.
    """
    
    def __init__(self, client_socket: socket.socket, client_address: tuple):
        """
        Initialize handler for an authenticated client.
        
        Args:
            client_socket: The connected socket (may be SSL-wrapped)
            client_address: (host, port) of client
        """
        self.client_socket = client_socket
        self.client_address = client_address
        self.client_file = client_socket.makefile('rw', buffering=1, encoding='utf-8', errors='replace')
        self._write_lock = threading.Lock()
        self._closed = False
    
    def receive_line(self) -> str:
        """Read one line from client (blocking)."""
        if self._closed:
            return ""
        try:
            line = self.client_file.readline()
            if not line:  # EOF
                return ""
            return line.rstrip('\n\r')
        except Exception:
            return ""
    
    def send_line(self, data: str) -> None:
        """Send one line to client (thread-safe)."""
        if self._closed:
            return
        with self._write_lock:
            if not data.endswith('\n'):
                data = data + '\n'
            self.client_file.write(data)
            self.client_file.flush()
    
    def close(self) -> None:
        """Close client connection (idempotent)."""
        if self._closed:
            return
        self._closed = True
        try:
            self.client_file.close()
        except Exception:
            pass
        try:
            self.client_socket.close()
        except Exception:
            pass
    
    def get_type(self) -> str:
        return "tcp_client"
    
    def get_address(self) -> tuple:
        """Return client address (host, port)."""
        return self.client_address


# =============================================================================
# Server Side: TCPServerTransport
# =============================================================================

class TCPServerTransport:
    """
    TCP server transport for Agent Mode.
    
    Listens on a TCP port, performs STARTTLS-style TLS negotiation,
    authenticates clients, and returns handlers for authenticated connections.
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_AGENT_PORT, 
                 use_tls: bool = True):
        """
        Initialize TCP server transport.
        
        Args:
            host: Interface to bind to (default: all interfaces)
            port: Port to listen on (default: 5555)
            use_tls: Enable TLS encryption (default: True)
            
        Raises:
            OSError: If socket creation or binding fails
            RuntimeError: If credentials cannot be loaded
        """
        self.host = host
        self.port = port
        self.ssl_context: Optional[ssl.SSLContext] = None
        self.server_socket: Optional[socket.socket] = None
        self._password_info: Optional[dict] = None
        
        # Check TLS availability and setup if requested
        if use_tls:
            self.tls_enabled = self._setup_tls()
        else:
            self.tls_enabled = False
        
        # Load credentials for authentication
        self._load_credentials()
        
        # Create and bind socket
        self._setup_socket()
    
    def _load_credentials(self) -> None:
        """Load admin password info from credentials file."""
        credentials = _read_credentials()
        
        # Find the admin user (or first user with valid password_info)
        for user_id, user_data in credentials.items():
            if isinstance(user_data, dict) and PASSWORD_INFO_KEY in user_data:
                pw_info = user_data[PASSWORD_INFO_KEY]
                if isinstance(pw_info, dict) and "hash" in pw_info and "salt" in pw_info:
                    self._password_info = pw_info
                    log_debug("TCP_SERVER", f"Loaded credentials for user '{user_data.get('username', 'unknown')}'")
                    return
        
        raise RuntimeError(
            "Cannot start TCP server: No valid credentials found in credentials.json. "
            "Ensure the daemon has been started at least once to create default credentials."
        )
    
    def _setup_tls(self) -> bool:
        """
        Setup TLS context with self-signed certificate.
        
        Uses tls_manager which tries cryptography library first,
        then falls back to openssl CLI if available.
        
        Returns:
            True if TLS setup succeeded, False otherwise.
        """
        global TLS_AVAILABLE
        
        # Import tls_manager - should always succeed as it's stdlib-compatible now
        try:
            from tls_manager import ensure_server_certificate
        except ImportError as e:
            log_error("TCP_SERVER", f"Cannot import tls_manager: {e}")
            TLS_AVAILABLE = False
            return False
        
        from paths import PERSISTENT_DATA_DIR
        
        cert_dir = Path(PERSISTENT_DATA_DIR) / 'tls'
        
        try:
            cert_path, key_path = ensure_server_certificate(cert_dir)
        except RuntimeError as e:
            # Neither cryptography nor openssl CLI available
            log_error("TCP_SERVER", f"Cannot generate TLS certificate: {e}")
            TLS_AVAILABLE = False
            return False
        except Exception as e:
            log_error("TCP_SERVER", f"Unexpected error setting up TLS: {e}")
            TLS_AVAILABLE = False
            return False
        
        # Create SSL context
        self.ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self.ssl_context.load_cert_chain(
            certfile=str(cert_path),
            keyfile=str(key_path)
        )
        
        TLS_AVAILABLE = True
        log_debug("TCP_SERVER", f"TLS enabled with certificate: {cert_path}")
        return True
    
    def _setup_socket(self) -> None:
        """Create socket, bind, and start listening."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # Allow address reuse (helps with quick restarts)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)  # Backlog of 5 connections
            log_debug("TCP_SERVER", f"Listening on {self.host}:{self.port}")
        except Exception as e:
            try:
                self.server_socket.close()
            except Exception:
                pass
            raise OSError(f"Failed to bind TCP socket to {self.host}:{self.port}: {e}") from e
    
    def accept_client(self, timeout: Optional[float] = None) -> Optional[TCPClientHandler]:
        """
        Accept a client connection and perform TLS negotiation + authentication.
        
        Uses STARTTLS-style protocol:
        1. Accept plaintext TCP connection
        2. Receive client hello, send server response
        3. Upgrade to TLS if negotiated
        4. Perform challenge-response authentication
        
        Args:
            timeout: Optional timeout in seconds. None = blocking.
                     Returns None on timeout.
        
        Returns:
            TCPClientHandler for authenticated client, or None on timeout/failure.
            
        Raises:
            RuntimeError: If socket not initialized
        """
        if self.server_socket is None:
            raise RuntimeError("TCP socket not initialized")
        
        # Set timeout
        old_timeout = self.server_socket.gettimeout()
        if timeout is not None:
            self.server_socket.settimeout(timeout)
        
        try:
            client_socket, client_address = self.server_socket.accept()
            log_debug("TCP_SERVER", f"Connection from {client_address[0]}:{client_address[1]}")
            
            try:
                # Phase 1: TLS negotiation (STARTTLS-style)
                tls_active, client_socket = negotiate_tls_server(
                    client_socket,
                    tls_enabled=self.tls_enabled,
                    ssl_context=self.ssl_context
                )
                
                if tls_active:
                    log_debug("TCP_SERVER", f"TLS established for {client_address[0]}")
                else:
                    log_debug("TCP_SERVER", f"Plaintext connection for {client_address[0]}")
                
                # Phase 2: Authentication
                if authenticate_server(client_socket, self._password_info):
                    log_debug("TCP_SERVER", f"Client {client_address[0]} authenticated")
                    client_socket.settimeout(None)  # Clear timeout for normal ops
                    return TCPClientHandler(client_socket, client_address)
                else:
                    log_info("TCP_SERVER", f"Auth failed for {client_address[0]}:{client_address[1]}")
                    try:
                        client_socket.close()
                    except Exception:
                        pass
                    return None
                    
            except TlsNegotiationError as e:
                log_info("TCP_SERVER", f"TLS negotiation failed for {client_address[0]}: {e}")
                try:
                    client_socket.close()
                except Exception:
                    pass
                return None
            except Exception as e:
                log_error("TCP_SERVER", f"Error handling client {client_address[0]}: {e}")
                try:
                    client_socket.close()
                except Exception:
                    pass
                return None
                
        except socket.timeout:
            return None  # Timeout, not an error
        except Exception as e:
            log_error("TCP_SERVER", f"Error accepting connection: {e}")
            return None
        finally:
            if timeout is not None:
                self.server_socket.settimeout(old_timeout)
    
    def close(self) -> None:
        """Close server socket."""
        if self.server_socket is not None:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None
    
    def get_type(self) -> str:
        return "tcp_server"
    
    def get_address(self) -> Tuple[str, int]:
        """Return bound address (host, port)."""
        return (self.host, self.port)
