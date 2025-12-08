/**
 * pool-actions.js - Pool Action Handlers Module
 * 
 * Handles pool creation, import, export, destroy, and other pool-level actions.
 */

import * as state from './state.js';
import dom from './dom-elements.js';
import { apiCall, executeActionWithRefresh } from './api.js';
import { showModal, hideModal, updateStatus } from './ui.js';
import { RESERVED_POOL_NAMES, VDEV_TYPES, MIN_DEVICES_PER_VDEV } from './constants.js';

// Store available devices map during modal operations
let availableDevicesMap = {};

/**
 * Handle create pool action
 */
export function handleCreatePool() {
    let availableDevicesHtml = '<p class="text-muted">Loading available devices...</p>';
    let modalHtml = `
        <div class="mb-3">
            <label for="pool-name-input" class="form-label">Pool Name:</label>
            <input type="text" class="form-control" id="pool-name-input" placeholder="e.g., tank, mypool" required>
            <div class="invalid-feedback">Pool name is required and cannot contain spaces or '/'.</div>
        </div>
        <div class="form-check mb-3">
            <input class="form-check-input" type="checkbox" value="" id="pool-force-create-check">
            <label class="form-check-label" for="pool-force-create-check">
                Force Creation (-f) <small class="text-muted">(Use with caution)</small>
            </label>
        </div>
        <hr>
        <h6>Pool Layout</h6>
        <div class="row">
            <div class="col-md-5">
                <label class="form-label">Available Devices:</label>
                <ul id="pool-available-devices" class="list-group list-group-flush border rounded" style="max-height: 200px; overflow-y: auto;">${availableDevicesHtml}</ul>
            </div>
            <div class="col-md-1 d-flex flex-column align-items-center justify-content-center">
                <button type="button" id="pool-add-device-btn" class="btn btn-sm btn-outline-primary mb-2" title="Add Selected Device(s) to VDEV">>></button>
                <button type="button" id="pool-remove-device-btn" class="btn btn-sm btn-outline-danger mt-2" title="Remove Selected Device/VDEV"><<</button>
            </div>
            <div class="col-md-6">
                <label class="form-label">VDEVs in Pool:</label>
                <div id="pool-vdev-config" class="border rounded p-1 bg-light" style="min-height: 150px;">
                    <ul class="list-unstyled mb-0" id="pool-vdev-list"></ul>
                </div>
                <div class="text-end mt-1">
                    <button type="button" id="pool-add-vdev-btn" class="btn btn-sm btn-success"><i class="bi bi-plus-circle"></i> Add VDEV Type</button>
                </div>
            </div>
        </div>
    `;

    showModal('Create New Pool', modalHtml, handleCreatePoolConfirm, { size: 'xl', setupFunc: setupCreatePoolModal });
}

/**
 * Setup create pool modal
 */
export function setupCreatePoolModal() {
    const availableList = document.getElementById('pool-available-devices');
    const vdevList = document.getElementById('pool-vdev-list');
    
    // Store map on modal body
    const modalBody = document.getElementById('actionModalBody');
    if (!modalBody) {
        console.error("Modal body not found for map storage!");
        return;
    }
    modalBody.modalAvailableDevicesMap = {};
    availableDevicesMap = modalBody.modalAvailableDevicesMap;

    // Add event listeners
    document.getElementById('pool-add-vdev-btn')?.addEventListener('click', () => addVdevTypeToPoolConfig(vdevList));
    document.getElementById('pool-add-device-btn')?.addEventListener('click', () => addDeviceToPoolVdev(availableList, vdevList, availableDevicesMap));
    document.getElementById('pool-remove-device-btn')?.addEventListener('click', () => {
        const selectedVdev = getSelectedPoolVdev(vdevList);
        const selectedDevice = getSelectedPoolDeviceInVdev(vdevList);

        if (selectedDevice) {
            removeDeviceFromPoolVdev(availableList, vdevList, availableDevicesMap);
        } else if (selectedVdev) {
            removeVdevFromPoolConfig(selectedVdev, availableList, availableDevicesMap);
        } else {
            alert("Please select a VDEV or a device within a VDEV to remove.");
        }
    });

    // Fetch available devices
    apiCall('/api/block_devices')
        .then(result => {
            availableList.innerHTML = '';
            const devices = result.data?.devices || [];
            if (result.data?.error) {
                availableList.innerHTML = `<li class="list-group-item text-danger">Error: ${result.data.error}</li>`;
                return;
            }
            if (devices.length === 0) {
                availableList.innerHTML = '<li class="list-group-item text-muted">No suitable devices found.</li>';
                return;
            }
            devices.forEach(dev => {
                availableDevicesMap[dev.name] = dev;
                const li = document.createElement('li');
                li.className = 'list-group-item list-group-item-action py-1 pool-device-item';
                li.textContent = dev.display_name || dev.name;
                li.dataset.path = dev.name;
                li.onclick = (e) => e.currentTarget.classList.toggle('active');
                availableList.appendChild(li);
            });
            const items = Array.from(availableList.children);
            items.sort((a, b) => a.textContent.localeCompare(b.textContent));
            availableList.innerHTML = '';
            items.forEach(item => availableList.appendChild(item));
        })
        .catch(error => {
            availableList.innerHTML = `<li class="list-group-item text-danger">Error loading devices: ${error.message}</li>`;
        });
}

/**
 * Add VDEV type to pool config
 * Exported for use by pool-edit-actions.js
 */
export function addVdevTypeToPoolConfig(vdevList) {
    const vdevType = prompt(`Select VDEV Type:\n(${VDEV_TYPES.join(', ')})`, 'disk');
    if (vdevType && VDEV_TYPES.includes(vdevType.toLowerCase())) {
        const type = vdevType.toLowerCase();
        const vdevId = `vdev-${type}-${Date.now()}`;
        const li = document.createElement('li');
        li.className = 'list-group-item py-1 pool-vdev-item mb-1';
        li.dataset.vdevType = type;
        li.dataset.vdevId = vdevId;
        li.innerHTML = `
            <div class="d-flex justify-content-between align-items-center">
                <span><strong>${type.toUpperCase()}</strong> VDEV</span>
                <button type="button" class="btn btn-sm btn-outline-danger py-0 px-1 remove-vdev-btn" title="Remove this VDEV">
                    <i class="bi bi-trash3-fill"></i>
                </button>
            </div>
            <ul class="list-unstyled ps-3 mb-0 device-list-in-vdev"></ul>`;
        
        li.onclick = (e) => {
            if (e.target.classList.contains('pool-vdev-item') || e.target.closest('.d-flex')) {
                vdevList.querySelectorAll('.pool-vdev-item.active, .pool-vdev-device-item.active').forEach(el => el.classList.remove('active'));
                li.classList.add('active');
            }
        };
        
        li.querySelector('.remove-vdev-btn').onclick = (e) => {
            e.stopPropagation();
            const availableListEl = document.getElementById('pool-available-devices');
            const modalBody = document.getElementById('actionModalBody');
            const map = modalBody?.modalAvailableDevicesMap || {};
            removeVdevFromPoolConfig(li, availableListEl, map);
        };
        
        vdevList.appendChild(li);
    } else if (vdevType !== null) {
        alert("Invalid VDEV type selected.");
    }
}

/**
 * Get selected pool VDEV
 * Exported for use by pool-edit-actions.js
 */
export function getSelectedPoolVdev(vdevList) {
    return vdevList.querySelector('.pool-vdev-item.active');
}

/**
 * Get selected device in VDEV
 * Exported for use by pool-edit-actions.js
 */
export function getSelectedPoolDeviceInVdev(vdevList) {
    return vdevList.querySelector('.pool-vdev-device-item.active');
}

/**
 * Add device to pool VDEV
 * Exported for use by pool-edit-actions.js
 */
export function addDeviceToPoolVdev(availableList, vdevList, devicesMap) {
    const selectedVdevLi = getSelectedPoolVdev(vdevList);
    if (!selectedVdevLi) {
        alert("Please select a VDEV in the pool layout first.");
        return;
    }
    const selectedAvailableItems = availableList.querySelectorAll('.pool-device-item.active');
    if (selectedAvailableItems.length === 0) {
        alert("Please select one or more available devices to add.");
        return;
    }

    const deviceListInVdev = selectedVdevLi.querySelector('.device-list-in-vdev');
    selectedAvailableItems.forEach(availItem => {
        const path = availItem.dataset.path;
        const devInfo = devicesMap[path];
        const display = devInfo?.display_name || path;

        if (deviceListInVdev.querySelector(`li[data-path="${CSS.escape(path)}"]`)) {
            console.log(`Device ${path} already in this VDEV.`);
            return;
        }

        const deviceLi = document.createElement('li');
        deviceLi.className = 'list-group-item list-group-item-action py-1 pool-vdev-device-item';
        deviceLi.textContent = display;
        deviceLi.dataset.path = path;
        deviceLi.onclick = (e) => {
            e.stopPropagation();
            vdevList.querySelectorAll('.pool-vdev-item.active, .pool-vdev-device-item.active').forEach(el => el.classList.remove('active'));
            deviceLi.classList.add('active');
        };
        deviceListInVdev.appendChild(deviceLi);
        availItem.remove();
    });
}

/**
 * Remove device from pool VDEV
 * Exported for use by pool-edit-actions.js
 */
export function removeDeviceFromPoolVdev(availableList, vdevList, devicesMap) {
    const selectedDeviceLi = getSelectedPoolDeviceInVdev(vdevList);
    if (!selectedDeviceLi) {
        const selectedVdevLi = getSelectedPoolVdev(vdevList);
        if (selectedVdevLi) {
            removeVdevFromPoolConfig(selectedVdevLi, availableList, devicesMap);
        } else {
            alert("Please select a device within a VDEV in the pool layout to remove.");
        }
        return;
    }

    const path = selectedDeviceLi.dataset.path;
    selectedDeviceLi.remove();

    const devInfo = devicesMap ? devicesMap[path] : { name: path };
    const display = devInfo?.display_name || path;
    const availLi = document.createElement('li');
    availLi.className = 'list-group-item list-group-item-action py-1 pool-device-item';
    availLi.textContent = display;
    availLi.dataset.path = path;
    availLi.onclick = (e) => e.currentTarget.classList.toggle('active');
    availableList.appendChild(availLi);
    
    // Re-sort
    const items = Array.from(availableList.children);
    items.sort((a, b) => a.textContent.localeCompare(b.textContent));
    availableList.innerHTML = '';
    items.forEach(item => availableList.appendChild(item));
}

/**
 * Remove VDEV from pool config
 * Exported for use by pool-edit-actions.js
 */
export function removeVdevFromPoolConfig(vdevLiToRemove, availableList, devicesMap) {
    const devicesInVdev = vdevLiToRemove.querySelectorAll('.pool-vdev-device-item');
    devicesInVdev.forEach(deviceLi => {
        const path = deviceLi.dataset.path;
        const devInfo = devicesMap ? devicesMap[path] : { name: path };
        const display = devInfo?.display_name || path;
        const availLi = document.createElement('li');
        availLi.className = 'list-group-item list-group-item-action py-1 pool-device-item';
        availLi.textContent = display;
        availLi.dataset.path = path;
        availLi.onclick = (e) => e.currentTarget.classList.toggle('active');
        availableList.appendChild(availLi);
    });
    
    // Re-sort
    const items = Array.from(availableList.children);
    items.sort((a, b) => a.textContent.localeCompare(b.textContent));
    availableList.innerHTML = '';
    items.forEach(item => availableList.appendChild(item));

    vdevLiToRemove.remove();
}

/**
 * Handle create pool confirmation
 */
function handleCreatePoolConfirm() {
    const poolNameInput = document.getElementById('pool-name-input');
    const forceCheckbox = document.getElementById('pool-force-create-check');
    const poolName = poolNameInput.value.trim();
    const forceCreate = forceCheckbox.checked;

    if (!poolName || poolName.includes(' ') || poolName.includes('/')) {
        alert("Pool name is required and cannot contain spaces or '/'.");
        poolNameInput.classList.add('is-invalid');
        return;
    }
    if (!/^[a-zA-Z]/.test(poolName)) {
        alert("Pool name must start with a letter.");
        poolNameInput.classList.add('is-invalid');
        return;
    }
    if (/[^a-zA-Z0-9_\-:.%]/.test(poolName)) {
        alert("Pool name contains invalid characters. Allowed: A-Z a-z 0-9 _ - : . %");
        poolNameInput.classList.add('is-invalid');
        return;
    }
    if (RESERVED_POOL_NAMES.includes(poolName.toLowerCase())) {
        alert(`Pool name cannot be a reserved keyword ('${poolName}').`);
        poolNameInput.classList.add('is-invalid');
        return;
    }
    poolNameInput.classList.remove('is-invalid');

    const vdevSpecs = [];
    const vdevItems = document.querySelectorAll('#pool-vdev-list > .pool-vdev-item');
    if (vdevItems.length === 0) {
        alert("Pool layout is empty. Please add at least one VDEV with devices.");
        return;
    }

    let hasDataVdev = false;
    let layoutValid = true;
    vdevItems.forEach(vdevLi => {
        const vdevType = vdevLi.dataset.vdevType;
        const devices = [];
        vdevLi.querySelectorAll('.pool-vdev-device-item').forEach(devLi => {
            devices.push(devLi.dataset.path);
        });

        const minDevices = MIN_DEVICES_PER_VDEV[vdevType] || 1;
        if (devices.length < minDevices) {
            alert(`VDEV type '${vdevType}' requires at least ${minDevices} device(s). Found ${devices.length}.`);
            layoutValid = false;
            return;
        }

        vdevSpecs.push({ type: vdevType, devices: devices });
        if (!['log', 'cache', 'spare'].includes(vdevType)) {
            hasDataVdev = true;
        }
    });

    if (!layoutValid) return;

    if (!hasDataVdev) {
        alert("Pool must contain at least one data VDEV (disk, mirror, raidz).");
        return;
    }

    hideModal();
    executeActionWithRefresh(
        'create_pool',
        [],
        { pool_name: poolName, vdev_specs: vdevSpecs, options: {}, force: forceCreate },
        `Pool '${poolName}' creation initiated.`
    );
}

/**
 * Handle import pool action
 */
export function handleImportPool() {
    let modalHtml = `<p class="text-muted">Searching for importable pools...</p>
        <div id="importable-pools-list" class="list-group"></div> <hr>
        <div class="row g-3 align-items-center"> <div class="col-auto">
        <label for="import-new-name" class="col-form-label">Import Selected As:</label>
        </div> <div class="col-auto">
        <input type="text" id="import-new-name" class="form-control form-control-sm" placeholder="(optional)">
        </div> </div>
        <div class="form-check mt-2">
        <input class="form-check-input" type="checkbox" value="" id="import-force-check">
        <label class="form-check-label" for="import-force-check"> Force Import (-f) </label>
        </div>`;
    let modalFooterHtml = `
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="importModalConfirmSelectedButton" disabled>Import Selected</button>
        <button type="button" class="btn btn-warning" id="importModalConfirmAllButton" disabled>Import All</button>`;

    showModal('Import ZFS Pools', modalHtml, null, {
        footerHtml: modalFooterHtml,
        setupFunc: setupImportPoolModal,
        onConfirmAll: () => {
            if (!confirm("Are you sure you want to attempt importing ALL listed pools?")) return;
            const force = document.getElementById('import-force-check').checked;
            hideModal();
            executeActionWithRefresh(
                'import_pool',
                [],
                { pool_name_or_id: null, new_name: null, force: force },
                `Import of all pools initiated.`
            );
        }
    });
}

/**
 * Setup import pool modal
 */
function setupImportPoolModal() {
    const listGroup = document.getElementById('importable-pools-list');
    const newNameInput = document.getElementById('import-new-name');
    const forceCheck = document.getElementById('import-force-check');
    const importSelectedBtn = document.getElementById('importModalConfirmSelectedButton');

    newNameInput.disabled = true;

    importSelectedBtn.onclick = () => {
        const selectedItem = listGroup.querySelector('.list-group-item.active');
        if (!selectedItem) return;
        const poolId = selectedItem.dataset.poolId;
        const newName = newNameInput.value.trim() || null;
        const force = forceCheck.checked;

        if (newName && !/^[a-zA-Z][a-zA-Z0-9_\-:.%]*$/.test(newName)) {
            alert("Invalid new pool name format.");
            return;
        }
        if (newName && RESERVED_POOL_NAMES.includes(newName.toLowerCase())) {
            alert(`New pool name cannot be a reserved keyword ('${newName}').`);
            return;
        }

        hideModal();
        executeActionWithRefresh(
            'import_pool',
            [],
            { pool_name_or_id: poolId, new_name: newName, force: force },
            `Import of pool '${poolId}' initiated.`
        );
    };

    apiCall('/api/importable_pools')
        .then(result => {
            listGroup.innerHTML = '';
            const importAllBtn = document.getElementById('importModalConfirmAllButton');
            if (!result.data || result.data.length === 0) {
                listGroup.innerHTML = '<div class="list-group-item text-muted">No importable pools found.</div>';
                if (importAllBtn) importAllBtn.disabled = true;
                return;
            }

            result.data.forEach(pool => {
                const a = document.createElement('a');
                a.href = "#";
                a.className = 'list-group-item list-group-item-action flex-column align-items-start py-2';
                a.dataset.poolId = pool.id || pool.name;
                a.innerHTML = `
                    <div class="d-flex w-100 justify-content-between">
                        <h6 class="mb-1">${pool.name}</h6>
                        <small class="${pool.state !== 'ONLINE' ? 'text-danger fw-bold': 'text-muted'}">${pool.state || '?'}</small>
                    </div>
                    <p class="mb-1"><small>ID: ${pool.id || 'N/A'}</small></p>
                    ${pool.action ? `<small class="text-info">${pool.action}</small>`: ''}
                `;
                a.onclick = (e) => {
                    e.preventDefault();
                    listGroup.querySelectorAll('a.active').forEach(el => el.classList.remove('active'));
                    a.classList.add('active');
                    importSelectedBtn.disabled = false;
                    newNameInput.disabled = false;
                };
                listGroup.appendChild(a);
            });
            if (importAllBtn) importAllBtn.disabled = false;
        })
        .catch(error => {
            listGroup.innerHTML = `<div class="list-group-item text-danger">Error finding pools: ${error.message}</div>`;
            importSelectedBtn.disabled = true;
            const importAllBtn = document.getElementById('importModalConfirmAllButton');
            if (importAllBtn) importAllBtn.disabled = true;
        });
}

/**
 * Handle pool action (generic)
 */
export function handlePoolAction(actionName, requireConfirm = false, confirmMsg = null, extraArgs = [], extraKwargs = {}) {
    if (!state.currentSelection || state.currentSelection.obj_type !== 'pool') return;
    const poolName = state.currentSelection.name;
    executeActionWithRefresh(
        actionName,
        [poolName, ...extraArgs],
        extraKwargs,
        `Pool action '${actionName}' initiated for '${poolName}'.`,
        requireConfirm,
        confirmMsg || `Are you sure you want to perform '${actionName}' on pool '${poolName}'?`
    );
}
