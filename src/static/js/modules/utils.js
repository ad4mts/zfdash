/**
 * utils.js - Utility Functions
 * 
 * Common utility functions used throughout the application.
 */

import * as state from './state.js';

/**
 * Format bytes into human-readable size string
 * @param {number|string|null} value - Size value to format
 * @returns {string} - Formatted size string
 */
export function formatSize(value) {
    // Handle non-numeric, null, undefined, and special string values
    if (value === null || value === undefined || value === '-' || value === '') return "-";

    const valueStr = String(value).trim();

    // Handle specific non-numeric values expected from ZFS properties
    const knownStrings = ['on', 'off', 'yes', 'no', 'none', 'default', 'local', 'standard', 'always', 'disabled', 'latency', 'throughput', 'passphrase', 'hex', 'raw', 'available', 'unavailable'];
    if (knownStrings.includes(valueStr.toLowerCase())) {
        return valueStr;
    }
    
    // Handle "inherited from..." and "received" values
    if (valueStr.toLowerCase().startsWith('inherited from') || valueStr.toLowerCase().startsWith('received')) {
        return valueStr;
    }
    
    // Handle ratios like '1.00x'
    if (/^\d+(\.\d+)?x$/i.test(valueStr)) {
        return valueStr;
    }

    // Handle potentially very large numbers as strings from backend or numbers
    if (!/^-?\d+(\.\d+)?$/.test(valueStr)) {
        return valueStr;
    }

    // Now parse as number
    const bytes = parseFloat(valueStr);

    // Handle parsing errors or negative numbers
    if (isNaN(bytes) || bytes < 0) return valueStr;
    if (bytes === 0) return "0B";

    const units = ['B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y'];
    let i = 0;
    let size = bytes;
    
    while (size >= 1024 && i < units.length - 1) {
        size /= 1024.0;
        i++;
    }

    // Adjust precision based on unit and value
    if (i === 0) return `${Math.round(size)}${units[i]}`;
    if (size < 10) return `${size.toFixed(2)}${units[i]}`;
    if (size < 100) return `${size.toFixed(1)}${units[i]}`;
    return `${Math.round(size)}${units[i]}`;
}

/**
 * Validate size input (accepts sizes like "100G" or "none")
 * @param {string} value - Value to validate
 * @returns {boolean} - Whether value is valid
 */
export function validateSizeOrNone(value) {
    if (value.toLowerCase() === 'none') return true;
    return /^\d+(\.\d+)?\s*[KMGTPEZY]?B?$/i.test(value);
}

/**
 * Find a ZFS object by path in the data tree
 * @param {string} path - Path to find
 * @param {string|null} typeHint - Optional type hint for disambiguation
 * @param {Array|null} items - Items to search (defaults to zfsDataCache)
 * @returns {object|null} - Found object or null
 */
export function findObjectByPath(path, typeHint = null, items = null) {
    const searchItems = items || state.zfsDataCache;
    if (!searchItems || !path) return null;
    
    let firstMatchByName = null;

    for (const item of searchItems) {
        if (item.name === path) {
            if (typeHint && item.obj_type === typeHint) {
                return item;
            }
            if (firstMatchByName === null) {
                firstMatchByName = item;
            }
        }

        if (item.children && item.children.length > 0) {
            const found = findObjectByPath(path, typeHint, item.children);
            if (found) {
                return found;
            }
        }
    }
    
    return firstMatchByName;
}

/**
 * Count datasets in a pool recursively
 * @param {object} pool - Pool object
 * @returns {number} - Count of datasets
 */
export function countDatasetsInPool(pool) {
    let count = 0;
    if (pool.children) {
        pool.children.forEach(child => {
            count += 1 + countDatasetsRecursive(child);
        });
    }
    return count;
}

/**
 * Recursive helper to count datasets
 * @param {object} dataset - Dataset object
 * @returns {number} - Count of child datasets
 */
export function countDatasetsRecursive(dataset) {
    let count = 0;
    if (dataset.children) {
        dataset.children.forEach(child => {
            count += 1 + countDatasetsRecursive(child);
        });
    }
    return count;
}

/**
 * Count snapshots in a pool recursively
 * @param {object} pool - Pool object
 * @returns {number} - Count of snapshots
 */
export function countSnapshotsInPool(pool) {
    let count = 0;
    if (pool.children) {
        pool.children.forEach(child => {
            count += countSnapshotsRecursive(child);
        });
    }
    return count;
}

/**
 * Recursive helper to count snapshots
 * @param {object} dataset - Dataset object
 * @returns {number} - Count of snapshots
 */
export function countSnapshotsRecursive(dataset) {
    let count = dataset.snapshots ? dataset.snapshots.length : 0;
    if (dataset.children) {
        dataset.children.forEach(child => {
            count += countSnapshotsRecursive(child);
        });
    }
    return count;
}

/**
 * Create an info row HTML string for dashboard cards
 * @param {string} label - Row label
 * @param {string} value - Row value
 * @param {string} valueClass - Optional CSS class for value
 * @returns {string} - HTML string
 */
export function createInfoRow(label, value, valueClass = '') {
    const classAttr = valueClass ? ` class="info-value ${valueClass}"` : ' class="info-value"';
    return `<div class="info-row"><span class="info-label">${label}</span><span${classAttr}>${value}</span></div>`;
}

/**
 * Escape CSS selector special characters
 * @param {string} str - String to escape
 * @returns {string} - Escaped string
 */
export function escapeSelector(str) {
    return CSS.escape(str);
}
