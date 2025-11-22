"""
IPC Client Transport Layer (GUI/WebUI Side)

This module provides client-side transport abstractions and daemon launching.
Used by: zfs_manager.py, daemon_utils.py, connect_webui_to_daemon.py

Responsibilities:
- Connect to existing daemon (pipes or sockets)
- Launch daemon with privilege escalation (pkexec, sudo, doas)
- Wait for daemon ready signal
- Client-side transport wrappers

Note: This module contains privilege escalation code. Only import from
user-space processes, never from the daemon itself.
"""

import os
import sys
import socket
import select
import struct
import subprocess
import shutil
from paths import get_daemon_socket_path
import json
import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple


class DaemonTransport(ABC):
    """Abstract base class for daemon communication transports."""
    
    @abstractmethod
    def send(self, data: bytes) -> None:
        """Send data to daemon. Raises OSError on failure."""
        pass
    
    @abstractmethod
    def receive(self, size: int = 4096) -> bytes:
        """Receive data from daemon. Returns empty bytes on EOF."""
        pass
    
    @abstractmethod
    def fileno(self) -> int:
        """Return file descriptor for select/poll operations."""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close the transport."""
        pass
    
    @abstractmethod
    def get_type(self) -> str:
        """Return transport type name (for logging/debugging)."""
        pass


class PipeTransport(DaemonTransport):
    """Transport using anonymous pipes (stdin/stdout redirection)."""
    
    def __init__(self, write_fd: int, read_fd: int):
        """
        Initialize pipe transport.
        
        Args:
            write_fd: File descriptor to write TO daemon
            read_fd: File descriptor to read FROM daemon
        """
        self.write_fd = write_fd
        self.read_fd = read_fd
        # Open file objects for easier I/O (buffering handled by caller)
        try:
            self.write_file = os.fdopen(write_fd, 'wb', buffering=0)
            self.read_file = os.fdopen(read_fd, 'rb')
        except Exception as e:
            # Clean up on error
            try: os.close(write_fd)
            except: pass
            try: os.close(read_fd)
            except: pass
            raise OSError(f"Failed to open pipe file objects: {e}") from e
    
    def send(self, data: bytes) -> None:
        """Write data to daemon stdin pipe."""
        self.write_file.write(data)
        self.write_file.flush()  # Ensure immediate send
    
    def receive(self, size: int = 4096) -> bytes:
        """Read data from daemon stdout pipe."""
        # Use os.read on the FD directly to avoid file object buffering issues
        # File objects can block even when select() says data is available
        return os.read(self.read_file.fileno(), size)
    
    def fileno(self) -> int:
        """Return read pipe FD for select()."""
        return self.read_file.fileno()
    
    def close(self) -> None:
        """Close both pipe ends."""
        try:
            self.write_file.close()
        except Exception:
            pass
        try:
            self.read_file.close()
        except Exception:
            pass
    
    def get_type(self) -> str:
        return "pipe"


class SocketTransport(DaemonTransport):
    """Transport using Unix domain sockets."""
    
    def __init__(self, sock: socket.socket):
        """
        Initialize socket transport.
        
        Args:
            sock: Connected Unix domain socket
        """
        self.socket = sock
        self.socket.setblocking(True)  # Default to blocking I/O
    
    def send(self, data: bytes) -> None:
        """Send data through socket."""
        self.socket.sendall(data)
    
    def receive(self, size: int = 4096) -> bytes:
        """Receive data from socket."""
        return self.socket.recv(size)
    
    def fileno(self) -> int:
        """Return socket FD for select()."""
        return self.socket.fileno()
    
    def close(self) -> None:
        """Close socket."""
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.socket.close()
        except Exception:
            pass
    
    def get_type(self) -> str:
        return "socket"
    
    def get_peer_credentials(self) -> Optional[Tuple[int, int, int]]:
        """
        Get peer process credentials (Linux only).
        
        Returns:
            Tuple of (pid, uid, gid) or None if not available
        """
        try:
            # SO_PEERCRED returns struct ucred { pid_t pid; uid_t uid; gid_t gid; }
            creds = self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 
                                          struct.calcsize('3i'))
            pid, uid, gid = struct.unpack('3i', creds)
            return (pid, uid, gid)
        except (OSError, AttributeError):
            # AttributeError if SO_PEERCRED not available (non-Linux)
            # OSError if getsockopt fails
            return None


class LineBufferedTransport:
    """
    Wrapper that adds line-buffered reading to any DaemonTransport.
    
    This handles the JSON-line protocol used by the daemon:
    - Each message is one JSON object on a single line
    - Lines are terminated with newline
    """
    
    def __init__(self, transport: DaemonTransport):
        self.transport = transport
        self.buffer = b""
    
    def send_line(self, data: bytes) -> None:
        """Send data with newline appended."""
        if not data.endswith(b'\n'):
            data = data + b'\n'
        self.transport.send(data)
    
    def receive_line(self) -> bytes:
        """
        Receive one complete line (blocking).
        
        Returns:
            Complete line without trailing newline, or empty bytes on EOF
        """
        while b'\n' not in self.buffer:
            chunk = self.transport.receive(4096)
            if not chunk:  # EOF
                # Return any remaining buffered data, then empty on next call
                remaining = self.buffer
                self.buffer = b""
                return remaining
            self.buffer += chunk
        
        # Extract one line from buffer
        line, self.buffer = self.buffer.split(b'\n', 1)
        return line
    
    def fileno(self) -> int:
        """Delegate to underlying transport."""
        return self.transport.fileno()
    
    def close(self) -> None:
        """Close underlying transport."""
        self.transport.close()
    
    def get_type(self) -> str:
        """Return underlying transport type."""
        return self.transport.get_type()
    
    def get_transport(self) -> DaemonTransport:
        """Access underlying transport (for socket-specific ops)."""
        return self.transport


# ============================================================================
# Platform-Specific Daemon Launcher
# ============================================================================

def _find_privilege_escalation_tool() -> Optional[str]:
    """
    Find the appropriate privilege escalation tool for the current platform.
    
    Returns:
        Path to privilege escalation tool (pkexec, doas, sudo)
        or None if running as root or tool not found.
    """
    if os.getuid() == 0:
        return None  # Already root, no escalation needed
    
    # Linux: pkexec (PolicyKit)
    pkexec = shutil.which("pkexec")
    if pkexec:
        return pkexec
    
    # FreeBSD/OpenBSD: doas
    doas = shutil.which("doas")
    if doas:
        return doas
    
    # Fallback: sudo (less desirable, no GUI prompt)
    sudo = shutil.which("sudo")
    if sudo:
        return sudo
    
    return None


def _build_daemon_command(daemon_path: str, uid: int, gid: int, 
                         escalation_tool: Optional[str] = None,
                         is_script: bool = False) -> list:
    """
    Build the command array to launch the daemon.
    
    Args:
        daemon_path: Path to daemon executable or script
        uid: User ID to pass to daemon
        gid: Group ID to pass to daemon
        escalation_tool: Path to privilege escalation tool or None
        is_script: True if daemon_path is a Python script (needs interpreter)
    
    Returns:
        Command list suitable for subprocess.Popen
    """
    # Build base command
    if is_script:
        # Python script - need to invoke with interpreter
        base_cmd = [sys.executable, daemon_path, '--daemon', '--uid', str(uid), '--gid', str(gid)]
    else:
        # Frozen executable - run directly
        base_cmd = [daemon_path, '--daemon', '--uid', str(uid), '--gid', str(gid)]
    
    if escalation_tool is None:
        # Running as root or no escalation needed
        return base_cmd
    
    tool_name = os.path.basename(escalation_tool)
    
    if tool_name == "pkexec":
        # Linux PolicyKit
        return [escalation_tool] + base_cmd
    
    elif tool_name == "doas":
        # FreeBSD/OpenBSD doas
        return [escalation_tool] + base_cmd
    
    elif tool_name == "sudo":
        # Fallback sudo (will prompt in terminal, not GUI)
        return [escalation_tool, '-n'] + base_cmd  # -n = non-interactive
    
    else:
        # Unknown tool, try direct execution
        return [escalation_tool] + base_cmd


# ============================================================================
# Socket Helper Functions
# ============================================================================

def check_socket_in_use(socket_path: str) -> bool:
    """
    Check if a Unix socket is currently in use (daemon listening).
    
    Args:
        socket_path: Path to Unix domain socket file
        
    Returns:
        True if socket exists and daemon is listening, False otherwise
    """
    if not os.path.exists(socket_path):
        return False
    
    test_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        test_sock.connect(socket_path)
        test_sock.close()
        return True  # Socket is in use
    except (ConnectionRefusedError, FileNotFoundError):
        return False  # Socket file exists but not listening (stale)
    finally:
        try:
            test_sock.close()
        except Exception:
            pass


def check_and_remove_stale_socket(socket_path: str) -> bool:
    """
    Check if a socket file is stale (no daemon listening) and remove it.
    
    Args:
        socket_path: Path to Unix domain socket file
        
    Returns:
        True if socket was stale and removed, False if no socket exists,
        raises RuntimeError if socket is active (daemon already running)
        
    Raises:
        RuntimeError: If socket exists and daemon is listening on it
    """
    if not os.path.exists(socket_path):
        return False
    
    # Check if socket is in use
    if check_socket_in_use(socket_path):
        raise RuntimeError(
            f"A daemon is already running on socket {socket_path}. "
            f"Use 'python scripts/connect_webui_to_daemon.py --socket {socket_path}' "
            f"to connect to it, or stop the existing daemon first."
        )
    
    # Socket file exists but no daemon listening - it's stale
    try:
        os.unlink(socket_path)
        print(f"IPC: Removed stale socket at {socket_path}")
        return True
    except OSError as e:
        print(f"IPC: Warning - could not remove stale socket: {e}", file=sys.stderr)
        return False


def connect_to_unix_socket(socket_path: str, 
                          timeout: float = 10.0,
                          check_process: Optional[subprocess.Popen] = None) -> socket.socket:
    """
    Connect to Unix domain socket with retry logic and optional process monitoring.
    
    This function:
    - Polls for socket file to exist
    - Retries connection attempts (socket may exist but not be listening yet)
    - Optionally monitors a process for premature exit
    
    Args:
        socket_path: Path to Unix domain socket
        timeout: Total timeout in seconds
        check_process: Optional subprocess to monitor for premature exit
        
    Returns:
        Connected socket.socket object
        
    Raises:
        RuntimeError: If process exits prematurely
        TimeoutError: If connection not established within timeout
        OSError: If socket connection fails
    """
    start_time = time.time()
    client_sock = None
    
    while time.time() - start_time < timeout:
        # Check if monitored process died
        if check_process and check_process.poll() is not None:
            raise RuntimeError(
                f"Process exited prematurely (exit code: {check_process.returncode})"
            )
        
        # Try to connect to socket
        if os.path.exists(socket_path):
            try:
                client_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client_sock.connect(socket_path)
                return client_sock  # Success!
            except (socket.error, ConnectionRefusedError):
                # Socket exists but not ready yet - retry
                if client_sock:
                    try:
                        client_sock.close()
                    except Exception:
                        pass
                    client_sock = None
                time.sleep(0.1)
        else:
            # Socket not created yet - retry
            time.sleep(0.1)
    
    # Timeout reached
    raise TimeoutError(
        f"Could not connect to socket within {timeout} seconds at {socket_path}. "
        f"If the daemon is running, another client may be actively connected (sequential mode). "
        f"Wait for the other client to disconnect, or increase --timeout."
    )


def wait_for_ready_signal(transport: 'LineBufferedTransport',
                          process: Optional[subprocess.Popen] = None,
                          timeout: int = 60) -> None:
    """
    Wait for daemon to send ready signal via transport.
    
    Generic version that works with or without process monitoring.
    
    Args:
        transport: LineBufferedTransport to read from
        process: Optional daemon subprocess to monitor for premature exit
        timeout: Timeout in seconds
    
    Raises:
        RuntimeError: If daemon exits prematurely or sends invalid signal
        TimeoutError: If ready signal not received within timeout
    """
    if process:
        print(f"IPC: Waiting for ready signal from daemon (PID: {process.pid})...")
    else:
        print("IPC: Waiting for ready signal from daemon...")
    
    start_time = time.monotonic()
    
    try:
        while time.monotonic() - start_time < timeout:
            # Check if daemon exited prematurely (if monitoring)
            if process:
                proc_status = process.poll()
                if proc_status is not None:
                    raise RuntimeError(
                        f"Daemon exited prematurely (status {proc_status}). "
                        "Authentication likely failed or cancelled."
                    )
            
            # Check for data with select (non-blocking check)
            readable, _, _ = select.select([transport.fileno()], [], [], 0.1)
            
            if readable:
                try:
                    line_bytes = transport.receive_line()
                    
                    if not line_bytes:  # EOF
                        if process:
                            proc_status = process.poll()
                            raise RuntimeError(
                                f"Daemon closed connection (EOF) before ready signal. "
                                f"Exit status: {proc_status}"
                            )
                        else:
                            raise RuntimeError(
                                "Daemon closed connection (EOF) before ready signal."
                            )
                    
                    line = line_bytes.decode('utf-8', errors='replace').strip()
                    print(f"IPC: Received from daemon: {line}")
                    
                    try:
                        signal = json.loads(line)
                        if isinstance(signal, dict) and signal.get("status") == "ready":
                            print("IPC: Received valid ready signal.")
                            return  # Success!
                        else:
                            print(f"IPC: Unexpected JSON (not ready signal): {line}", 
                                 file=sys.stderr)
                    except json.JSONDecodeError:
                        print(f"IPC: Non-JSON line from daemon: {line}", 
                             file=sys.stderr)
                
                except BlockingIOError:
                    pass  # No data right now
                except OSError as e:
                    if process:
                        proc_status = process.poll()
                        raise RuntimeError(f"Error reading from daemon: {e} (status {proc_status})")
                    else:
                        raise RuntimeError(f"Error reading from daemon: {e}")
        
        # Timeout reached
        raise TimeoutError(f"Daemon did not send ready signal within {timeout} seconds.")
    
    except Exception:
        raise  # Re-raise to caller


def launch_daemon_process(daemon_path: str, uid: int, gid: int, is_script: bool = False, use_socket: bool = False) -> Tuple[subprocess.Popen, LineBufferedTransport]:
    """
    Launch privileged daemon process and establish communication.
    
    Args:
        daemon_path: Path to daemon executable or script
        uid: User ID to pass to daemon (for permission context)
        gid: Group ID to pass to daemon (for permission context)
        is_script: True if daemon_path is a Python script (needs sys.executable)
        use_socket: If True, daemon creates Unix socket and acts as server; client connects
    
    Returns:
        Tuple of (subprocess.Popen, LineBufferedTransport)
    
    Raises:
        RuntimeError: If privilege escalation tool not found or daemon launch fails
        TimeoutError: If daemon doesn't send ready signal or socket not created in time
        OSError: If pipe/socket connection fails
    """
    if use_socket:
        return _launch_daemon_with_socket_server(daemon_path, uid, gid, is_script)
    else:
        return _launch_daemon_with_pipes(daemon_path, uid, gid, is_script)


def _launch_daemon_with_socket_server(daemon_path: str, uid: int, gid: int, is_script: bool = False) -> Tuple[subprocess.Popen, LineBufferedTransport]:
    """
    Launch daemon as socket server - daemon creates socket and listens, client connects.
    
    This simplified approach:
    - Daemon creates Unix socket at /run/user/{uid}/zfdash.sock (Linux)
    - Daemon listens for connections
    - Client waits for socket to exist then connects
    - Consistent with standalone daemon server mode
    
    Args:
        daemon_path: Path to daemon executable or script
        uid: User ID to pass to daemon (for permission context)
        gid: Group ID to pass to daemon (for permission context)
        is_script: True if daemon_path is a Python script (needs sys.executable)
    
    Returns:
        Tuple of (subprocess.Popen, LineBufferedTransport)
    
    Raises:
        RuntimeError: If daemon launch fails
        TimeoutError: If socket not created or ready signal not received in time
    """
    import socket as socket_module
    import time
    
    print(f"IPC: Launching daemon as socket server from: {daemon_path} (script: {is_script})")
    print(f"IPC: User context: UID={uid}, GID={gid}")
    
    # Find privilege escalation tool
    escalation_tool = _find_privilege_escalation_tool()
    if escalation_tool:
        print(f"IPC: Using privilege escalation: {escalation_tool}")
    else:
        if os.getuid() != 0:
            raise RuntimeError("No privilege escalation tool found. Cannot launch daemon as root.")
        print("IPC: Running as root, no escalation needed.")
    
    # Get socket path from centralized path configuration
    socket_path = get_daemon_socket_path(uid)
    socket_dir = os.path.dirname(socket_path)
    os.makedirs(socket_dir, exist_ok=True)
    
    # Check for stale socket and remove it, or raise if daemon already running
    check_and_remove_stale_socket(socket_path)
    
    # Build daemon command with --listen-socket argument
    cmd = _build_daemon_command(daemon_path, uid, gid, escalation_tool, is_script)
    cmd.extend(['--listen-socket', socket_path])
    print(f"IPC: Command: {' '.join(cmd)}")
    
    # Launch daemon (it will create and listen on socket)
    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
        print(f"IPC: Daemon launched (PID: {process.pid}), waiting for socket to be ready...")
    except Exception as e:
        raise RuntimeError(f"Failed to launch daemon process: {e}") from e
    
    # Connect to socket with retry and process monitoring
    try:
        client_sock = connect_to_unix_socket(socket_path, timeout=10.0, check_process=process)
        print(f"IPC: Connected to daemon socket at {socket_path}")
        
        # Wrap socket in transport
        transport = SocketTransport(client_sock)
        buffered_transport = LineBufferedTransport(transport)
        
        # Wait for ready signal
        wait_for_ready_signal(buffered_transport, process)
        
        print("IPC: Socket transport created successfully.")
        return process, buffered_transport
        
    except Exception as e:
        print(f"IPC: Socket connection failed: {e}", file=sys.stderr)
        if client_sock:
            try:
                client_sock.close()
            except Exception:
                pass
        # Terminate daemon if started
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except Exception:
                pass
        raise


def _launch_daemon_with_pipes(daemon_path: str, uid: int, gid: int, is_script: bool = False) -> Tuple[subprocess.Popen, LineBufferedTransport]:
    """
    Launch privileged daemon process using anonymous pipe communication.
    
    This function handles:
    - Finding appropriate privilege escalation tool (pkexec, doas, sudo)
    - Creating anonymous pipes for bidirectional communication
    - Launching daemon with proper privilege escalation
    - Waiting for daemon ready signal
    - Creating transport abstraction for IPC
    
    Args:
        daemon_path: Path to daemon executable or script
        uid: User ID to pass to daemon (for permission context)
        gid: Group ID to pass to daemon (for permission context)
        is_script: True if daemon_path is a Python script (needs sys.executable)
    
    Returns:
        Tuple of (subprocess.Popen, LineBufferedTransport)
        - Popen object for process management
        - LineBufferedTransport for JSON-line protocol communication
    
    Raises:
        RuntimeError: If privilege escalation tool not found, daemon launch fails,
                     or daemon exits prematurely
        TimeoutError: If daemon doesn't send ready signal in time
        OSError: If pipe creation fails
    """
    print(f"IPC: Launching daemon from: {daemon_path} (script: {is_script})")
    print(f"IPC: User context: UID={uid}, GID={gid}")
    
    # Find privilege escalation tool
    escalation_tool = _find_privilege_escalation_tool()
    if escalation_tool:
        print(f"IPC: Using privilege escalation: {escalation_tool}")
    else:
        if os.getuid() != 0:
            raise RuntimeError(
                "No privilege escalation tool found (pkexec, doas, sudo). "
                "Cannot launch daemon as root."
            )
        print("IPC: Running as root, no escalation needed.")
    
    # Build command
    cmd = _build_daemon_command(daemon_path, uid, gid, escalation_tool, is_script)
    print(f"IPC: Command: {' '.join(cmd)}")
    
    # Create pipes
    pipe_to_daemon_r, pipe_to_daemon_w = -1, -1
    pipe_from_daemon_r, pipe_from_daemon_w = -1, -1
    
    try:
        # Parent->Daemon pipe (parent writes, daemon reads stdin)
        pipe_to_daemon_r, pipe_to_daemon_w = os.pipe()
        # Daemon->Parent pipe (daemon writes stdout, parent reads)
        pipe_from_daemon_r, pipe_from_daemon_w = os.pipe()
        
        print(f"IPC: Pipes created: P->D ({pipe_to_daemon_r},{pipe_to_daemon_w}), "
              f"D->P ({pipe_from_daemon_r},{pipe_from_daemon_w})")
        
    except OSError as e:
        # Cleanup any created pipes
        for fd in [pipe_to_daemon_r, pipe_to_daemon_w, 
                   pipe_from_daemon_r, pipe_from_daemon_w]:
            if fd != -1:
                try: os.close(fd)
                except: pass
        raise OSError(f"Failed to create communication pipes: {e}") from e
    
    # Launch daemon process
    process = None
    try:
        process = subprocess.Popen(
            cmd,
            stdin=pipe_to_daemon_r,     # Daemon reads from this
            stdout=pipe_from_daemon_w,  # Daemon writes to this
            stderr=subprocess.DEVNULL,  # Suppress stderr (daemon logs elsewhere)
            env=os.environ.copy(),
        )
        
        # Parent closes the ends used by child
        os.close(pipe_to_daemon_r)
        os.close(pipe_from_daemon_w)
        pipe_to_daemon_r = -1
        pipe_from_daemon_w = -1
        
        print(f"IPC: Daemon launched (PID: {process.pid})")
        
        # Create transport wrapper BEFORE waiting for ready signal
        # This way the FDs are properly wrapped and buffered
        transport = PipeTransport(pipe_to_daemon_w, pipe_from_daemon_r)
        buffered_transport = LineBufferedTransport(transport)
        
        # Wait for ready signal through the transport
        wait_for_ready_signal(buffered_transport, process)
        
        print("IPC: Transport created successfully.")
        return process, buffered_transport
        
    except Exception as e:
        print(f"IPC: Error during daemon launch: {e}", file=sys.stderr)
        
        # Cleanup pipes
        for fd in [pipe_to_daemon_r, pipe_to_daemon_w, 
                   pipe_from_daemon_r, pipe_from_daemon_w]:
            if fd != -1:
                try: os.close(fd)
                except Exception: pass
        
        # Terminate daemon if started
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except Exception:
                pass
        
        # Re-raise appropriate exception
        if isinstance(e, (RuntimeError, TimeoutError, OSError)):
            raise
        else:
            raise RuntimeError(f"Daemon launch failed: {e}") from e
