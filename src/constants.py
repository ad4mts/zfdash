# --- START OF FILE constants.py ---

"""
Central location for constants used across the ZFS manager modules.
"""

# --- ZFS/ZPOOL Property Lists ---
# Used for 'zpool list -o ...'
ZPOOL_PROPS = [
    'name', 'size', 'alloc', 'free', 'frag', 'cap', 'dedup', 'health', 'guid',
    'altroot', 'bootfs', 'cachefile', 'comment', 'failmode', 'listsnapshots',
    'version', 'readonly', 'feature@encryption', 'autotrim', 'autoexpand', 'autoreplace'
]

# Used for 'zfs list -t filesystem,volume -o ...'
ZFS_DATASET_PROPS = [
    'name', 'type', 'used', 'available', 'referenced', 'mountpoint', 'quota', 'reservation',
    'recordsize', 'compression', 'compressratio', 'atime', 'relatime', 'readonly', 'volsize',
    'volblocksize', 'dedup', 'encryption', 'keystatus', 'keyformat', 'keylocation', 'pbkdf2iters',
    'mounted', 'origin', 'creation', 'logicalused', 'logicalreferenced', 'sync'
]

# Used for 'zfs list -t snapshot -o ...'
ZFS_SNAPSHOT_PROPS = [
    'name', 'used', 'referenced', 'creation', 'defer_destroy', 'userrefs',
    'logicalused', 'logicalreferenced'
]

# Custom Properties for UI Editing
AUTO_SNAPSHOT_PROPS = [
    "com.sun:auto-snapshot",
    "com.sun:auto-snapshot:daily",
    "com.sun:auto-snapshot:frequent",
    "com.sun:auto-snapshot:hourly",
    "com.sun:auto-snapshot:monthly",
    "com.sun:auto-snapshot:weekly",
    "com.sun:auto-snapshot:yearly",
]

# Desired sort order for auto-snapshot properties in UI
AUTO_SNAPSHOT_SORT_ORDER = [
    "com.sun:auto-snapshot", # Master switch first
    "com.sun:auto-snapshot:frequent",
    "com.sun:auto-snapshot:hourly",
    "com.sun:auto-snapshot:daily",
    "com.sun:auto-snapshot:weekly",
    "com.sun:auto-snapshot:monthly",
    "com.sun:auto-snapshot:yearly",
]

# --- Default Settings ---
# These are fallback values used when config file doesn't have the setting or value is invalid

DEFAULT_DAEMON_COMMAND_TIMEOUT = 120  # Default timeout for daemon commands in seconds
DEFAULT_LOGGING_ENABLED = False       # Default state for logging feature (disabled by default)

# --- Timeout related constants ---
# Timeouts used across client<->daemon IPC and internal thread/process management
# NOTE: Keep values in sync with current behavior to avoid changing runtime characteristics
# --- IPC Timeouts
IPC_READY_TIMEOUT = 60             # Default timeout for waiting daemon 'ready' signal (seconds)
IPC_CONNECT_TIMEOUT = 10.0         # Default timeout for connecting to daemon socket (seconds)
IPC_LAUNCH_CONNECT_TIMEOUT = IPC_READY_TIMEOUT  # Timeout when connecting to a socket created by a freshly-launched daemon (allows authentication/polkit time)
# --- Client Timeouts
CLIENT_REQUEST_TIMEOUT = 60.0      # Default timeout for a standard client request/response roundtrip (seconds)
CLIENT_ACTION_TIMEOUT = 120.0      # Default timeout for long-running client actions/requests (seconds)
LIST_IMPORTABLE_POOLS_TIMEOUT = CLIENT_ACTION_TIMEOUT  # Timeout when searching for importable pools
SHUTDOWN_REQUEST_TIMEOUT = 5.0     # Timeout for shutdown request to daemon (seconds)
# --- Thread/Process/Poll Timeouts..etc
THREAD_JOIN_TIMEOUT = 2.0          # Timeout for joining threads during shutdown (seconds)
TERMINATE_TIMEOUT = 5.0 # Timeout to wait for process to terminate after SIGTERM (seconds)
TERMINATE_SHORT_TIMEOUT = 1.0  # Short grace time after terminate() for cleanup
KILL_TIMEOUT = 2.0    # Timeout to wait for process to terminate after SIGKILL (seconds)
POLL_INTERVAL = 0.1                # Generic short poll interval used for retry loops (seconds)
READER_SELECT_TIMEOUT = 0.2        # Timeout used in select() in reader thread loop in client to check read responses from daemon (seconds)
READY_SELECT_TIMEOUT = 0.1         # Timeout used in select() in wait_for_ready_signal


# --- TCP Agent Constants ---
DEFAULT_AGENT_PORT = 5555      # Default TCP port for agent mode
AUTH_TIMEOUT_SECONDS = 30      # Timeout for authentication handshake (seconds)
NONCE_BYTES = 32               # Size of random nonce for challenge (bytes)

# --- TLS Negotiation Protocol ---
TCP_PROTOCOL_VERSION = 2       # Protocol version (2 = hello handshake)
HELLO_TIMEOUT_SECONDS = 5      # Timeout for hello handshake (seconds)

# TLS Error Codes (for structured error handling)
TLS_ERROR_REQUIRED = "TLS_REQUIRED"              # Server requires TLS, client didn't request
TLS_ERROR_UNAVAILABLE = "TLS_UNAVAILABLE"        # Client wants TLS, server doesn't have it
TLS_ERROR_PROTOCOL_MISMATCH = "PROTOCOL_MISMATCH"  # Protocol version mismatch

# --- Network Discovery ---
DISCOVERY_PORT = 5554                  # UDP port for broadcast discovery
DISCOVERY_MAGIC = "ZFDASH_DISCOVER"    # Discovery request identifier
MDNS_SERVICE_TYPE = "_zfdash._tcp.local."  # mDNS service type
DISCOVERY_TIMEOUT = 3.0                # Discovery scan timeout (seconds)

# --- END OF FILE constants.py ---