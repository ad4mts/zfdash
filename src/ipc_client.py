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
import struct
import subprocess
import shutil
try:
    import termios
except ImportError:
    termios = None
from paths import get_daemon_socket_path
from abc import ABC, abstractmethod
from typing import Optional, Tuple
import constants

# Import shared socket helpers (no privilege escalation code)
from ipc_helpers import (
    check_socket_in_use,
    check_and_remove_stale_socket,
    connect_to_unix_socket,
    wait_for_ready_signal
)


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
            # linux-only: SO_PEERCRED is Linux-specific socket option
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
# Connect to existing daemon
# ============================================================================
def connect_to_daemon():
    """
    Connect to an existing daemon with auto-detected socket path.
    
    This is the abstracted public interface for connecting to an existing daemon.
    Callers should use this instead of connect_to_existing_socket_daemon directly.
    
    Returns:
        LineBufferedTransport connected to the daemon
        
    Raises:
        FileNotFoundError: If daemon socket doesn't exist
        RuntimeError: If connection fails
    """
    socket_path = get_daemon_socket_path(os.getuid())
    return connect_to_existing_socket_daemon(socket_path)

def connect_to_existing_socket_daemon(socket_path: str):
    """
    Connect to an existing socket daemon.
    
    Args:
        socket_path: Path to Unix domain socket
        
    Returns:
        LineBufferedTransport connected to the daemon
        
    Raises:
        FileNotFoundError: If socket doesn't exist
        RuntimeError: If connection fails (stale socket, daemon not responding)
    """
    
    if not os.path.exists(socket_path):
        raise FileNotFoundError(
            f"Daemon socket not found: {socket_path}\n"
            f"Start the daemon with: sudo python3 src/main.py --daemon --uid $(id -u) --gid $(id -g) --listen-socket"
        )
    
    print(f"IPC: Connecting to existing daemon socket at {socket_path}...", file=sys.stderr)
    try:
        # Short timeout for existing daemon (should connect immediately)
        client_sock = connect_to_unix_socket(socket_path, timeout=5.0, check_process=None)
        transport = SocketTransport(client_sock)
        buffered = LineBufferedTransport(transport)
        wait_for_ready_signal(buffered, process=None, timeout=constants.IPC_CONNECT_TIMEOUT)
        print(f"IPC: Successfully connected to existing daemon.", file=sys.stderr)
        return buffered
    except (TimeoutError, RuntimeError, OSError) as e:
        raise RuntimeError(f"IPC: Socket exists but connection failed: {e}")

# ============================================================================
# Stop existing daemon
# ============================================================================
def stop_daemon() -> bool:
    """
    Stop not running daemon with auto-detected socket path.
    
    This is the abstracted public interface for stopping the daemon.
    Callers should use this instead of stop_socket_daemon directly.
    
    Returns:
        True if daemon was stopped or socket was cleaned up
        False if no socket exists (nothing to do)
    """
    socket_path = get_daemon_socket_path(os.getuid())
    return stop_socket_daemon(socket_path)

def stop_socket_daemon(socket_path: str = None) -> bool:
    """
    Stop a running socket daemon, or clean up stale socket if daemon not running.
    
    Args:
        socket_path: Path to Unix domain socket (uses default if None)
        
    Returns:
        True if daemon was stopped or socket was cleaned up
        False if no socket exists (nothing to do)
    """
    import json
    from ipc_helpers import check_and_remove_stale_socket
    
    if socket_path is None:
        from paths import get_daemon_socket_path
        socket_path = get_daemon_socket_path(os.getuid())
    
    if not os.path.exists(socket_path):
        print(f"IPC: No daemon socket found at {socket_path}", file=sys.stderr)
        return False
    
    try:
        transport = connect_to_existing_socket_daemon(socket_path)
    except (FileNotFoundError, RuntimeError):
        # Socket exists but can't connect - use helper to remove stale socket
        check_and_remove_stale_socket(socket_path)
        return True
    
    try:
        # Send shutdown command
        request = {"command": "shutdown_daemon", "args": [], "kwargs": {}, "meta": {"request_id": 0}}
        transport.send_line(json.dumps(request).encode('utf-8'))
        
        # Read response
        response_line = transport.receive_line()
        if response_line:
            response = json.loads(response_line.decode('utf-8'))
            if response.get("status") == "success":
                print(f"IPC: Daemon shutdown successful.", file=sys.stderr)
                return True
            else:
                raise RuntimeError(f"Shutdown failed: {response.get('error', 'Unknown error')}")
        else:
            # EOF - daemon already shutting down
            print(f"IPC: Daemon shutdown (connection closed).", file=sys.stderr)
            return True
    finally:
        transport.close()


# ============================================================================
# Platform-Specific Daemon Launcher
# ============================================================================

def _get_privilege_escalation_tools() -> list:
    """
    Get ordered list of available privilege escalation tools.
    
    Returns:
        List of paths to privilege escalation tools in preference order:
        [pkexec, sudo, doas] (only includes tools that exist on system)
        Returns empty list if running as root.
    """
    if os.getuid() == 0:
        return []  # Already root, no escalation needed
    
    tools = []
    
    # Linux: pkexec (PolicyKit) - preferred for GUI auth dialog
    # linux-only: pkexec/PolicyKit is Linux-specific
    pkexec = shutil.which("pkexec")
    if pkexec:
        tools.append(pkexec)
    
    # sudo - works in TTY and non-TTY (with -n)
    sudo = shutil.which("sudo")
    if sudo:
        tools.append(sudo)
    
    # FreeBSD/OpenBSD: doas
    doas = shutil.which("doas")
    if doas:
        tools.append(doas)
    
    return tools


def _find_privilege_escalation_tool(exclude: Optional[list] = None) -> Optional[str]:
    """
    Find the next available privilege escalation tool.
    
    Args:
        exclude: List of tool paths to skip (used for fallback after auth failure)
    
    Returns:
        Path to privilege escalation tool (pkexec, sudo, doas)
        or None if running as root or no tool available.
    """
    if os.getuid() == 0:
        return None  # Already root, no escalation needed
    
    exclude = exclude or []
    tools = _get_privilege_escalation_tools()
    
    for tool in tools:
        if tool not in exclude:
            return tool
    
    return None


def _build_daemon_command(daemon_path: str, uid: int, gid: int, 
                         escalation_tool: Optional[str] = None,
                         is_script: bool = False,
                         allow_tty_prompt: bool = False,
                         debug: bool = False) -> list:
    """
    Build the command array to launch the daemon.
    
    Args:
        daemon_path: Path to daemon executable or script
        uid: User ID to pass to daemon
        gid: Group ID to pass to daemon
        escalation_tool: Path to privilege escalation tool or None
        is_script: True if daemon_path is a Python script (needs interpreter)
        allow_tty_prompt: If True, allow escalation tools to prompt on TTY (no -n for sudo)
    
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
    
    # Add debug flag if requested
    if debug:
        base_cmd.append('--debug')
    
    if escalation_tool is None:
        # Running as root or no escalation needed
        return base_cmd
    
    tool_name = os.path.basename(escalation_tool)
    
    if tool_name == "pkexec":
        # Linux PolicyKit  # linux-only: pkexec is Linux-specific
        return [escalation_tool] + base_cmd
    
    elif tool_name == "sudo":
        # Fallback sudo - use -n (non-interactive) only if we can't prompt on TTY
        if allow_tty_prompt:
            return [escalation_tool] + base_cmd  # Allow password prompt on TTY
        else:
            return [escalation_tool, '-n'] + base_cmd  # -n = non-interactive (pipe mode)
    
    elif tool_name == "doas":
        # FreeBSD/OpenBSD doas
        return [escalation_tool] + base_cmd
    

    
    else:
        # Unknown tool, try direct execution
        return [escalation_tool] + base_cmd


def launch_daemon(use_socket: bool = False, debug: bool = False) -> Tuple[subprocess.Popen, LineBufferedTransport]:
    """
    Launch privileged daemon with auto-detected path and user context.
    
    Args:
        use_socket: If True, use Unix socket IPC instead of pipes
        debug: If True, pass --debug flag to daemon for verbose logging
    
    Returns:
        Tuple of (subprocess.Popen, LineBufferedTransport)
    
    Raises:
        RuntimeError: If daemon launch fails or privilege escalation not available
        TimeoutError: If daemon doesn't send ready signal
        OSError: If pipe/socket creation fails
    """
    from paths import DAEMON_SCRIPT_PATH, DAEMON_IS_SCRIPT
    
    uid = os.getuid()
    gid = os.getgid()
    
    if not os.path.exists(DAEMON_SCRIPT_PATH):
        raise RuntimeError(f"Daemon path not found: {DAEMON_SCRIPT_PATH}")
    
    return launch_daemon_process(DAEMON_SCRIPT_PATH, uid, gid, DAEMON_IS_SCRIPT, use_socket, debug)


def launch_daemon_process(daemon_path: str, uid: int, gid: int, is_script: bool = False, use_socket: bool = False, debug: bool = False) -> Tuple[subprocess.Popen, LineBufferedTransport]:
    """
    Launch privileged daemon process and establish communication.
    
    Args:
        daemon_path: Path to daemon executable or script
        uid: User ID to pass to daemon (for permission context)
        gid: Group ID to pass to daemon (for permission context)
        is_script: True if daemon_path is a Python script (needs sys.executable)
        use_socket: If True, daemon creates Unix socket and acts as server; client connects
        debug: If True, pass --debug flag to daemon for verbose logging
    
    Returns:
        Tuple of (subprocess.Popen, LineBufferedTransport)
    
    Raises:
        RuntimeError: If privilege escalation tool not found or daemon launch fails
        TimeoutError: If daemon doesn't send ready signal or socket not created in time
        OSError: If pipe/socket connection fails
    """
    if use_socket:
        return _launch_daemon_with_socket_server(daemon_path, uid, gid, is_script, debug)
    else:
        return _launch_daemon_with_pipes(daemon_path, uid, gid, is_script, debug)


def _launch_daemon_with_socket_server(daemon_path: str, uid: int, gid: int, is_script: bool = False, debug: bool = False) -> Tuple[subprocess.Popen, LineBufferedTransport]:
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
        debug: If True, pass --debug flag to daemon for verbose logging
    
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
    
    # Get available escalation tools for fallback
    available_tools = _get_privilege_escalation_tools()
    if not available_tools and os.getuid() != 0:
        raise RuntimeError("No privilege escalation tool found (pkexec, sudo, doas). Cannot launch daemon as root.")
    
    tried_tools = []  # Track failed tools for fallback
    
    # Get socket path from centralized path configuration
    socket_path = get_daemon_socket_path(uid)
    socket_dir = os.path.dirname(socket_path)
    os.makedirs(socket_dir, exist_ok=True)
    
    # Check for stale socket and remove it, or raise if daemon already running
    check_and_remove_stale_socket(socket_path)
    
    # Determine if we can allow TTY prompts (for sudo password, etc.)
    allow_tty = sys.stdin.isatty()

    # Save terminal settings if possible (to restore after sudo potentially messes them up, posix only)
    old_tty_settings = None
    if allow_tty and termios:
        try:
            old_tty_settings = termios.tcgetattr(sys.stdin.fileno())
        except Exception:
            pass
    
    # Try escalation tools with fallback on auth failure
    last_error = None
    process = None
    
    while True:
        escalation_tool = _find_privilege_escalation_tool(exclude=tried_tools)
        
        if escalation_tool is None and os.getuid() != 0 and tried_tools:
            # All tools exhausted after trying at least one
            raise RuntimeError(f"All privilege escalation tools failed. Last error: {last_error}")
        elif escalation_tool is None and os.getuid() != 0:
            raise RuntimeError("No privilege escalation tool found. Cannot launch daemon as root.")
        
        if escalation_tool:
            print(f"IPC: Using privilege escalation: {escalation_tool}")
        else:
            print("IPC: Running as root, no escalation needed.")
        
        # Build daemon command with --listen-socket argument
        cmd = _build_daemon_command(daemon_path, uid, gid, escalation_tool, is_script, allow_tty_prompt=allow_tty, debug=debug)
        cmd.extend(['--listen-socket', socket_path])
        print(f"IPC: Command: {' '.join(cmd)}")
        
        # Launch daemon (it will create and listen on socket)
        try:
            # If the caller runs attached to a TTY (e.g. interactive terminal),
            # keep both stdin and stdout inherited (None) so escalation tools like sudo
            # can prompt for credentials and display messages. Only do this for socket mode:
            # pipe mode relies on pipes and must not inherit these.
            if allow_tty:
                stdin_arg = None  # inherit parent's stdin/tty
                stdout_arg = None # inherit parent's stdout/tty
                print("IPC: Detected caller TTY; inheriting stdin and stdout for daemon (socket mode).")
            else:
                stdin_arg = subprocess.DEVNULL
                stdout_arg = subprocess.DEVNULL

            process = subprocess.Popen(
                cmd,
                stdin=stdin_arg,
                stdout=stdout_arg,
                stderr=subprocess.DEVNULL,
                env=os.environ.copy(),
                # Note: Don't use start_new_session=True here it prevents sudo password prompts
                # Daemon persistence is handled by the daemon ignoring SIGINT
            )
            print(f"IPC: Daemon process started (PID: {process.pid}). Waiting for daemon socket/escalation...")
            if escalation_tool:
                tool_name = os.path.basename(escalation_tool)
                print(f"IPC: Launching via {tool_name}. Please enter your user password if prompted.")
            
            # Try to connect to socket (inside the retry loop)
            client_sock = None
            try:
                # Use IPC_LAUNCH_CONNECT_TIMEOUT: allows extra time for auth (polkit/sudo)
                client_sock = connect_to_unix_socket(socket_path, timeout=constants.IPC_LAUNCH_CONNECT_TIMEOUT, check_process=process)
                print(f"IPC: Connected to daemon socket at {socket_path}")

                # Restore terminal settings if we saved them (posix only)
                if old_tty_settings and termios:
                    try:
                        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_tty_settings)
                    except Exception:
                        pass
                
                # Wrap socket in transport
                transport = SocketTransport(client_sock)
                buffered_transport = LineBufferedTransport(transport)
                
                # Wait for ready signal
                wait_for_ready_signal(buffered_transport, process)
                
                print("IPC: Socket transport created successfully.")
                return process, buffered_transport
                
            except Exception as e:
                # Clean up socket if partially connected
                if client_sock:
                    try:
                        client_sock.close()
                    except Exception:
                        pass
                
                # Terminate daemon if started (works only if we are root in docker)
                if process and process.poll() is None:
                    try:
                        process.terminate()
                        process.wait(timeout=constants.TERMINATE_SHORT_TIMEOUT)
                    except Exception:
                        pass
                
                # Check if this is an auth failure (exit codes 126, 127, or 1)
                exit_code = process.returncode if process else None
                is_auth_failure = exit_code in (1, 126, 127)
                
                if is_auth_failure and escalation_tool:
                    tried_tools.append(escalation_tool)
                    last_error = str(e)
                    tool_name = os.path.basename(escalation_tool)
                    remaining = len(available_tools) - len(tried_tools)
                    if remaining > 0:
                        print(f"IPC: {tool_name} failed (exit {exit_code}), trying next escalation tool ({remaining} remaining)...", file=sys.stderr)
                        # Clean up stale socket before retry
                        try:
                            check_and_remove_stale_socket(socket_path)
                        except Exception:
                            pass
                        continue  # Retry with next tool
                    else:
                        raise RuntimeError(f"All privilege escalation tools failed. Last error: {last_error}")
                
                # Not an auth failure or no more tools to try
                print(f"IPC: Socket connection failed: {e}", file=sys.stderr)
                raise
            
        except Exception as e:
            last_error = str(e)
            if escalation_tool:
                tried_tools.append(escalation_tool)
                print(f"IPC: Escalation tool {os.path.basename(escalation_tool)} failed: {e}, trying next...", file=sys.stderr)
                continue
            raise RuntimeError(f"Failed to launch daemon process: {e}") from e


def _launch_daemon_with_pipes(daemon_path: str, uid: int, gid: int, is_script: bool = False, debug: bool = False) -> Tuple[subprocess.Popen, LineBufferedTransport]:
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
        debug: If True, pass --debug flag to daemon for verbose logging
    
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
    
    # Get available escalation tools for fallback
    available_tools = _get_privilege_escalation_tools()
    if not available_tools and os.getuid() != 0:
        raise RuntimeError(
            "No privilege escalation tool found (pkexec, sudo, doas). "
            "Cannot launch daemon as root."
        )
    
    # Determine if we can allow TTY prompts (for sudo password, etc.)
    try:
        allow_tty = sys.stdin.isatty()
    except Exception:
        allow_tty = False
    
    tried_tools = []  # Track failed tools for fallback
    last_error = None
    
    while True:
        escalation_tool = _find_privilege_escalation_tool(exclude=tried_tools)
        
        if escalation_tool is None and os.getuid() != 0 and tried_tools:
            # All tools exhausted after trying at least one
            raise RuntimeError(f"All privilege escalation tools failed. Last error: {last_error}")
        elif escalation_tool is None and os.getuid() != 0:
            raise RuntimeError("No privilege escalation tool found. Cannot launch daemon as root.")
        
        if escalation_tool:
            print(f"IPC: Using privilege escalation: {escalation_tool}")
        else:
            print("IPC: Running as root, no escalation needed.")
        
        # Build command
        cmd = _build_daemon_command(daemon_path, uid, gid, escalation_tool, is_script, allow_tty_prompt=allow_tty, debug=debug)
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
        transport = None
        buffered_transport = None
        try:
            process = subprocess.Popen( #sudo ignores this stdin/stdout/stderr and works fine!
                cmd,
                stdin=pipe_to_daemon_r,     # Daemon reads from this
                stdout=pipe_from_daemon_w,  # Daemon writes to this
                stderr=sys.stderr,          # Inherit stderr to see escalation errors
                #stderr=subprocess.DEVNULL,  # Suppress stderr (daemon logs elsewhere)
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
            # Mark these as owned by transport now (don't double-close)
            pipe_to_daemon_w = -1
            pipe_from_daemon_r = -1
            
            buffered_transport = LineBufferedTransport(transport)
            
            # Wait for ready signal through the transport
            wait_for_ready_signal(buffered_transport, process)
            
            print("IPC: Transport created successfully.")
            return process, buffered_transport
            
        except Exception as e:
            print(f"IPC: Error during daemon launch: {e}", file=sys.stderr)
            
            # Close transport first if it was created (it owns the FDs)
            if buffered_transport:
                try:
                    buffered_transport.close()
                except Exception:
                    pass
            elif transport:
                try:
                    transport.close()
                except Exception:
                    pass
            else:
                # Transport not created, close pipes manually
                for fd in [pipe_to_daemon_r, pipe_to_daemon_w, 
                           pipe_from_daemon_r, pipe_from_daemon_w]:
                    if fd != -1:
                        try: os.close(fd)
                        except Exception: pass
            
            # Terminate daemon if started (works only if we are root in docker)
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=constants.TERMINATE_SHORT_TIMEOUT)
                except Exception:
                    pass
            
            # Check if this is an auth failure (exit codes 126, 127, or 1 for pkexec/sudo)
            exit_code = process.returncode if process else None
            is_auth_failure = exit_code in (1, 126, 127)
            
            if is_auth_failure and escalation_tool:
                tried_tools.append(escalation_tool)
                last_error = str(e)
                tool_name = os.path.basename(escalation_tool)
                remaining = len(available_tools) - len(tried_tools)
                if remaining > 0:
                    print(f"IPC: {tool_name} failed (exit {exit_code}), trying next escalation tool ({remaining} remaining)...", file=sys.stderr)
                    continue
                else:
                    raise RuntimeError(f"All privilege escalation tools failed. Last error: {last_error}")
            
            # Re-raise appropriate exception
            if isinstance(e, (RuntimeError, TimeoutError, OSError)):
                raise
            else:
                raise RuntimeError(f"Daemon launch failed: {e}") from e
