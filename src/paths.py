# Path configuration module for ZfDash
# This module centralizes all path logic for the application

import sys
import os
from pathlib import Path

# Deployment detection
IS_FROZEN = getattr(sys, 'frozen', False)
IS_DOCKER = os.path.exists('/.dockerenv')

# Base directory for application resources (templates, static, icons, policies)
if IS_FROZEN:
    # Frozen/Installed: executable is at /opt/zfdash/zfdash
    RESOURCES_BASE_DIR = Path(sys.executable).parent
else:
    # Source/Docker: running from .../zfdash/src/
    RESOURCES_BASE_DIR = Path(__file__).parent.resolve()

# Directory for persistent data (credentials, flask keys)
# Always absolute, created by daemon or install.sh
PERSISTENT_DATA_DIR = Path("/opt/zfdash/data")

# Application resource paths (relative to RESOURCES_BASE_DIR)
TEMPLATES_DIR = str(RESOURCES_BASE_DIR / "templates")
STATIC_DIR = str(RESOURCES_BASE_DIR / "static")
ICON_PATH = str(RESOURCES_BASE_DIR / "data" / "icons" / "zfs-gui.png")
POLICY_PATH = str(RESOURCES_BASE_DIR / "data" / "policies" / "org.zfsgui.pkexec.daemon.launch.policy")

# Persistent data paths (absolute, always at /opt/zfdash/data)
CREDENTIALS_FILE_PATH = str(PERSISTENT_DATA_DIR / "credentials.json")
FLASK_KEY_PERSISTENT_PATH = str(PERSISTENT_DATA_DIR / "flask_secret_key.txt")

# User configuration paths (per-user, in home directory)
USER_CONFIG_DIR = Path.home() / ".config" / "ZfDash"
USER_CONFIG_FILE_PATH = str(USER_CONFIG_DIR / "config.json")

# Daemon script path (changes based on deployment mode)
if IS_FROZEN:
    DAEMON_SCRIPT_PATH = str(RESOURCES_BASE_DIR / 'zfdash')  # The executable itself
else:
    DAEMON_SCRIPT_PATH = str(RESOURCES_BASE_DIR / 'main.py')  # The Python script

# Log file paths
DAEMON_STDERR_LOG = "/tmp/zfs_daemon_stderr.log"
LOG_FILE_NAME = "zfdash-daemon.log"  # Log file specific to the daemon for a user session


def get_daemon_log_file_path(uid: int) -> str:
    """Gets the path for the daemon's log file within the user's runtime directory."""
    if uid < 0:
         # Fallback if UID is invalid somehow
         print("CONFIG: Warning: Invalid UID passed to get_daemon_log_file_path. Using /tmp.", file=sys.stderr)
         return f"/tmp/{LOG_FILE_NAME}.{uid}"

    runtime_dir = f"/run/user/{uid}"
    log_path = os.path.join(runtime_dir, LOG_FILE_NAME)

    # Check if runtime dir exists - daemon should create socket there first
    if not os.path.isdir(runtime_dir):
         print(f"CONFIG: Warning: Runtime directory {runtime_dir} not found for UID {uid}. Using /tmp for logs.", file=sys.stderr)
         log_path = f"/tmp/{LOG_FILE_NAME}.{uid}"
         # Attempt to create /tmp log file with user ownership? Daemon runs as root...
         # Daemon should handle log file creation and permissions within _run_command's finally block.
    # No need to os.makedirs here, daemon will handle file opening/creation.
    return log_path


def get_viewer_log_file_path() -> str:
    """Gets the path for the log file from the viewer's perspective (needs user's UID)."""
    try:
        uid = os.getuid()
        return get_daemon_log_file_path(uid)
    except Exception as e:
        print(f"CONFIG: Error getting current user UID for log path: {e}. Falling back to /tmp.", file=sys.stderr)
        return f"/tmp/{LOG_FILE_NAME}.unknownUID"


def get_daemon_socket_path(uid: int) -> str:
    """
    Gets the path for the daemon's Unix socket for IPC.
    
    Returns the socket path in the user's runtime directory.
    On Linux this is typically /run/user/{uid}/zfdash.sock.
    
    Args:
        uid: The user ID for which to get the socket path
        
    Returns:
        str: Absolute path to the daemon socket file
    """
    if uid < 0:
        print("CONFIG: Warning: Invalid UID passed to get_daemon_socket_path. Using /tmp.", file=sys.stderr)
        return f"/tmp/zfdash.sock.{uid}"
    
    # Use XDG_RUNTIME_DIR if available, otherwise /run/user/{uid}
    runtime_dir = os.environ.get('XDG_RUNTIME_DIR')
    if not runtime_dir or not os.path.isdir(runtime_dir):
        runtime_dir = f"/run/user/{uid}"
    
    socket_path = os.path.join(runtime_dir, "zfdash.sock")
    return socket_path


# Export list for module
__all__ = [
    'IS_FROZEN', 'IS_DOCKER',
    'RESOURCES_BASE_DIR', 'PERSISTENT_DATA_DIR',
    'TEMPLATES_DIR', 'STATIC_DIR',
    'ICON_PATH', 'POLICY_PATH',
    'CREDENTIALS_FILE_PATH', 'FLASK_KEY_PERSISTENT_PATH',
    'USER_CONFIG_DIR', 'USER_CONFIG_FILE_PATH',
    'DAEMON_SCRIPT_PATH', 'DAEMON_STDERR_LOG',
    'get_daemon_log_file_path', 'get_viewer_log_file_path', 'get_daemon_socket_path'
]
