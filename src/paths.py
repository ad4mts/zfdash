# Path configuration module for ZfDash
# This module centralizes all path logic for the application
#
# Use `get_user_runtime_dir(uid)` to resolve per-UID runtime directories in a
# consistent manner across the project.
#
# NOTE on XDG_RUNTIME_DIR and the socket path mismatch problem:
# ---------------------------------------------------------------
# We intentionally DO NOT use XDG_RUNTIME_DIR for socket/runtime path resolution.
# 
# The problem: XDG_RUNTIME_DIR is a per-user, per-session environment variable.
# - Daemon runs as root (uid=0) → sees XDG_RUNTIME_DIR=/run/user/0 (or unset)
# - WebUI runs as regular user → sees XDG_RUNTIME_DIR=/run/user/1000
# - Result: daemon listens on one path, client tries to connect to another → mismatch!

import sys
import os
import platform
import shutil
import tempfile
from pathlib import Path

# Deployment detection
IS_FROZEN = getattr(sys, 'frozen', False)
IS_DOCKER = os.path.exists('/.dockerenv')  # linux-only: /.dockerenv is Linux container detection

# Base directory for application resources (templates, static, icons, policies)
if IS_FROZEN:
    # Frozen/Installed: executable is at /opt/zfdash/zfdash
    RESOURCES_BASE_DIR = Path(sys.executable).parent
else:
    # Source/Docker: running from .../zfdash/src/
    RESOURCES_BASE_DIR = Path(__file__).parent.resolve()

# Directory for persistent data (credentials, flask keys)
# Always absolute, created by daemon or install.sh
PERSISTENT_DATA_DIR = Path("/opt/zfdash/data")  # linux-only: /opt path is Linux-specific

# Application resource paths (relative to RESOURCES_BASE_DIR)
TEMPLATES_DIR = str(RESOURCES_BASE_DIR / "templates")
STATIC_DIR = str(RESOURCES_BASE_DIR / "static")
ICON_PATH = str(RESOURCES_BASE_DIR / "data" / "icons" / "zfs-gui.png")
POLICY_PATH = str(RESOURCES_BASE_DIR / "data" / "policies" / "org.zfsgui.pkexec.daemon.launch.policy")  # linux-only: pkexec/PolicyKit is Linux-specific

# Persistent data paths (absolute, always at /opt/zfdash/data)
CREDENTIALS_FILE_PATH = str(PERSISTENT_DATA_DIR / "credentials.json")
FLASK_KEY_PERSISTENT_PATH = str(PERSISTENT_DATA_DIR / "flask_secret_key.txt")

# User configuration paths (per-user, in home directory)
USER_CONFIG_DIR = Path.home() / ".config" / "ZfDash"
USER_CONFIG_FILE_PATH = str(USER_CONFIG_DIR / "config.json")

# Daemon script path with fallbacks
if IS_FROZEN:
    daemon_candidate = RESOURCES_BASE_DIR / 'zfdash'
    if not daemon_candidate.exists():
        daemon_candidate = Path(sys.executable)
    DAEMON_SCRIPT_PATH = str(daemon_candidate)
    DAEMON_IS_SCRIPT = False
else:
    daemon_candidate = RESOURCES_BASE_DIR / 'main.py'
    if not daemon_candidate.exists():
        daemon_candidate = Path(__file__).parent / 'main.py'
    DAEMON_SCRIPT_PATH = str(daemon_candidate)
    DAEMON_IS_SCRIPT = True

# Log file paths
# Default filename for daemon stderr logs (system debug). Use get_daemon_log_file_path
# to compute an absolute path if needed (per-user or system-level).
DAEMON_STDERR_FILENAME = "zfs_daemon_stderr.log"
LOG_FILE_NAME = "zfdash-daemon.log"  # Log file specific to the daemon for a user session
RUNTIME_FALLBACK_DIR = "/tmp"  # Fallback base for runtime_dir resolution when no /run/user/<uid> exists
RUNTIME_PER_USER_PREFIX = "zfdash-runtime-"  # subdirectory name prefix used for per-UID fallback dirs under RUNTIME_FALLBACK_DIR


def get_daemon_log_file_path(uid: int, log_name: str | None = None) -> str:
    """Gets the path for the daemon's log file within the user's runtime directory."""
    runtime_dir = get_user_runtime_dir(uid)
    if log_name is None:
        log_name = LOG_FILE_NAME
    log_path = os.path.join(runtime_dir, log_name)
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
    Args:
        uid: The user ID for which to get the socket path
        
    Returns:
        str: Absolute path
    """
    # Delegate all path resolution, including handling of invalid UIDs
    runtime_dir = get_user_runtime_dir(uid)
    socket_path = os.path.join(runtime_dir, "zfdash.sock")
    return socket_path


def get_user_runtime_dir(uid: int) -> str:
    """Return a canonical runtime directory path for a given user id.

    This function uses DETERMINISTIC, platform-specific paths that do NOT depend
    on environment variables like XDG_RUNTIME_DIR. This ensures both daemon (root)
    and client (user) resolve to the same path for a given UID.

    Resolution order by platform:
    - Linux: /run/user/{uid} → /var/run/user/{uid} → /tmp/zfdash-runtime-{uid}
    - FreeBSD: /var/run/user/{uid} → /tmp/zfdash-runtime-{uid}
    - Windows: {tempdir}/zfdash-runtime-{uid} (using tempfile.gettempdir())
    - macOS/Other: /tmp/zfdash-runtime-{uid} → {tempdir}/zfdash-runtime-{uid}

    Args:
        uid: The UID for which to resolve the runtime dir

    Returns:
        str: Absolute path to a suitable runtime directory
    """
    if uid < 0:
        return RUNTIME_FALLBACK_DIR

    system = platform.system()
    per_user_subdir = f"{RUNTIME_PER_USER_PREFIX}{uid}"

    if system == 'Linux':
        # Linux: prefer systemd-style /run/user/{uid}, then /var/run/user/{uid}
        candidates = [
            f"/run/user/{uid}",
            f"/var/run/user/{uid}",  # Some older/non-systemd systems
        ]
        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate
        # Fallback: create per-user dir under /tmp
        return _create_fallback_runtime_dir(RUNTIME_FALLBACK_DIR, per_user_subdir, uid)

    elif 'BSD' in system:  # FreeBSD, OpenBSD, NetBSD, etc.
        # BSD: /var/run/user/{uid} is common on FreeBSD with pam_runtime_dir
        candidates = [
            f"/var/run/user/{uid}",
        ]
        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate
        # Fallback: create per-user dir under /tmp
        return _create_fallback_runtime_dir(RUNTIME_FALLBACK_DIR, per_user_subdir, uid)

    elif system == 'Windows':
        # Windows (educational only; no stable openzfs support yet in windows): Use the system temp directory (typically C:\Users\<user>\AppData\Local\Temp)
        temp_base = tempfile.gettempdir()
        return _create_fallback_runtime_dir(temp_base, per_user_subdir, uid)

    elif system == 'Darwin':  # macOS
        # macOS: TMPDIR is per-user (e.g., /var/folders/xx/xxxxx/T/) so it has the
        # same mismatch problem as XDG_RUNTIME_DIR - daemon and client would get
        # different paths. Instead, use /tmp (symlink to /private/tmp) which is
        # shared and accessible by all users, with a per-UID subdirectory.
        if os.path.isdir('/tmp'):
            return _create_fallback_runtime_dir('/tmp', per_user_subdir, uid)
        # Ultimate fallback - but this may cause mismatch issues
        temp_base = tempfile.gettempdir()
        return _create_fallback_runtime_dir(temp_base, per_user_subdir, uid)

    else:
        # Unknown platform: try /tmp first, then tempfile.gettempdir()
        if os.path.isdir('/tmp'):
            return _create_fallback_runtime_dir('/tmp', per_user_subdir, uid)
        temp_base = tempfile.gettempdir()
        return _create_fallback_runtime_dir(temp_base, per_user_subdir, uid)


def _create_fallback_runtime_dir(base_dir: str, subdir_name: str, uid: int) -> str:
    """Create a per-user fallback runtime directory with proper permissions.

    Args:
        base_dir: Base directory (e.g., /tmp)
        subdir_name: Subdirectory name (e.g., zfdash-runtime-1000)
        uid: Target user ID for ownership

    Returns:
        str: Path to the created directory, or base_dir on failure
    """
    per_user_dir = os.path.join(base_dir, subdir_name)
    try:
        os.makedirs(per_user_dir, mode=0o700, exist_ok=True)
        # If running as root, try to chown the directory to the target UID (best effort)
        # This ensures the user can access their runtime dir even if root created it (webui/gui can access logs/socket)
        if platform.system() != 'Windows' and os.geteuid() == 0:
            try:
                os.chown(per_user_dir, uid, uid)
            except (PermissionError, OSError):
                # If we can't chown, leave as-is. Best-effort only.
                pass
        return per_user_dir
    except Exception:
        # If creation fails, return base_dir as last resort
        return base_dir


# Export list for module
__all__ = [
    'IS_FROZEN', 'IS_DOCKER',
    'RESOURCES_BASE_DIR', 'PERSISTENT_DATA_DIR',
    'TEMPLATES_DIR', 'STATIC_DIR',
    'ICON_PATH', 'POLICY_PATH',
    'CREDENTIALS_FILE_PATH', 'FLASK_KEY_PERSISTENT_PATH',
    'USER_CONFIG_DIR', 'USER_CONFIG_FILE_PATH',
    'DAEMON_SCRIPT_PATH', 'DAEMON_IS_SCRIPT', 'DAEMON_STDERR_FILENAME',
    'RUNTIME_FALLBACK_DIR',
    'get_daemon_log_file_path', 'get_viewer_log_file_path', 'get_daemon_socket_path',
    'get_user_runtime_dir', '_create_fallback_runtime_dir', 'find_executable'
]


def find_executable(name: str, additional_paths: list[str] | None = None) -> str | None:
    """Find an executable by name.

    First tries shutil.which which searches PATH, then falls back to searching
    common platform-specific directories plus any additional_paths provided.

    Args:
        name: Executable base name to find
        additional_paths: Optional list of paths to search after PATH

    Returns:
        Absolute path if found, otherwise None
    """
    # 1) Check PATH via shutil.which
    try:
        path = shutil.which(name)
        if path:
            return path
    except Exception:
        # If any error occurs, continue to directory search
        pass

    # 2) Platform-specific common locations
    system = platform.system()
    if system == 'Linux':
        base_paths = ['/usr/sbin', '/sbin', '/usr/bin', '/bin', '/usr/local/sbin', '/usr/local/bin']
    elif system == 'Darwin':
        base_paths = ['/usr/local/bin', '/usr/local/sbin', '/opt/homebrew/bin', '/opt/homebrew/sbin', '/usr/bin', '/bin', '/sbin']
    elif 'BSD' in system:
        base_paths = ['/sbin', '/usr/sbin', '/usr/local/sbin', '/usr/local/bin', '/usr/bin', '/bin']
    else:
        base_paths = ['/usr/local/bin', '/usr/local/sbin', '/usr/bin', '/bin', '/sbin', '/usr/sbin']

    if additional_paths:
        base_paths = additional_paths + base_paths

    for p in base_paths:
        candidate = os.path.join(p, name)
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate #The first match is returned so earlier entries override later ones
    return None
