


import sys
import socket
import json
from typing import Optional

# Import IPC transport bases
from ipc_client import DaemonTransport, LineBufferedTransport

# Import auth protocol
from ipc_tcp_auth import (
    _compute_auth_response,
    AuthError
)

# Import constants
from config_manager import PBKDF2_ITERATIONS


# =============================================================================
# Client Side: TCPClientTransport
# =============================================================================

class TCPClientTransport(DaemonTransport):
    """
    TCP client transport for connecting to a remote Agent.
    
    Performs Challenge-Response authentication on connect.
    """
    
    def __init__(self, host: str, port: int, password: str, timeout: float = 30.0):
        """
        Connect to a remote agent and authenticate.
        
        Args:
            host: Remote host IP or hostname
            port: Remote port
            password: Admin password for authentication
            timeout: Connection timeout in seconds
            
        Raises:
            AuthError: If authentication fails
            ConnectionError: If connection fails
            TimeoutError: If connection or auth times out
        """
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        
        # Connect and authenticate
        self._connect_and_authenticate(password, timeout)
    
    def _connect_and_authenticate(self, password: str, timeout: float) -> None:
        """Establish connection and perform auth handshake."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(timeout)
            
            print(f"TCP_CLIENT: Connecting to {self.host}:{self.port}...", file=sys.stderr)
            self.socket.connect((self.host, self.port))
            print(f"TCP_CLIENT: Connected, starting authentication...", file=sys.stderr)
            
            # Create file-like object for JSON I/O
            sock_file = self.socket.makefile('rw', buffering=1, encoding='utf-8', errors='replace')
            
            try:
                # Receive challenge
                challenge_line = sock_file.readline()
                if not challenge_line:
                    raise ConnectionError("Server closed connection before sending challenge")
                
                challenge = json.loads(challenge_line)
                
                if challenge.get("type") != "auth_challenge":
                    raise AuthError(f"Unexpected message type: {challenge.get('type')}")
                
                # Extract challenge parameters
                salt_hex = challenge.get("salt", "")
                iterations = challenge.get("iterations", PBKDF2_ITERATIONS)
                nonce = challenge.get("nonce", "")
                
                if not salt_hex or not nonce:
                    raise AuthError("Invalid challenge: missing salt or nonce")
                
                # Compute response
                response_hmac = _compute_auth_response(password, salt_hex, iterations, nonce)
                
                # Send response
                response = {
                    "type": "auth_response",
                    "hmac": response_hmac
                }
                sock_file.write(json.dumps(response) + '\n')
                sock_file.flush()
                
                # Receive result
                result_line = sock_file.readline()
                if not result_line:
                    raise AuthError("Server closed connection after auth response")
                
                result = json.loads(result_line)
                
                if result.get("type") != "auth_result":
                    raise AuthError(f"Unexpected result type: {result.get('type')}")
                
                if not result.get("success"):
                    error_msg = result.get("error", "Authentication failed")
                    raise AuthError(error_msg)
                
                print(f"TCP_CLIENT: Authentication successful", file=sys.stderr)
                
                # Clear timeout for normal operation
                self.socket.settimeout(None)
                
            except Exception:
                sock_file.close()
                raise
                
        except socket.timeout:
            self._cleanup()
            raise TimeoutError(f"Connection to {self.host}:{self.port} timed out")
        except AuthError:
            self._cleanup()
            raise
        except Exception as e:
            self._cleanup()
            raise ConnectionError(f"Failed to connect to {self.host}:{self.port}: {e}")
    
    def _cleanup(self) -> None:
        """Clean up socket on error."""
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
    
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
        return "tcp"


# =============================================================================
# Helper: Create line-buffered client transport
# =============================================================================

def connect_to_agent(host: str, port: int, password: str, timeout: float = 30.0) -> LineBufferedTransport:
    """
    Connect to a remote agent and return a line-buffered transport.
    
    Args:
        host: Remote host IP or hostname
        port: Remote port
        password: Admin password for authentication
        timeout: Connection timeout in seconds
        
    Returns:
        LineBufferedTransport ready for JSON-line communication
        
    Raises:
        AuthError: If authentication fails
        ConnectionError: If connection fails
        TimeoutError: If connection times out
    """
    transport = TCPClientTransport(host, port, password, timeout)
    return LineBufferedTransport(transport)