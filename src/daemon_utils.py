# --- START OF FILE src/daemon_utils.py ---
# Utility functions for daemon interaction, callable without GUI dependencies.
import os
import sys

from paths import IS_FROZEN, DAEMON_SCRIPT_PATH
from ipc_client import launch_daemon_process, LineBufferedTransport


# --- Helper Functions ---

def get_user_ids():
    """Gets the current real user ID and group ID."""
    uid = os.getuid()
    gid = os.getgid()
    return uid, gid


def launch_daemon(use_socket=False):
    """
    Launch the ZFS daemon with privilege escalation and establish communication.
    
    This is a thin wrapper around ipc.launch_daemon_process() that:
    - Determines the correct daemon path (frozen exe vs script)
    - Gets the user context (UID/GID)
    - Delegates to ipc module for platform-specific launching
    
    Args:
        use_socket: If True, use Unix socket IPC instead of pipes (experimental)
    
    Returns:
        tuple: (subprocess.Popen, LineBufferedTransport)
               - Popen: The daemon process handle
               - LineBufferedTransport: IPC transport for JSON-line protocol
    
    Raises:
        RuntimeError: If daemon launch fails or privilege escalation not available
        TimeoutError: If daemon doesn't send ready signal
        OSError: If pipe/socket creation fails
    """
    print(f"DAEMON_UTILS: Launching ZFS daemon (socket mode: {use_socket})...")
    
    # Get user context
    try:
        user_uid, user_gid = get_user_ids()
        print(f"DAEMON_UTILS: User context - UID={user_uid}, GID={user_gid}")
    except Exception as e:
        print(f"ERROR: Could not determine user/group ID: {e}", file=sys.stderr)
        raise RuntimeError("User ID error") from e
    
    # Determine daemon path (frozen executable vs Python script)
    if IS_FROZEN:
        # Running as PyInstaller bundle - use sys.executable (the bundle itself)
        daemon_path = sys.executable
        is_script = False
        print(f"DAEMON_UTILS: Using frozen executable: {daemon_path}")
        
        if not os.path.exists(daemon_path):
            raise RuntimeError(f"Frozen executable not found: {daemon_path}")
    else:
        # Running as Python script
        daemon_path = DAEMON_SCRIPT_PATH
        is_script = True
        print(f"DAEMON_UTILS: Using Python script: {daemon_path}")
        
        if not os.path.exists(daemon_path):
            raise RuntimeError(f"Daemon script not found: {daemon_path}")
    
    # Delegate to ipc module for platform-specific launch logic
    try:
        process, transport = launch_daemon_process(daemon_path, user_uid, user_gid, is_script, use_socket=use_socket)
        print(f"DAEMON_UTILS: Daemon launched successfully (PID: {process.pid})")
        return process, transport
    except Exception as e:
        print(f"DAEMON_UTILS: Daemon launch failed: {e}", file=sys.stderr)
        raise

# --- END OF FILE src/daemon_utils.py ---
