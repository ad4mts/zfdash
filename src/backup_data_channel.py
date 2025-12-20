"""
Backup Data Channel Transport Layer

Provides transport abstractions for backup data streams:
- DataChannelClient: Connect to data channel, send chunks
- DataChannelServer: Accept connection, receive chunks

Encapsulates TLS upgrade, token authentication, and length-prefixed framing.
No hello negotiation - TLS state is decided via control channel.
"""

import socket
import ssl
import secrets
import json
from typing import Optional, Tuple
from pathlib import Path

from debug_logging import daemon_log, log_debug
from constants import DATA_CHANNEL_ACCEPT_TIMEOUT, DATA_CHANNEL_STREAMING_TIMEOUT


# =============================================================================
# TLS Utility Functions
# =============================================================================

def create_client_ssl_context() -> ssl.SSLContext:
    """
    Create SSL context for data channel client.
    
    Uses permissive settings for self-signed certificates.
    """
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # Self-signed cert support
    return ctx


def create_server_ssl_context(cert_path: Path, key_path: Path) -> ssl.SSLContext:
    """
    Create SSL context for data channel server.
    
    Args:
        cert_path: Path to certificate file
        key_path: Path to private key file
    """
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return ctx


def ensure_data_channel_ssl_context() -> Optional[ssl.SSLContext]:
    """
    Get or create server SSL context using existing agent certificates.
    
    Returns:
        SSLContext if TLS is available, None otherwise
    """
    try:
        from tls_manager import ensure_server_certificate
        from paths import PERSISTENT_DATA_DIR
        
        cert_dir = Path(PERSISTENT_DATA_DIR) / 'tls'
        cert_path, key_path = ensure_server_certificate(cert_dir)
        return create_server_ssl_context(cert_path, key_path)
    except Exception as e:
        daemon_log(f"DATA_CHANNEL: TLS setup failed: {e}", "WARNING")
        return None


# =============================================================================
# DataChannelClient - Client-side transport
# =============================================================================

class DataChannelClient:
    """
    Client transport for connecting to a backup data channel.
    
    Handles: TCP connect -> TLS upgrade (if enabled) -> token auth -> chunk I/O
    
    Usage:
        client = DataChannelClient(host, port, token, use_tls=True)
        client.connect()
        for chunk in data:
            client.send_chunk(chunk)
        client.send_end_of_stream()
        response = client.receive_response()
        client.close()
    """

    
    def __init__(self, host: str, port: int, token: str, 
                 use_tls: bool = True, timeout: float = 30.0):
        """
        Initialize data channel client.
        
        Args:
            host: Destination host
            port: Data channel port
            token: Authentication token (hex string)
            use_tls: Whether to use TLS encryption
            timeout: Connection timeout in seconds
        """
        self.host = host
        self.port = port
        self.token = token
        self.use_tls = use_tls
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None
    
    def connect(self) -> None:
        """
        Connect to data channel, upgrade TLS if enabled, authenticate.
        
        Raises:
            ConnectionError: If connection fails
            ssl.SSLError: If TLS handshake fails
        """
        try:
            # Create and connect socket
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.timeout)
            self._socket.connect((self.host, self.port))
            log_debug("DATA_CHANNEL", f"Connected to {self.host}:{self.port}")
            
            # TLS upgrade if enabled
            if self.use_tls:
                ctx = create_client_ssl_context()
                self._socket = ctx.wrap_socket(self._socket, server_hostname=self.host)
                log_debug("DATA_CHANNEL", "TLS client wrap completed")
            
            # Send authentication token
            self._socket.sendall(self.token.encode('ascii'))
            log_debug("DATA_CHANNEL", "Token sent, connected")
            
            # Switch to streaming timeout (longer than connection timeout)
            # This prevents hanging if receiver stops reading
            self._socket.settimeout(DATA_CHANNEL_STREAMING_TIMEOUT)
            
        except Exception as e:
            self.close()
            raise ConnectionError(f"Data channel connection failed: {e}") from e
    
    def send_chunk(self, data: bytes) -> None:
        """
        Send a data chunk with length prefix.
        
        Args:
            data: Raw bytes to send
            
        Raises:
            OSError: If send fails
        """
        if not self._socket:
            raise OSError("Not connected")
        length_prefix = len(data).to_bytes(4, 'big')
        self._socket.sendall(length_prefix + data)
    
    def send_end_of_stream(self) -> None:
        """Send zero-length chunk to signal end of stream."""
        if not self._socket:
            raise OSError("Not connected")
        self._socket.sendall(b'\x00\x00\x00\x00')
    
    def receive_response(self, timeout: float = 60.0) -> dict:
        """
        Receive final JSON response from server.
        
        Args:
            timeout: Read timeout in seconds
            
        Returns:
            Parsed JSON response dict
        """
        if not self._socket:
            raise OSError("Not connected")
        
        self._socket.settimeout(timeout)
        buffer = b""
        
        try:
            while b'\n' not in buffer:
                chunk = self._socket.recv(4096)
                if not chunk:
                    # Connection closed - this is likely an error on the receiver side
                    log_debug("DATA_CHANNEL", "Connection closed while waiting for response")
                    return {"status": "error", "error": "Connection closed unexpectedly by receiver"}
                buffer += chunk
        except socket.timeout:
            log_debug("DATA_CHANNEL", "Timeout waiting for response, assuming success")
            return {"status": "success"}
        
        if buffer:
            try:
                return json.loads(buffer.decode('utf-8').strip())
            except json.JSONDecodeError:
                return {"status": "success"}  # Partial response, assume success
        
        # Empty buffer after loop = connection was closed without response
        return {"status": "error", "error": "No response received from receiver"}
    
    def close(self) -> None:
        """Close the connection."""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None


# =============================================================================
# DataChannelServer - Server-side transport
# =============================================================================

class DataChannelServer:
    """
    Server transport for receiving a backup data stream.
    
    Handles: bind random port -> accept one connection -> TLS upgrade -> token verify
    
    Usage:
        server = DataChannelServer(use_tls=True)
        port, token = server.start()
        # ... communicate port/token to sender via control channel ...
        server.accept_and_verify()  # Blocking
        while chunk := server.recv_chunk():
            process_chunk(chunk)
        server.send_response({"status": "success"})
        server.close()
    """
    
    TOKEN_LENGTH = 32  # Bytes for random token (64 hex chars)
    
    def __init__(self, use_tls: bool = True, 
                 accept_timeout: float = DATA_CHANNEL_ACCEPT_TIMEOUT,
                 streaming_timeout: float = DATA_CHANNEL_STREAMING_TIMEOUT):
        """
        Initialize data channel server.
        
        Args:
            use_tls: Whether to use TLS encryption
            accept_timeout: Seconds to wait for sender connection
            streaming_timeout: Seconds to wait for data during transfer (prevents hanging on dead sender)
        """
        self.use_tls = use_tls
        self.accept_timeout = accept_timeout
        self.streaming_timeout = streaming_timeout
        
        self._server_socket: Optional[socket.socket] = None
        self._client_socket: Optional[socket.socket] = None
        self._ssl_context: Optional[ssl.SSLContext] = None
        self._token: Optional[str] = None
        self._port: Optional[int] = None
    
    def start(self) -> Tuple[int, str]:
        """
        Start listening on a random port.
        
        Returns:
            Tuple of (port, token) for sender to use
            
        Raises:
            RuntimeError: If server fails to start
        """
        # Generate auth token
        self._token = secrets.token_hex(self.TOKEN_LENGTH)
        
        # Setup TLS if requested
        if self.use_tls:
            self._ssl_context = ensure_data_channel_ssl_context()
            if not self._ssl_context:
                daemon_log("DATA_CHANNEL: TLS unavailable, proceeding without", "WARNING")
        
        # Bind to random port
        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind(("0.0.0.0", 0))
            self._server_socket.listen(1)
            self._server_socket.settimeout(self.accept_timeout)
            
            _, self._port = self._server_socket.getsockname()
            daemon_log(f"DATA_CHANNEL: Server listening on port {self._port}", "DEBUG")
            
            return self._port, self._token
            
        except OSError as e:
            raise RuntimeError(f"Failed to start data channel server: {e}")
    
    def accept_and_verify(self) -> None:
        """
        Accept one connection, upgrade TLS, verify token.
        
        Raises:
            TimeoutError: If no connection within timeout
            AuthError: If token verification fails
            ssl.SSLError: If TLS handshake fails
        """
        if not self._server_socket:
            raise RuntimeError("Server not started")
        
        try:
            client_socket, addr = self._server_socket.accept()
            log_debug("DATA_CHANNEL", f"Connection from {addr[0]}:{addr[1]}")
        except socket.timeout:
            raise TimeoutError("Sender did not connect within timeout")
        
        # TLS upgrade if context available
        if self._ssl_context:
            try:
                client_socket = self._ssl_context.wrap_socket(client_socket, server_side=True)
                log_debug("DATA_CHANNEL", "TLS server wrap completed")
            except ssl.SSLError as e:
                client_socket.close()
                raise
        
        # Read and verify token (TOKEN_LENGTH * 2 = 64 hex chars)
        try:
            token_bytes = self._recv_exact(client_socket, self.TOKEN_LENGTH * 2)
            if token_bytes is None:
                client_socket.close()
                raise ConnectionError("Connection closed before token received")
            
            received_token = token_bytes.decode('ascii', errors='replace')
            if not secrets.compare_digest(received_token, self._token):
                client_socket.close()
                raise PermissionError("Invalid authentication token")
            
            log_debug("DATA_CHANNEL", "Token verified")
            self._client_socket = client_socket
            
            # Set streaming timeout now that connection is established
            self._client_socket.settimeout(self.streaming_timeout)
            
        except Exception:
            client_socket.close()
            raise
    
    def recv_chunk(self) -> Optional[bytes]:
        """
        Receive one length-prefixed chunk.
        
        Returns:
            Chunk data, or None if end of stream (zero-length marker)
        """
        if not self._client_socket:
            raise RuntimeError("No client connected")
        
        # Read 4-byte length header
        length_bytes = self._recv_exact(self._client_socket, 4)
        if length_bytes is None:
            return None
        
        chunk_length = int.from_bytes(length_bytes, 'big')
        
        # Zero length = end of stream
        if chunk_length == 0:
            return None
        
        # Read chunk data
        return self._recv_exact(self._client_socket, chunk_length)
    
    def send_response(self, response: dict) -> None:
        """Send JSON response to client."""
        if self._client_socket:
            try:
                data = json.dumps(response).encode('utf-8') + b'\n'
                self._client_socket.sendall(data)
            except Exception:
                pass
    
    def close(self) -> None:
        """Close all sockets."""
        if self._client_socket:
            try:
                self._client_socket.close()
            except Exception:
                pass
            self._client_socket = None
        
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None
    
    def _recv_exact(self, sock: socket.socket, n: int) -> Optional[bytes]:
        """
        Receive exactly n bytes, or None on error/close.
        
        Raises:
            TimeoutError: If socket timeout expires (sender likely dead)
        """
        data = b""
        while len(data) < n:
            try:
                chunk = sock.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                # Re-raise as TimeoutError for clearer handling upstream
                raise TimeoutError(f"No data received for {self.streaming_timeout}s - sender may have crashed")
            except (socket.error, ssl.SSLError):
                return None
        return data
    
    @property
    def token(self) -> Optional[str]:
        """Get the authentication token."""
        return self._token
    
    @property
    def port(self) -> Optional[int]:
        """Get the bound port."""
        return self._port
