"""
IPC TCP Transport Layer (Agent Mode)

This module provides TCP-based transport for network-accessible daemon ("Agent Mode").
It includes Challenge-Response authentication using the admin password from credentials.json.

Server: TCPServerTransport - listens on a TCP port, authenticates clients
Client: TCPClientTransport - connects to a remote agent, performs auth handshake

Security Model:
- Server sends salt, iterations, and a random nonce
- Client derives key from password using PBKDF2, then computes HMAC(key, nonce)
- Server verifies HMAC using stored password hash
- Raw password is NEVER transmitted over the network
"""

import os
import sys
import socket
import json
import threading
from typing import Optional, Tuple

# Import from existing IPC modules for consistency
from ipc_client import DaemonTransport, LineBufferedTransport

# Import auth protocol
from ipc_tcp_auth import (
    _generate_auth_challenge,
    _verify_auth_response,
    AuthError
)

# Import constants
from constants import (
    DEFAULT_AGENT_PORT,
    AUTH_TIMEOUT_SECONDS
)

# Import credential constants
from config_manager import (
    PASSWORD_INFO_KEY,
    _read_credentials
)


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
            client_socket: The connected socket
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
    
    Listens on a TCP port, authenticates clients using Challenge-Response,
    and returns handlers for authenticated connections.
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_AGENT_PORT):
        """
        Initialize TCP server transport.
        
        Args:
            host: Interface to bind to (default: all interfaces)
            port: Port to listen on (default: 5555)
            
        Raises:
            OSError: If socket creation or binding fails
            RuntimeError: If credentials cannot be loaded
        """
        self.host = host
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self._password_info: Optional[dict] = None
        
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
                    print(f"TCP_SERVER: Loaded credentials for user '{user_data.get('username', 'unknown')}'", file=sys.stderr)
                    return
        
        raise RuntimeError(
            "Cannot start TCP server: No valid credentials found in credentials.json. "
            "Ensure the daemon has been started at least once to create default credentials."
        )
    
    def _setup_socket(self) -> None:
        """Create socket, bind, and start listening."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # Allow address reuse (helps with quick restarts)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)  # Backlog of 5 connections
            print(f"TCP_SERVER: Listening on {self.host}:{self.port}", file=sys.stderr)
        except Exception as e:
            try:
                self.server_socket.close()
            except Exception:
                pass
            raise OSError(f"Failed to bind TCP socket to {self.host}:{self.port}: {e}") from e
    
    def accept_client(self, timeout: Optional[float] = None) -> Optional[TCPClientHandler]:
        """
        Accept a client connection and perform authentication.
        
        Args:
            timeout: Optional timeout in seconds. None = blocking.
                     Returns None on timeout.
        
        Returns:
            TCPClientHandler for authenticated client, or None on timeout/auth failure.
            
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
            print(f"TCP_SERVER: Connection from {client_address[0]}:{client_address[1]}", file=sys.stderr)
            
            # Set auth timeout on client socket
            client_socket.settimeout(AUTH_TIMEOUT_SECONDS)
            
            # Perform authentication handshake
            if self._authenticate_client(client_socket, client_address):
                # Auth successful - clear timeout for normal operation
                client_socket.settimeout(None)
                return TCPClientHandler(client_socket, client_address)
            else:
                # Auth failed - close connection
                print(f"TCP_SERVER: Auth failed for {client_address[0]}:{client_address[1]}", file=sys.stderr)
                try:
                    client_socket.close()
                except Exception:
                    pass
                return None
                
        except socket.timeout:
            return None  # Timeout, not an error
        except Exception as e:
            print(f"TCP_SERVER: Error accepting connection: {e}", file=sys.stderr)
            return None
        finally:
            if timeout is not None:
                self.server_socket.settimeout(old_timeout)
    
    def _authenticate_client(self, client_socket: socket.socket, client_address: tuple) -> bool:
        """
        Perform Challenge-Response authentication with client.
        
        Returns:
            True if authenticated successfully, False otherwise
        """
        try:
            # Create file-like object for easier JSON I/O
            client_file = client_socket.makefile('rw', buffering=1, encoding='utf-8', errors='replace')
            
            try:
                # Generate and send challenge
                challenge, expected_hmac = _generate_auth_challenge(self._password_info)
                client_file.write(json.dumps(challenge) + '\n')
                client_file.flush()
                
                # Receive response
                response_line = client_file.readline()
                if not response_line:
                    print(f"TCP_SERVER: Client {client_address[0]} disconnected during auth", file=sys.stderr)
                    return False
                
                response = json.loads(response_line)
                
                if response.get("type") != "auth_response":
                    print(f"TCP_SERVER: Invalid auth response type from {client_address[0]}", file=sys.stderr)
                    return False
                
                # Verify HMAC
                client_hmac_hex = response.get("hmac", "")
                if _verify_auth_response(client_hmac_hex, expected_hmac):
                    # Send success
                    result = {"type": "auth_result", "success": True}
                    client_file.write(json.dumps(result) + '\n')
                    client_file.flush()
                    print(f"TCP_SERVER: Client {client_address[0]} authenticated successfully", file=sys.stderr)
                    return True
                else:
                    # Send failure and close
                    result = {"type": "auth_result", "success": False, "error": "Invalid credentials"}
                    client_file.write(json.dumps(result) + '\n')
                    client_file.flush()
                    print(f"TCP_SERVER: Invalid HMAC from {client_address[0]}", file=sys.stderr)
                    return False
                    
            finally:
                # Don't close client_file - it would close the socket
                # Just detach it (we'll create a new one in TCPClientHandler)
                pass
                
        except json.JSONDecodeError as e:
            print(f"TCP_SERVER: JSON error during auth from {client_address[0]}: {e}", file=sys.stderr)
            return False
        except socket.timeout:
            print(f"TCP_SERVER: Auth timeout from {client_address[0]}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"TCP_SERVER: Auth error from {client_address[0]}: {e}", file=sys.stderr)
            return False
    
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



