/**
 * pool-status.js - Pool Status and Layout Module
 * 
 * Handles rendering of pool status text and pool edit layout tree.
 */

import * as state from './state.js';
import dom from './dom-elements.js';


// Track current pool status view mode and cached data
let currentPoolStatusView = 'status'; // 'status', 'layout', or 'iostat'
let cachedPoolStatusData = {
    status: null,
    layout: null,
    iostat: null
};
let currentPoolName = null;

/**
 * Update the active state of pool status view buttons
 * @param {string} activeView - The current active view ('status', 'layout', or 'iostat')
 */
function updatePoolStatusButtons(activeView) {
    if (dom.poolStatusBtn) {
        dom.poolStatusBtn.classList.toggle('active', activeView === 'status');
    }
    if (dom.poolLayoutBtn) {
        dom.poolLayoutBtn.classList.toggle('active', activeView === 'layout');
    }
    if (dom.poolIostatBtn) {
        dom.poolIostatBtn.classList.toggle('active', activeView === 'iostat');
    }
}

/**
 * Set pool status buttons enabled/disabled state
 * @param {boolean} enabled - Whether buttons should be enabled
 */
export function setPoolStatusButtonsEnabled(enabled) {
    if (dom.poolStatusBtn) dom.poolStatusBtn.disabled = !enabled;
    if (dom.poolLayoutBtn) dom.poolLayoutBtn.disabled = !enabled;
    if (dom.poolIostatBtn) dom.poolIostatBtn.disabled = !enabled;
}

/**
 * Fetch pool data from API
 * @param {string} poolName - Name of the pool
 * @param {string} dataType - Type of data to fetch ('layout' or 'iostat')
 * @returns {Promise<string>} - The fetched data
 */
async function fetchPoolData(poolName, dataType) {
    const endpoint = dataType === 'layout'
        ? `/api/pool/${encodeURIComponent(poolName)}/list_verbose`
        : `/api/pool/${encodeURIComponent(poolName)}/iostat_verbose`;
    try {
        const response = await fetch(endpoint);
        const result = await response.json();
        if (result.status === 'success') {
            return result.data || `No ${dataType} data available.`;
        } else {
            return `Error fetching ${dataType}: ${result.error || 'Unknown error'}`;
        }
    } catch (error) {
        console.error(`Error fetching pool ${dataType}:`, error);
        return `Error fetching ${dataType}: ${error.message}`;
    }
}

/**
 * Switch the pool status view
 * @param {string} viewType - The view to switch to ('status', 'layout', or 'iostat')
 */
export async function switchPoolStatusView(viewType) {
    if (!currentPoolName || !state.currentSelection || state.currentSelection.obj_type !== 'pool') {
        renderPoolStatus('Select a pool to view its information.');
        return;
    }

    currentPoolStatusView = viewType;
    updatePoolStatusButtons(viewType);

    if (viewType === 'status') {
        // Use cached status data (from pool's status_details)
        renderPoolStatus(cachedPoolStatusData.status);
    } else {
        // Check cache first
        if (cachedPoolStatusData[viewType]) {
            renderPoolStatus(cachedPoolStatusData[viewType]);
        } else {
            // Show loading message
            renderPoolStatus(`Loading ${viewType === 'layout' ? 'pool layout' : 'IO statistics'}...`);
            // Fetch data
            const data = await fetchPoolData(currentPoolName, viewType);
            cachedPoolStatusData[viewType] = data;
            // Only update if still on the same view
            if (currentPoolStatusView === viewType) {
                renderPoolStatus(data);
            }
        }
    }
}

/**
 * Initialize pool status view with status data and reset cache
 * @param {string} poolName - Name of the pool
 * @param {string} statusText - The pool status text
 */
export function initPoolStatusView(poolName, statusText) {
    // Reset cache when pool changes
    if (poolName !== currentPoolName) {
        cachedPoolStatusData = {
            status: statusText,
            layout: null,
            iostat: null
        };
        currentPoolName = poolName;
        currentPoolStatusView = 'status';
        updatePoolStatusButtons('status');
    } else {
        // Just update status cache
        cachedPoolStatusData.status = statusText;
    }

    // Enable buttons when pool is selected
    setPoolStatusButtonsEnabled(true);

    // If currently viewing status, update display
    if (currentPoolStatusView === 'status') {
        renderPoolStatus(statusText);
    }
}

/**
 * Clear pool status view (when non-pool is selected)
 */
export function clearPoolStatusView() {
    currentPoolName = null;
    cachedPoolStatusData = {
        status: null,
        layout: null,
        iostat: null
    };
    currentPoolStatusView = 'status';
    updatePoolStatusButtons('status');
    setPoolStatusButtonsEnabled(false);
    renderPoolStatus('Pool status not applicable.');
}

/**
 * Initialize pool status button event listeners
 */
export function initPoolStatusButtons() {
    if (dom.poolStatusBtn) {
        dom.poolStatusBtn.addEventListener('click', () => switchPoolStatusView('status'));
    }
    if (dom.poolLayoutBtn) {
        dom.poolLayoutBtn.addEventListener('click', () => switchPoolStatusView('layout'));
    }
    if (dom.poolIostatBtn) {
        dom.poolIostatBtn.addEventListener('click', () => switchPoolStatusView('iostat'));
    }
    // Initially disable buttons until a pool is selected
    setPoolStatusButtonsEnabled(false);
}

/**
 * Render pool status text
 * @param {string} statusText - Pool status text
 */
export function renderPoolStatus(statusText) {
    if (dom.poolStatusContent) {
        dom.poolStatusContent.textContent = statusText || 'Pool status not available.';
    }
}

/**
 * Render pool edit layout tree
 * @param {string} statusText - Pool status text (fallback if vdev_tree unavailable)
 */
export function renderPoolEditLayout(statusText) {
    if (!dom.poolEditTreeContainer) return;

    dom.poolEditTreeContainer.innerHTML = '';

    if (!state.currentSelection || state.currentSelection.obj_type !== 'pool') {
        dom.poolEditTreeContainer.innerHTML = '<div class="text-center p-3 text-muted">Pool layout details not available or item is not a pool.</div>';
        updatePoolEditActionStates(null);
        return;
    }

    const poolName = state.currentSelection.name;
    const vdevTree = state.currentSelection.vdev_tree;

    // Create root element for the tree structure
    const rootUl = document.createElement('ul');
    rootUl.className = 'list-unstyled mb-0 pool-edit-tree-root';

    // Prefer structured vdev_tree if available
    if (vdevTree && Object.keys(vdevTree).length > 0) {
        renderVdevTreeFromJson(rootUl, vdevTree, poolName);
    } else {
        dom.poolEditTreeContainer.innerHTML = '<div class="text-center p-3 text-muted">Pool layout details not available.</div>';
        updatePoolEditActionStates(null);
        return;
    }

    dom.poolEditTreeContainer.appendChild(rootUl);
    updatePoolEditActionStates(null);
}

/**
 * Render VDEV tree from structured JSON (vdev_tree)
 * @param {HTMLElement} rootUl - Root UL element
 * @param {Object} vdevTree - Structured vdev tree from backend
 * @param {string} poolName - Pool name
 */
function renderVdevTreeFromJson(rootUl, vdevTree, poolName) {
    // Create the top-level pool item
    const poolState = vdevTree.state || 'UNKNOWN';
    const poolLi = createPoolEditItem(poolName, 'pool', 'pool', poolState, null);
    poolLi.dataset.indent = -1;
    rootUl.appendChild(poolLi);

    // Add children recursively
    const children = vdevTree.children || [];
    if (children.length > 0) {
        const childUl = document.createElement('ul');
        childUl.className = 'list-unstyled mb-0 ps-3 pool-edit-children';
        addVdevChildrenFromJson(childUl, children);
        poolLi.appendChild(childUl);
    }
}

/**
 * Recursively add VDEV children from JSON
 * @param {HTMLElement} parentUl - Parent UL element
 * @param {Array} children - Array of child vdev objects
 */
function addVdevChildrenFromJson(parentUl, children) {
    for (const child of children) {
        const name = child.name || 'unknown';
        const vdevType = child.type || 'unknown';
        const itemState = child.state || 'UNKNOWN';
        const devicePath = child.path || null;
        const readErrors = child.read_errors || '0';
        const writeErrors = child.write_errors || '0';
        const checksumErrors = child.checksum_errors || '0';

        // Determine item type
        const isLeafDevice = vdevType === 'disk' && devicePath;
        const itemType = isLeafDevice ? 'device' : 'vdev';

        const li = createPoolEditItem(name, itemType, vdevType, itemState, devicePath, readErrors, writeErrors, checksumErrors);
        parentUl.appendChild(li);

        // Recurse for children
        const childChildren = child.children || [];
        if (childChildren.length > 0) {
            const childUl = document.createElement('ul');
            childUl.className = 'list-unstyled mb-0 ps-3 pool-edit-children';
            addVdevChildrenFromJson(childUl, childChildren);
            li.appendChild(childUl);
        }
    }
}

/**
 * Create a pool edit tree item element
 * @param {string} name - Item name
 * @param {string} itemType - Item type (pool, vdev, device)
 * @param {string} vdevType - VDEV type (mirror, raidz, disk, etc.)
 * @param {string} itemState - State (ONLINE, OFFLINE, etc.)
 * @param {string|null} devicePath - Device path (for devices)
 * @param {string} r - Read errors
 * @param {string} w - Write errors
 * @param {string} c - Checksum errors
 * @returns {HTMLElement} - LI element
 */
function createPoolEditItem(name, itemType, vdevType, itemState, devicePath, r = '0', w = '0', c = '0') {
    const li = document.createElement('li');
    li.classList.add('pool-edit-item');
    li.dataset.name = name;
    li.dataset.itemType = itemType;
    li.dataset.vdevType = vdevType;
    li.dataset.state = itemState;
    if (devicePath) li.dataset.devicePath = devicePath;

    // Determine icon
    let iconClass = 'bi-question-circle';
    if (itemType === 'pool') iconClass = 'bi-hdd-rack-fill';
    else if (itemType === 'vdev') {
        if (vdevType === 'disk') iconClass = 'bi-hdd';
        else if (['log', 'cache', 'spare', 'special'].includes(vdevType)) iconClass = 'bi-drive-fill';
        else iconClass = 'bi-hdd-stack';
    } else if (itemType === 'device') iconClass = 'bi-disc';

    // Set text and state badge
    let stateClass = 'text-muted';
    if (itemState === 'ONLINE') stateClass = 'text-success';
    else if (itemState === 'DEGRADED') stateClass = 'text-warning';
    else if (['FAULTED', 'UNAVAIL', 'REMOVED'].includes(itemState)) stateClass = 'text-danger';
    else if (itemState === 'OFFLINE') stateClass = 'text-muted fw-light';

    const stateHtml = `<span class="badge bg-light ${stateClass} float-end">${itemState}</span>`;

    // Display errors if present
    let errorHtml = '';
    if (r !== '0' || w !== '0' || c !== '0') {
        errorHtml = ` <small class="text-danger">(${r}R ${w}W ${c}C)</small>`;
    }

    li.innerHTML = `<i class="bi ${iconClass} me-1"></i> ${name}${errorHtml}${stateHtml}`;
    li.title = `Type: ${itemType}\nVDEV Type: ${vdevType}\nState: ${itemState}${devicePath ? '\nPath: ' + devicePath : ''}${errorHtml ? `\nErrors: ${r}R ${w}W ${c}C` : ''}`;

    // Add click handler
    li.onclick = (e) => {
        e.stopPropagation();
        dom.poolEditTreeContainer.querySelectorAll('.selected').forEach(el => el.classList.remove('selected'));
        li.classList.add('selected');
        updatePoolEditActionStates(li);
    };

    return li;
}




/**
 * Update pool edit action button states based on selection
 * @param {HTMLElement|null} selectedLi - Selected list item element
 */
export function updatePoolEditActionStates(selectedLi) {
    // Reset all buttons first
    const buttonIds = ['attach-device-button', 'detach-device-button', 'replace-device-button',
        'offline-device-button', 'online-device-button', 'remove-pool-vdev-button',
        'split-pool-button'];
    buttonIds.forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = true;
    });

    // Add VDEV button is always enabled if a pool is selected
    const addVdevBtn = document.getElementById('add-pool-vdev-button');
    if (addVdevBtn) addVdevBtn.disabled = !state.currentSelection || state.currentSelection.obj_type !== 'pool';

    if (!selectedLi || !state.currentSelection || state.currentSelection.obj_type !== 'pool') {
        return;
    }

    const itemType = selectedLi.dataset.itemType;
    const vdevType = selectedLi.dataset.vdevType;
    const deviceState = selectedLi.dataset.state?.toUpperCase();
    const devicePath = selectedLi.dataset.devicePath;
    const isDevice = itemType === 'device';
    const isVdev = itemType === 'vdev';
    const isPoolItem = itemType === 'pool';

    const parentLi = selectedLi.parentElement?.closest('li.pool-edit-item');
    const parentItemType = parentLi?.dataset.itemType;
    const parentVdevType = parentLi?.dataset.vdevType;

    // Attach Button
    if (deviceState === 'ONLINE' && devicePath) {
        if (parentItemType === 'pool' || parentVdevType === 'disk' || (parentVdevType && !['mirror', 'log', 'cache', 'spare'].includes(parentVdevType))) {
            document.getElementById('attach-device-button').disabled = false;
        }
    }

    // Detach Button
    if (isDevice && parentVdevType === 'mirror' && parentLi) {
        const siblingDevices = parentLi.querySelectorAll(':scope > ul.pool-edit-children > li[data-item-type="device"]');
        if (siblingDevices.length > 1) {
            document.getElementById('detach-device-button').disabled = false;
        }
    }

    // Replace Button
    if (devicePath && (isDevice || (isVdev && vdevType === 'disk'))) {
        document.getElementById('replace-device-button').disabled = false;
    }

    // Offline Button
    if (devicePath && deviceState === 'ONLINE' && (isDevice || (isVdev && vdevType === 'disk'))) {
        document.getElementById('offline-device-button').disabled = false;
    }

    // Online Button
    if (devicePath && deviceState === 'OFFLINE' && (isDevice || (isVdev && vdevType === 'disk'))) {
        document.getElementById('online-device-button').disabled = false;
    }

    // Remove VDEV Button
    if (isVdev && parentItemType === 'pool') {
        if (['log', 'cache', 'spare'].includes(vdevType)) {
            document.getElementById('remove-pool-vdev-button').disabled = false;
        } else {
            let dataVdevCount = 0;
            const poolRootItem = dom.poolEditTreeContainer.querySelector('li[data-item-type="pool"]');
            const topLevelChildrenUl = poolRootItem?.querySelector(':scope > ul.pool-edit-children');
            if (topLevelChildrenUl) {
                topLevelChildrenUl.querySelectorAll(':scope > li[data-item-type="vdev"]').forEach(siblingLi => {
                    if (!['log', 'cache', 'spare'].includes(siblingLi.dataset.vdevType)) {
                        dataVdevCount++;
                    }
                });
            }
            if (dataVdevCount > 1) {
                document.getElementById('remove-pool-vdev-button').disabled = false;
            }
        }
    }

    // Split Pool Button
    if (isPoolItem) {
        let isFullyMirrored = true;
        let hasDataVdev = false;
        const poolRootItem = selectedLi;
        const topLevelChildrenUl = poolRootItem.querySelector(':scope > ul.pool-edit-children');
        if (topLevelChildrenUl) {
            const topLevelVdevs = topLevelChildrenUl.querySelectorAll(':scope > li[data-item-type="vdev"]');
            if (topLevelVdevs.length === 0) {
                isFullyMirrored = false;
            }
            topLevelVdevs.forEach(topVdevLi => {
                const topVdevType = topVdevLi.dataset.vdevType;
                if (!['log', 'cache', 'spare'].includes(topVdevType)) {
                    hasDataVdev = true;
                    const devicesInVdev = topVdevLi.querySelectorAll(':scope > ul.pool-edit-children > li[data-item-type="device"]').length;
                    if (topVdevType !== 'mirror' || devicesInVdev < 2) {
                        isFullyMirrored = false;
                    }
                }
            });
        } else {
            isFullyMirrored = false;
        }

        if (hasDataVdev && isFullyMirrored) {
            document.getElementById('split-pool-button').disabled = false;
        }
    }
}
