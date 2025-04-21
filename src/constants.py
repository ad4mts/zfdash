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

# --- Default Settings ---
DEFAULT_DAEMON_COMMAND_TIMEOUT = 120 # Default timeout in seconds for ZFS/ZPOOL commands

# --- END OF FILE constants.py ---