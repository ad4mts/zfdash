# --- START OF FILE constants.py ---

"""
Central location for constants used across the ZFS manager modules.
"""

# --- ZFS/ZPOOL Property Lists ---
# Used for 'zpool list -o ...'
ZPOOL_PROPS = [
    'name', 'size', 'alloc', 'free', 'frag', 'cap', 'dedup', 'health', 'guid',
    'altroot', 'bootfs', 'cachefile', 'comment', 'failmode', 'listsnapshots',
    'version', 'readonly', 'feature@encryption'
]

# Used for 'zfs list -t filesystem,volume -o ...'
ZFS_DATASET_PROPS = [
    'name', 'type', 'used', 'available', 'referenced', 'mountpoint', 'quota', 'reservation',
    'recordsize', 'compression', 'atime', 'relatime', 'readonly', 'volsize',
    'volblocksize', 'dedup', 'encryption', 'keystatus', 'keyformat', 'keylocation', 'pbkdf2iters',
    'mounted', 'origin', 'creation', 'logicalused', 'logicalreferenced'
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
DEFAULT_DAEMON_COMMAND_TIMEOUT = 120 # Default timeout for daemon commands in seconds

# --- END OF FILE constants.py ---