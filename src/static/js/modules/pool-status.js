/**
 * pool-status.js - Pool Status and Layout Module
 * 
 * Handles rendering of pool status text and pool edit layout tree.
 */

import * as state from './state.js';
import dom from './dom-elements.js';
import { VDEV_GROUP_PATTERNS, DEVICE_PATTERN_RE } from './constants.js';

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
 * @param {string} statusText - Pool status text to parse
 */
export function renderPoolEditLayout(statusText) {
    if (!dom.poolEditTreeContainer) return;
    
    dom.poolEditTreeContainer.innerHTML = '';
    
    if (!statusText || !state.currentSelection || state.currentSelection.obj_type !== 'pool') {
        dom.poolEditTreeContainer.innerHTML = '<div class="text-center p-3 text-muted">Pool layout details not available or item is not a pool.</div>';
        updatePoolEditActionStates(null);
        return;
    }

    const lines = statusText.split('\n');
    const poolName = state.currentSelection.name;

    // Create root element for the tree structure
    const rootUl = document.createElement('ul');
    rootUl.className = 'list-unstyled mb-0 pool-edit-tree-root';

    // Create the top-level pool item
    const poolLi = document.createElement('li');
    poolLi.dataset.indent = -1;
    poolLi.dataset.name = poolName;
    poolLi.dataset.itemType = 'pool';
    poolLi.dataset.vdevType = 'pool';

    // Extract overall pool state and scan info
    let poolState = 'UNKNOWN';
    let scanInfo = '';
    for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith('state:')) { poolState = trimmed.substring(6).trim(); }
        else if (trimmed.startsWith('scan:')) { scanInfo = trimmed.substring(5).trim(); }
        else if (trimmed.startsWith('config:')) { break; }
    }
    poolLi.dataset.state = poolState;

    // Set display text and icon
    let poolStateClass = 'text-muted';
    if (poolState === 'ONLINE') poolStateClass = 'text-success';
    else if (poolState === 'DEGRADED') poolStateClass = 'text-warning';
    else if (poolState === 'FAULTED' || poolState === 'UNAVAIL' || poolState === 'REMOVED') poolStateClass = 'text-danger';
    else if (poolState === 'OFFLINE') poolStateClass = 'text-muted fw-light';

    poolLi.innerHTML = `<i class="bi bi-hdd-rack-fill me-1 ${poolStateClass}"></i> ${poolName} <span class="badge bg-light ${poolStateClass} float-end">${poolState}</span>`;
    poolLi.title = `Pool: ${poolName}\nState: ${poolState}\nScan: ${scanInfo}`;
    poolLi.classList.add('pool-edit-item', 'fw-bold');
    
    poolLi.onclick = (e) => {
        e.stopPropagation();
        dom.poolEditTreeContainer.querySelectorAll('.selected').forEach(el => el.classList.remove('selected'));
        poolLi.classList.add('selected');
        updatePoolEditActionStates(poolLi);
    };
    rootUl.appendChild(poolLi);

    // Regexes for parsing
    const itemRe = /^(\s+)(.+?)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)/;
    const groupRe = /^(\s+)(\S+.*)/;

    let inConfigSection = false;
    let parentStack = [poolLi];

    // Process config section
    for (const line of lines) {
        const lineStrip = line.trim();
        if (lineStrip.startsWith("config:")) {
            inConfigSection = true;
            continue;
        }
        if (!inConfigSection || !lineStrip) continue;
        if (lineStrip.startsWith("errors:")) break;

        // Parse line data
        let matchItem = itemRe.exec(line);
        let matchGroup = groupRe.exec(line);
        let indent = 0;
        let name = "";
        let itemState = "N/A";
        let r = 'N/A', w = 'N/A', c = 'N/A';

        if (matchItem) {
            let indentStr = matchItem[1];
            name = matchItem[2].trim();
            itemState = matchItem[3];
            r = matchItem[4]; w = matchItem[5]; c = matchItem[6];
            indent = indentStr.length;
        } else if (matchGroup) {
            let indentStr = matchGroup[1];
            name = matchGroup[2].trim();
            indent = indentStr.length;
        } else {
            console.warn("Pool Edit: Skipping unparseable line:", lineStrip);
            continue;
        }

        // Skip header row and pool name repetition
        if (name === "NAME" && itemState === "STATE") continue;
        if (name === poolName && parentStack.length === 1 && parentStack[0] === poolLi) continue;

        // Adjust parent stack based on indentation
        while (parentStack.length > 1 && indent <= parseInt(parentStack[parentStack.length - 1].dataset.indent || '0')) {
            parentStack.pop();
        }
        let currentParentLi = parentStack[parentStack.length - 1];
        
        // Ensure the parent has a UL child
        let currentParentUl = currentParentLi.querySelector(':scope > ul.pool-edit-children');
        if (!currentParentUl) {
            currentParentUl = document.createElement('ul');
            currentParentUl.className = 'list-unstyled mb-0 ps-3 pool-edit-children';
            currentParentLi.appendChild(currentParentUl);
        }

        // Determine item type
        let itemType = 'unknown';
        let vdevType = 'unknown';
        let isVdevGroup = false;
        let isDevice = false;
        let devicePathForRole = null;

        for (const vtype in VDEV_GROUP_PATTERNS) {
            if (VDEV_GROUP_PATTERNS[vtype].test(name)) {
                itemType = 'vdev';
                vdevType = vtype;
                isVdevGroup = true;
                break;
            }
        }

        const parentVdevType = currentParentLi.dataset.vdevType;
        const isUnderKnownVdevGroup = parentVdevType && parentVdevType !== 'unknown' && parentVdevType !== 'pool';

        if (!isVdevGroup && DEVICE_PATTERN_RE.test(name)) {
            if (matchItem || isUnderKnownVdevGroup) {
                itemType = 'device';
                isDevice = true;
                devicePathForRole = name;
                if (isUnderKnownVdevGroup) {
                    vdevType = parentVdevType;
                } else if (currentParentLi === poolLi) {
                    vdevType = 'disk';
                }
            } else if (currentParentLi === poolLi && !matchItem) {
                itemType = 'vdev';
                vdevType = 'disk';
                devicePathForRole = name;
            }
        } else if (!isVdevGroup && !isDevice && currentParentLi === poolLi) {
            itemType = 'vdev';
            vdevType = 'disk';
            devicePathForRole = name;
        }

        if (itemType === 'unknown') {
            console.warn("Pool Edit: Could not determine item type for:", name, "under", currentParentLi.dataset.name);
        }

        // Create the list item
        const li = document.createElement('li');
        li.classList.add('pool-edit-item');
        li.dataset.indent = indent;
        li.dataset.name = name;
        li.dataset.itemType = itemType;
        li.dataset.vdevType = vdevType;
        li.dataset.state = itemState;
        if (devicePathForRole) li.dataset.devicePath = devicePathForRole;

        // Determine icon
        let iconClass = 'bi-question-circle';
        if (itemType === 'pool') iconClass = 'bi-hdd-rack-fill';
        else if (itemType === 'vdev') {
            if (vdevType === 'disk') iconClass = 'bi-hdd';
            else if (['log', 'cache', 'spare', 'special'].includes(vdevType)) iconClass = 'bi-drive-fill';
            else iconClass = 'bi-hdd-stack';
        } else if (itemType === 'device') iconClass = 'bi-disc';

        // Set text and state badge
        let stateHtml = '';
        if (itemState !== 'N/A' && itemState !== name) {
            let stateClass = 'text-muted';
            if (itemState === 'ONLINE') stateClass = 'text-success';
            else if (itemState === 'DEGRADED') stateClass = 'text-warning';
            else if (itemState === 'FAULTED' || itemState === 'UNAVAIL' || itemState === 'REMOVED') stateClass = 'text-danger';
            else if (itemState === 'OFFLINE') stateClass = 'text-muted fw-light';
            stateHtml = `<span class="badge bg-light ${stateClass} float-end">${itemState}</span>`;
        }

        // Display errors if present
        let errorHtml = '';
        if (matchItem && (r !== '0' || w !== '0' || c !== '0')) {
            errorHtml = ` <small class="text-danger">(${r}R ${w}W ${c}C)</small>`;
        }

        li.innerHTML = `<i class="bi ${iconClass} me-1"></i> ${name}${errorHtml}${stateHtml}`;
        li.title = `Type: ${itemType}\nVDEV Type: ${vdevType}\nState: ${itemState}${devicePathForRole ? '\nPath: '+devicePathForRole : ''}${errorHtml ? `\nErrors: ${r}R ${w}W ${c}C` : ''}`;

        // Add click handler
        li.onclick = (e) => {
            e.stopPropagation();
            dom.poolEditTreeContainer.querySelectorAll('.selected').forEach(el => el.classList.remove('selected'));
            li.classList.add('selected');
            updatePoolEditActionStates(li);
        };

        currentParentUl.appendChild(li);

        // If it's a VDEV group, push it onto the stack
        if (itemType === 'vdev' || itemType === 'pool') {
            parentStack.push(li);
        }
    }

    dom.poolEditTreeContainer.appendChild(rootUl);
    updatePoolEditActionStates(null);
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
