"""
IPC TCP Client Transport

TCP client transport for connecting to remote ZFS Agents.
Uses the modular security layer for TLS negotiation and authentication.
"""

import socket
from typing import Optional

# Import IPC transport bases
from ipc_client import DaemonTransport, LineBufferedTransport

# Import security layer
from ipc_security import (
    negotiate_tls_client,
    authenticate_client,
    TlsNegotiationError
)

# Import auth error for re-export
from ipc_tcp_auth import AuthError

# Import TLS manager for TOFU verification (optional)
try:
    from tls_manager import verify_certificate_tofu
    TLS_AVAILABLE = True
except ImportError:
    TLS_AVAILABLE = False
    verify_certificate_tofu = None

# Debug logging
from debug_logging import log_debug


# =============================================================================
# Re-export for compatibility
# =============================================================================

# Re-export TlsNegotiationError for callers
__all__ = ['TCPClientTransport', 'connect_to_agent', 'TlsNegotiationError', 'AuthError']


# =============================================================================
# Client Transport
# =============================================================================

class TCPClientTransport(DaemonTransport):
    """
    TCP client transport for connecting to a remote Agent.
    
    Uses STARTTLS-style negotiation: plaintext hello handshake first,
    then optional TLS upgrade, then authentication.
    """
    
    def __init__(self, host: str, port: int, password: str, 
                 timeout: float = 30.0, use_tls: bool = True):
        """
        Connect to a remote agent and authenticate.
        
        Args:
            host: Remote host IP or hostname
            port: Remote port
            password: Admin password for authentication
            timeout: Connection timeout in seconds
            use_tls: Whether client supports/wants TLS
            
        Raises:
            AuthError: If authentication fails
            TlsNegotiationError: If TLS negotiation fails
            ConnectionError: If connection fails
            TimeoutError: If connection times out
        """
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self.tls_active = False
        self.socket: Optional[socket.socket] = None
        
        # Warn if TLS requested but cryptography not installed locally
        if use_tls and not TLS_AVAILABLE:
            log_debug("TCP_CLIENT", "TLS requested but cryptography not installed locally")
        
        self._connect_and_authenticate(password, timeout)
    
    def _connect_and_authenticate(self, password: str, timeout: float) -> None:
        """Establish connection with hello handshake, optional TLS, and auth."""
        sock = None
        try:
            # Create socket and connect
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            
            log_debug("TCP_CLIENT", f"Connecting to {self.host}:{self.port}...")
            sock.connect((self.host, self.port))
            log_debug("TCP_CLIENT", "Connected, starting TLS negotiation...")
            
            # Phase 1: Hello handshake and optional TLS upgrade
            self.tls_active, sock = negotiate_tls_client(
                sock, 
                tls_supported=self.use_tls,
                host=self.host
            )
            
            if self.tls_active:
                log_debug("TCP_CLIENT", "TLS negotiation succeeded, connection encrypted")
                # Perform TOFU verification if available
                self._verify_certificate_tofu(sock)
            else:
                log_debug("TCP_CLIENT", "Proceeding without TLS (as negotiated)")
            
            # Phase 2: Authentication
            log_debug("TCP_CLIENT", "Starting authentication...")
            authenticate_client(sock, password)
            log_debug("TCP_CLIENT", "Authentication successful")
            
            # Store socket for later use
            self.socket = sock
            sock.settimeout(None)  # Clear timeout for normal operation
            
        except (TlsNegotiationError, AuthError):
            # Clean up and re-raise  
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
            raise
        except socket.timeout:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
            raise TimeoutError(f"Connection to {self.host}:{self.port} timed out")
        except Exception as e:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
            raise ConnectionError(f"Failed to connect to {self.host}:{self.port}: {e}")
    
    def _verify_certificate_tofu(self, ssl_socket) -> None:
        """Verify certificate using Trust-on-First-Use (if available)."""
        if not TLS_AVAILABLE or verify_certificate_tofu is None:
            return
        
        from pathlib import Path
        from paths import USER_CONFIG_DIR
        
        # Get server certificate
        cert_der = ssl_socket.getpeercert(binary_form=True)
        
        # Verify using TOFU
        verified, error_msg = verify_certificate_tofu(
            Path(USER_CONFIG_DIR),
            self.host,
            self.port,
            cert_der
        )
        
        if not verified:
            raise AuthError(error_msg)
    
    def send(self, data: bytes) -> None:
        """Send data through socket."""
        if self.socket is None:
            raise OSError("Socket not connected")
        self.socket.sendall(data)
    
    def receive(self, size: int = 4096) -> bytes:
        """Receive data from socket."""
        if self.socket is None:
            raise OSError("Socket not connected")
        return self.socket.recv(size)
    
    def fileno(self) -> int:
        """Return socket FD for select()."""
        if self.socket is None:
            raise OSError("Socket not connected")
        return self.socket.fileno()
    
    def close(self) -> None:
        """Close socket."""
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
    
    def get_type(self) -> str:
        if self.tls_active:
            return "tls+tcp"
        return "tcp"


# =============================================================================
# Helper Function
# =============================================================================

def connect_to_agent(host: str, port: int, password: str, 
                     timeout: float = 30.0, use_tls: bool = True) -> tuple:
    """
    Connect to a remote agent and return a line-buffered transport.
    
    Args:
        host: Remote host IP or hostname
        port: Remote port
        password: Admin password for authentication
        timeout: Connection timeout in seconds
        use_tls: Whether client supports/wants TLS (default: True)
        
    Returns:
        Tuple of (LineBufferedTransport, tls_active: bool)
        - tls_active is True only if TLS handshake succeeded
        
    Raises:
        AuthError: If authentication fails
        TlsNegotiationError: If TLS negotiation fails
        ConnectionError: If connection fails
        TimeoutError: If connection times out
    """
    tcp_transport = TCPClientTransport(host, port, password, timeout, use_tls)
    return LineBufferedTransport(tcp_transport), tcp_transport.tls_active