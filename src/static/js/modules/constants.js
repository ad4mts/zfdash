/**
 * constants.js - Application Constants and Configuration
 * 
 * Contains all global constants, configuration objects, and static definitions
 * used throughout the ZfDash application.
 */

// --- Storage Keys ---
export const EXPANDED_NODES_KEY = 'zfdash_expanded_nodes_v1';
export const SELECTED_SELECTION_KEY = 'zfdash_selected_item_v1';

// --- Define which properties use zpool set/inherit (pool-level only) ---
export const POOL_LEVEL_PROPERTIES = new Set([
    'comment', 'cachefile', 'bootfs', 'failmode', 'autoreplace', 'autotrim',
    'delegation', 'autoexpand', 'listsnapshots', 'readonly', 'multihost', 
    'compatibility'
]);

// --- Auto Snapshot Properties ---
export const AUTO_SNAPSHOT_PROPS = [
    "com.sun:auto-snapshot",
    "com.sun:auto-snapshot:daily",
    "com.sun:auto-snapshot:frequent",
    "com.sun:auto-snapshot:hourly",
    "com.sun:auto-snapshot:monthly",
    "com.sun:auto-snapshot:weekly",
    "com.sun:auto-snapshot:yearly",
];

// --- Auto Snapshot Sort Order for WebUI ---
export const AUTO_SNAPSHOT_SORT_ORDER_WEB = [
    "com.sun:auto-snapshot", // Master switch first
    "com.sun:auto-snapshot:frequent",
    "com.sun:auto-snapshot:hourly",
    "com.sun:auto-snapshot:daily",
    "com.sun:auto-snapshot:weekly",
    "com.sun:auto-snapshot:monthly",
    "com.sun:auto-snapshot:yearly",
];

// --- Editable Properties Configuration ---
// Define editable properties for the web UI (similar to PySide6 version)
export const EDITABLE_PROPERTIES_WEB = {
    'mountpoint': { internalName: 'mountpoint', displayName: 'Mount Point', editor: 'lineedit' },
    'quota': { internalName: 'quota', displayName: 'Quota', editor: 'lineedit', placeholder: 'e.g., 100G, none', validation: 'sizeOrNone' },
    'reservation': { internalName: 'reservation', displayName: 'Reservation', editor: 'lineedit', placeholder: 'e.g., 5G, none', validation: 'sizeOrNone' },
    'recordsize': { internalName: 'recordsize', displayName: 'Record Size', editor: 'combobox', options: ['inherit', '512', ...Array.from({length: 11-7+1}, (_, i) => `${2**(i+7)}K`), '1M'] },
    'compression': { internalName: 'compression', displayName: 'Compression', editor: 'combobox', options: ['inherit', 'off', 'on', 'lz4', 'gzip', 'gzip-1', 'gzip-9', 'zle', 'lzjb', 'zstd', 'zstd-fast'] },
    'atime': { internalName: 'atime', displayName: 'Access Time (atime)', editor: 'combobox', options: ['inherit', 'on', 'off'] },
    'relatime': { internalName: 'relatime', displayName: 'Relative Access Time', editor: 'combobox', options: ['inherit', 'on', 'off'] },
    'readonly': { internalName: 'readonly', displayName: 'Read Only', editor: 'combobox', options: ['inherit', 'on', 'off'] },
    'dedup': { internalName: 'dedup', displayName: 'Deduplication', editor: 'combobox', options: ['inherit', 'on', 'off', 'verify', 'sha256', 'sha512', 'skein', 'edonr'], readOnlyFunc: (obj) => obj?.obj_type === 'snapshot' },
    'sharenfs': { internalName: 'sharenfs', displayName: 'NFS Share', editor: 'combobox', options: ['inherit', 'off', 'on'], readOnlyFunc: (obj) => obj?.obj_type === 'snapshot' },
    'sharesmb': { internalName: 'sharesmb', displayName: 'SMB Share', editor: 'combobox', options: ['inherit', 'off', 'on'], readOnlyFunc: (obj) => obj?.obj_type === 'snapshot' },
    'logbias': { internalName: 'logbias', displayName: 'Log Bias', editor: 'combobox', options: ['inherit', 'latency', 'throughput'], readOnlyFunc: (obj) => obj?.obj_type === 'snapshot' },
    'sync': { internalName: 'sync', displayName: 'Sync Policy', editor: 'combobox', options: ['inherit', 'standard', 'always', 'disabled'], readOnlyFunc: (obj) => obj?.obj_type === 'snapshot' },
    'volblocksize': { internalName: 'volblocksize', displayName: 'Volume Block Size', editor: 'combobox', options: ['inherit'].concat(Array.from({length: 17-9+1}, (_, i) => `${2**(i+9)}K`)).concat(['1M']), readOnlyFunc: (obj) => !(obj?.obj_type === 'volume') },
    'comment': { internalName: 'comment', displayName: 'Pool Comment', editor: 'lineedit', readOnlyFunc: (obj) => obj?.obj_type !== 'pool' },
    'cachefile': { internalName: 'cachefile', displayName: 'Cache File', editor: 'lineedit', readOnlyFunc: (obj) => obj?.obj_type !== 'pool' },
    'bootfs': { internalName: 'bootfs', displayName: 'Boot FS', editor: 'lineedit', readOnlyFunc: (obj) => obj?.obj_type !== 'pool' },
    'failmode': { internalName: 'failmode', displayName: 'Fail Mode', editor: 'combobox', options: ['wait', 'continue', 'panic'], readOnlyFunc: (obj) => obj?.obj_type !== 'pool' },
    'autotrim': { internalName: 'autotrim', displayName: 'Auto Trim', editor: 'combobox', options: ['on', 'off'], readOnlyFunc: (obj) => obj?.obj_type !== 'pool' },
    'autoreplace': { internalName: 'autoreplace', displayName: 'Auto Replace', editor: 'combobox', options: ['on', 'off'], readOnlyFunc: (obj) => obj?.obj_type !== 'pool' },
};

// --- Initialize Auto Snapshot Properties in Editable Properties ---
export function initializeAutoSnapshotProperties() {
    AUTO_SNAPSHOT_PROPS.forEach(prop => {
        const suffix = prop.includes(':') ? prop.split(':').pop() : 'Default';
        const is_master_switch = (prop === "com.sun:auto-snapshot");
        const displayName = is_master_switch ? "Auto Snapshot (Master Switch)" : `Auto Snapshot (${suffix.charAt(0).toUpperCase() + suffix.slice(1)})`;
        EDITABLE_PROPERTIES_WEB[prop] = {
            internalName: prop,
            displayName: displayName,
            editor: 'combobox',
            options: ['true', 'false', '-'],
            readOnlyFunc: (obj) => !(obj?.obj_type === 'dataset' || obj?.obj_type === 'volume')
        };
    });
}

// --- VDEV Group Patterns for Pool Edit Parsing ---
export const VDEV_GROUP_PATTERNS = {
    'mirror': /^mirror-\d+/,
    'raidz1': /^raidz1-\d+/,
    'raidz2': /^raidz2-\d+/,
    'raidz3': /^raidz3-\d+/,
    'draid': /^draid\d*:/,
    'log': /^logs$/,
    'cache': /^cache$/,
    'spare': /^spares$/,
    'special': /^special$/
};

// --- Device Path Pattern ---
export const DEVICE_PATTERN_RE = /^(\/dev\/\S+|ata-|wwn-|scsi-|nvme-|usb-|dm-|zd\d+|[a-z]+[0-9]+|gpt\/.*|disk\/by-.*)/i;

// --- Reserved Pool Names ---
export const RESERVED_POOL_NAMES = ['log', 'spare', 'cache', 'mirror', 'raidz', 'raidz1', 'raidz2', 'raidz3', 'replacing', 'initializing'];

// --- VDEV Types for Pool Creation ---
export const VDEV_TYPES = ['disk', 'mirror', 'raidz1', 'raidz2', 'raidz3', 'log', 'cache', 'spare'];

// --- Minimum Devices per VDEV Type ---
export const MIN_DEVICES_PER_VDEV = {
    'mirror': 2,
    'raidz1': 3,
    'raidz2': 4,
    'raidz3': 5
};
