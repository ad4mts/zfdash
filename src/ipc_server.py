"""
IPC Server Transport Layer (Daemon Side)

This module provides server-side transport abstractions for the ZFS daemon.
Used by: zfs_daemon.py

Responsibilities:
- Transport mechanics - bind/listen/accept, read/write bytes
- Protocol framing - JSON line buffering
- Resource cleanup - close sockets, remove socket files
- Connection setup - establishing the communication channel

Security Note: This module contains NO daemon launching or privilege 
escalation code. Safe for import by root-privileged daemon.
"""

import os
import sys
import socket
import threading
from abc import ABC, abstractmethod
from typing import Optional

# Import socket helpers (shared utilities - no privilege escalation code)
from ipc_helpers import check_socket_in_use


class ServerTransport(ABC):
    """
    Abstract base class for server-side daemon transports.
    
    Server transports handle the daemon side of IPC:
    - Accept incoming connections
    - Read/write JSON lines
    - Cleanup resources
    """
    
    @abstractmethod
    def accept_connection(self) -> None:
        """
        Wait for and accept a client connection.
        
        For pipe transports, this is a no-op (already connected).
        For socket transports, this blocks until a client connects.
        
        Raises:
            OSError: If connection setup fails
        """
        pass
    
    @abstractmethod
    def receive_line(self) -> str:
        """
        Receive one complete line from client (blocking).
        
        Returns:
            String without trailing newline, or empty string on EOF
        """
        pass
    
    @abstractmethod
    def send_line(self, data: str) -> None:
        """
        Send one line to client with newline appended.
        
        Args:
            data: String to send (newline will be added if missing)
            
        Raises:
            OSError: If write fails
        """
        pass
    
    @abstractmethod
    def close(self) -> None:
        """
        Close transport and cleanup resources.
        
        This should be idempotent and safe to call multiple times.
        """
        pass
    
    @abstractmethod
    def get_type(self) -> str:
        """
        Return transport type name for logging.
        
        Returns:
            "pipe" or "socket"
        """
        pass


class _LineBuffer:
    """
    Internal helper for buffered line reading.
    
    Handles the common pattern of reading chunks and splitting by newlines. (Used neither by PipeServerTransport nor SocketServerTransport.. keep it for now)
    """
    
    def __init__(self, read_func):
        """
        Initialize line buffer.
        
        Args:
            read_func: Callable that reads bytes (e.g., file.read, sock.recv)
        """
        self.read_func = read_func
        self.buffer = ""
    
    def read_line(self) -> str:
        """
        Read one complete line (blocking).
        
        Returns:
            Line without trailing newline, or empty string on EOF
        """
        while '\n' not in self.buffer:
            try:
                chunk = self.read_func(4096)
                if isinstance(chunk, bytes):
                    chunk = chunk.decode('utf-8', errors='replace')
                if not chunk:  # EOF
                    remaining = self.buffer
                    self.buffer = ""
                    return remaining
                self.buffer += chunk
            except Exception:
                # On error, return any buffered data
                remaining = self.buffer
                self.buffer = ""
                return remaining
        
        # Extract one line
        line, self.buffer = self.buffer.split('\n', 1)
        return line


class PipeServerTransport(ServerTransport):
    """
    Server transport using stdin/stdout pipes.
    
    This is the default mode when daemon is launched via subprocess with
    stdin/stdout redirected to pipes.
    """
    
    def __init__(self):
        """Initialize pipe transport using sys.stdin/stdout."""
        self.input_stream = sys.stdin
        self.output_stream = sys.stdout
        self._write_lock = threading.Lock()  # Thread-safe writes for async daemon
    
    def accept_connection(self) -> None:
        """No-op for pipes - already connected via stdin/stdout."""
        pass
    
    def receive_line(self) -> str:
        """Read one line from stdin."""
        try:
            line = self.input_stream.readline()
            if not line:  # EOF
                return ""
            # Remove trailing newline
            return line.rstrip('\n\r')
        except Exception:
            return ""
    
    def send_line(self, data: str) -> None:
        """Write one line to stdout (thread-safe)."""
        with self._write_lock:
            if not data.endswith('\n'):
                data = data + '\n'
            self.output_stream.write(data)
            self.output_stream.flush()
    
    def close(self) -> None:
        """Close stdin/stdout (usually not needed, but safe to call)."""
        try:
            self.output_stream.flush()
        except Exception:
            pass
    
    def get_type(self) -> str:
        return "pipe"


class SocketServerTransport(ServerTransport):
    """
    Server transport using Unix domain socket.
    
    This mode creates a socket file, binds to it, sets permissions,
    and waits for a client to connect.
    """
    
    def __init__(self, socket_path: str, uid: int, gid: int):
        """
        Initialize socket server transport.
        
        Args:
            socket_path: Path to Unix domain socket file
            uid: User ID to set as socket owner (for permission control)
            gid: Group ID to set as socket group (for permission control)
            
        Raises:
            OSError: If socket creation, bind, or permission setting fails
        """
        self.socket_path = socket_path
        self.uid = uid
        self.gid = gid
        self.server_socket: Optional[socket.socket] = None
        self.client_socket: Optional[socket.socket] = None
        self.client_file = None  # File-like object from socket.makefile()
        self._write_lock = threading.Lock()  # Thread-safe writes for async daemon
        
        # Create and bind socket
        self._setup_socket()
    
    def _close_client(self) -> None:
        """Close current client connection if any."""
        if self.client_file is not None:
            try:
                self.client_file.close()
            except Exception:
                pass
            self.client_file = None
        
        if self.client_socket is not None:
            try:
                self.client_socket.close()
            except Exception:
                pass
            self.client_socket = None

    def _setup_socket(self) -> None:
        """Create socket, bind, and set permissions."""
        # Check if socket is already in use by another daemon
        if check_socket_in_use(self.socket_path):
            raise OSError(
                f"Socket {self.socket_path} is already in use by another daemon. "
                f"Use 'scripts/connect_webui_to_daemon.py --socket {self.socket_path}' "
                f"to connect to it, or stop the existing daemon first."
            )
        
        # Remove stale socket file if it exists (safe - we know it's not in use)
        try:
            os.unlink(self.socket_path)
        except OSError:
            pass
        
        # Create socket
        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        
        try:
            # Bind to path
            self.server_socket.bind(self.socket_path)
            
            # Set permissions: 0660 (rw-rw----)
            os.chmod(self.socket_path, 0o660)
            
            # linux-only: setting socket file owner/group and permissions depends on POSIX permissions
            # Set ownership to target user
            os.chown(self.socket_path, self.uid, self.gid)
            
            # Start listening (queue size 1 - allows one pending connection while processing current client)
            # Note: With queue=1, if a client is actively connected, a 2nd client can connect() but will
            # wait in queue until the 1st client's session ends. Queue=0 would reject immediately with ECONNREFUSED.
            self.server_socket.listen(1)
            
        except Exception as e:
            # Cleanup on error
            try:
                self.server_socket.close()
            except Exception:
                pass
            try:
                os.unlink(self.socket_path)
            except Exception:
                pass
            raise OSError(f"Failed to setup socket at {self.socket_path}: {e}") from e
    
    def accept_connection(self) -> None:
        """
        Wait for and accept a client connection (blocking).
        
        Raises:
            OSError: If accept fails
        """
        if self.server_socket is None:
            raise RuntimeError("Socket not initialized")
        
        # Close any previous client connection
        self._close_client()
        
        try:
            client_socket, _ = self.server_socket.accept()
            
            # Create file-like object with line buffering for easier I/O
            client_file = client_socket.makefile('rw', buffering=1, encoding='utf-8', errors='replace')
            
            self.client_socket = client_socket
            self.client_file = client_file
        except Exception as e:
            # Cleanup partial connection on error
            if 'client_socket' in locals():
                try:
                    client_socket.close()
                except Exception:
                    pass
            raise OSError(f"Failed to accept connection: {e}") from e
    
    def receive_line(self) -> str:
        """
        Read one line from connected client.
        
        Raises:
            RuntimeError: If called before accept_connection()
        """
        if self.client_file is None:
            raise RuntimeError("No client connected - call accept_connection() first")
        
        # Use readline() directly - simpler and more reliable than custom buffering
        line = self.client_file.readline()
        if not line:  # EOF
            return ""
        # Remove trailing newline
        return line.rstrip('\n\r')
    
    def send_line(self, data: str) -> None:
        """
        Send one line to connected client (thread-safe).
        
        Raises:
            RuntimeError: If called before accept_connection()
            OSError: If write fails
        """
        if self.client_file is None:
            raise RuntimeError("No client connected - call accept_connection() first")
        
        with self._write_lock:
            if not data.endswith('\n'):
                data = data + '\n'
            
            self.client_file.write(data)
            self.client_file.flush()
    
    def close(self) -> None:
        """
        Close client connection, server socket, and remove socket file.
        
        This is idempotent and safe to call multiple times.
        """
        # Close client connection
        self._close_client()
        
        # Close server socket
        if self.server_socket is not None:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None
        
        # Remove socket file
        if self.socket_path and os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except Exception:
                pass
    
    def get_type(self) -> str:
        return "socket"
