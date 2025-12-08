/**
 * pool-edit-actions.js - Pool Edit Actions Module
 * 
 * Handles pool editing operations like adding VDEVs to existing pools.
 */

import * as state from './state.js';
import { apiCall, executeActionWithRefresh } from './api.js';
import { showModal, hideModal, showErrorAlert } from './ui.js';

// Import helper functions from pool-actions
import { 
    addVdevTypeToPoolConfig,
    addDeviceToPoolVdev,
    removeDeviceFromPoolVdev,
    removeVdevFromPoolConfig,
    getSelectedPoolVdev,
    getSelectedPoolDeviceInVdev
} from './pool-actions.js';

/**
 * Handle pool edit action (switch-based routing)
 */
export function handlePoolEditAction(action, selectedLi) {
    if (!state.currentSelection || state.currentSelection.obj_type !== 'pool') {
        alert("Pool Edit Action Error: No pool selected.");
        return;
    }
    if (!selectedLi && action !== 'add_vdev') {
        alert("Pool Edit Action Error: No item selected in the pool layout for this action.");
        return;
    }

    const poolName = state.currentSelection.name;
    const devicePath = selectedLi?.dataset.devicePath;
    const vdevId = selectedLi?.dataset.name;
    const vdevType = selectedLi?.dataset.vdevType;

    switch(action) {
        case 'attach':
            if (!devicePath) { 
                alert("Select the specific device or disk VDEV to attach to."); 
                return; 
            }
            promptAndExecuteDeviceSelect(
                "Select Device to Attach",
                `Select device to attach as mirror to:\n${devicePath}`,
                (newDevice) => {
                    executeActionWithRefresh('attach_device', [poolName, devicePath, newDevice], {},
                        `Attach initiated for ${newDevice} to ${devicePath}.`, true,
                        `Attach '${newDevice}' as mirror to '${devicePath}' in pool '${poolName}'?`);
                }
            );
            break;
            
        case 'detach':
            if (!devicePath) { 
                alert("Select the device within a mirror to detach."); 
                return; 
            }
            const parentLi = selectedLi?.parentElement?.closest('li.pool-edit-item');
            if (parentLi?.dataset.vdevType !== 'mirror') {
                alert("Detach is only possible for devices within a mirror."); 
                return;
            }
            executeActionWithRefresh('detach_device', [poolName, devicePath], {},
                `Detach initiated for ${devicePath}.`, true,
                `Detach device '${devicePath}' from its mirror in pool '${poolName}'?`);
            break;
            
        case 'replace':
            if (!devicePath) { 
                alert("Select the specific device or disk VDEV to replace."); 
                return; 
            }
            promptAndExecuteDeviceSelect(
                "Select Replacement Device",
                `Select NEW device to replace:\n${devicePath}\n(Choose 'Mark Only' to replace later)`,
                (newDevice) => {
                    const isMarkOnly = newDevice === "";
                    executeActionWithRefresh('replace_device', [poolName, devicePath, newDevice], {},
                        `Replacement initiated for ${devicePath}.`, true,
                        `Replace device '${devicePath}' ${isMarkOnly ? '(mark only)' : `with '${newDevice}'`} in pool '${poolName}'?`);
                },
                true
            );
            break;
            
        case 'offline':
            if (!devicePath) { 
                alert("Select the specific device or disk VDEV to take offline."); 
                return; 
            }
            const temporary = confirm(`Take device '${devicePath}' offline temporarily?\n(May come back online after reboot)`);
            executeActionWithRefresh('offline_device', [poolName, devicePath, temporary], {},
                `Offline initiated for ${devicePath}.`, true,
                `Take device '${devicePath}' offline ${temporary ? '(temporarily)' : ''} in pool '${poolName}'?`);
            break;
            
        case 'online':
            if (!devicePath) { 
                alert("Select the specific device or disk VDEV to bring online."); 
                return; 
            }
            const expand = confirm(`Attempt to expand capacity if '${devicePath}' is larger than original?`);
            executeActionWithRefresh('online_device', [poolName, devicePath, expand], {},
                `Online initiated for ${devicePath}.`, true,
                `Bring device '${devicePath}' online ${expand ? 'and expand ' : ''}in pool '${poolName}'?`);
            break;
            
        case 'remove_vdev':
            if (!vdevId) { 
                alert("Could not identify VDEV to remove."); 
                return; 
            }
            let idToRemove = vdevId;
            if (['log', 'cache', 'spare'].includes(vdevType)) {
                const firstDeviceLi = selectedLi.querySelector(':scope > ul.pool-edit-children > li[data-item-type="device"]');
                if (firstDeviceLi && firstDeviceLi.dataset.devicePath) {
                    idToRemove = firstDeviceLi.dataset.devicePath;
                } else {
                    idToRemove = selectedLi.dataset.name;
                    console.warn(`Could not find child device path for special VDEV '${vdevId}', attempting removal using name '${idToRemove}'`);
                }
            } else if (vdevType === 'disk' && devicePath) {
                idToRemove = devicePath;
            }
            executeActionWithRefresh('remove_vdev', [poolName, idToRemove], {},
                `Removal initiated for ${idToRemove}.`, true,
                `WARNING: Removing VDEVs can be dangerous!\nAre you sure you want to attempt remove '${idToRemove}' from pool '${poolName}'?`);
            break;
            
        case 'split':
            if (selectedLi?.dataset.itemType !== 'pool') {
                alert("Select the top-level pool item in the 'Edit Pool' tab to initiate split."); 
                return;
            }
            const newPoolName = prompt(`Enter name for the new pool created by splitting '${poolName}':`);
            if (newPoolName === null) return;
            const newName = newPoolName.trim();
            if (!newName || newName === poolName || !/^[a-zA-Z][a-zA-Z0-9_\-:.%]*$/.test(newName) || 
                ['log', 'spare', 'cache', 'mirror', 'raidz', 'raidz1', 'raidz2', 'raidz3', 'replacing', 'initializing'].includes(newName.toLowerCase())) {
                alert("Invalid or reserved new pool name."); 
                return;
            }
            executeActionWithRefresh('split_pool', [poolName, newName, {}], {},
                `Split initiated for ${poolName} into ${newName}.`, true,
                `Split pool '${poolName}' into new pool '${newName}'?\n(Detaches second device of each top-level mirror)`);
            break;
            
        case 'add_vdev':
            handleAddVdevDialog();
            break;
            
        default:
            console.warn("Unknown pool edit action:", action);
    }
}

/**
 * Handle Add VDEV dialog - uses the same UI as Create Pool
 */
export function handleAddVdevDialog() {
    if (!state.currentSelection || state.currentSelection.obj_type !== 'pool') {
        alert("No pool selected for adding VDEV.");
        return;
    }
    
    const poolName = state.currentSelection.name;
    
    let availableDevicesHtml = '<p class="text-muted">Loading available devices...</p>';
    let modalHtml = `
        <h6>Add VDEVs to Pool '${poolName}'</h6>
        <div class="form-check mb-3">
            <input class="form-check-input" type="checkbox" value="" id="pool-force-add-check">
            <label class="form-check-label" for="pool-force-add-check">Force Addition (-f)</label>
        </div>
        <hr>
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
                <label class="form-label">VDEVs to Add:</label>
                <div id="pool-vdev-config" class="border rounded p-1 bg-light" style="min-height: 150px;">
                    <ul class="list-unstyled mb-0" id="pool-vdev-list"></ul>
                </div>
                <div class="text-end mt-1">
                    <button type="button" id="pool-add-vdev-btn" class="btn btn-sm btn-success"><i class="bi bi-plus-circle"></i> Add VDEV Type</button>
                </div>
            </div>
        </div>
    `;

    showModal(`Add VDEVs to Pool '${poolName}'`, modalHtml, handleAddVdevConfirm, { size: 'xl', setupFunc: setupAddVdevModal });
}

/**
 * Setup add VDEV modal - reuses the pool creation UI setup logic
 */
function setupAddVdevModal() {
    const availableList = document.getElementById('pool-available-devices');
    const vdevList = document.getElementById('pool-vdev-list');
    
    // Store map on modal body
    const modalBody = document.getElementById('actionModalBody');
    if (!modalBody) {
        console.error("Modal body not found for map storage!");
        return;
    }
    modalBody.modalAvailableDevicesMap = {};
    const availableDevicesMap = modalBody.modalAvailableDevicesMap;

    // Add event listeners for buttons inside the modal
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

    // Fetch and populate available devices
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
 * Handle add VDEV confirmation
 */
function handleAddVdevConfirm() {
    if (!state.currentSelection || state.currentSelection.obj_type !== 'pool') {
        console.error("handleAddVdevConfirm called without a pool selected.");
        return;
    }
    
    const poolName = state.currentSelection.name;
    const forceAdd = document.getElementById('pool-force-add-check').checked;

    const vdevSpecs = [];
    const vdevItems = document.querySelectorAll('#pool-vdev-list > .pool-vdev-item');
    
    if (vdevItems.length === 0) {
        alert("No VDEVs defined to add.");
        return;
    }

    let layoutValid = true;
    const minDevicesMap = { 'mirror': 2, 'raidz1': 3, 'raidz2': 4, 'raidz3': 5 };
    
    vdevItems.forEach(vdevLi => {
        const vdevType = vdevLi.dataset.vdevType;
        const devices = [];
        vdevLi.querySelectorAll('.pool-vdev-device-item').forEach(devLi => {
            devices.push(devLi.dataset.path);
        });
        
        const minDevices = minDevicesMap[vdevType] || 1;
        if (devices.length < minDevices) {
            alert(`VDEV type '${vdevType}' requires at least ${minDevices} device(s), found ${devices.length}.`);
            layoutValid = false;
            return;
        }
        
        vdevSpecs.push({ type: vdevType, devices: devices });
    });

    if (!layoutValid) return;

    hideModal();
    executeActionWithRefresh(
        'add_vdev',
        [],
        { pool_name: poolName, vdev_specs: vdevSpecs, force: forceAdd },
        `Adding VDEVs to pool '${poolName}' initiated.`
    );
}

/**
 * Prompt and execute device selection for pool operations
 * @param {string} title - Modal title
 * @param {string} message - Message to display
 * @param {Function} onConfirm - Callback when device selected
 * @param {boolean} allowMarkOnly - Whether to allow "mark only" option
 */
function promptAndExecuteDeviceSelect(title, message, onConfirm, allowMarkOnly = false) {
    let modalHtml = `<p>${message}</p><select id="device-select-input" class="form-select"><option value="" disabled selected>Loading devices...</option>`;
    if (allowMarkOnly) {
        modalHtml += `<option value="">&lt;Mark for replacement only&gt;</option>`;
    }
    modalHtml += `</select>`;

    showModal(title, modalHtml,
        () => {
            const selectedValue = document.getElementById('device-select-input').value;
            if (selectedValue === "" && !allowMarkOnly) {
                alert("Please select a device.");
                return;
            }
            if (selectedValue === null) return;

            hideModal();
            onConfirm(selectedValue);
        },
        {
            setupFunc: () => {
                const selectEl = document.getElementById('device-select-input');
                apiCall('/api/block_devices')
                    .then(result => {
                        selectEl.options.length = allowMarkOnly ? 2 : 1;
                        const devices = result.data?.devices || [];
                        if (devices.length > 0) {
                            devices.forEach(dev => {
                                selectEl.add(new Option(dev.display_name || dev.name, dev.name));
                            });
                            selectEl.options[0].textContent = "Select a device...";
                            selectEl.options[0].disabled = true;
                            if (!allowMarkOnly) selectEl.selectedIndex = 0;
                        } else {
                            selectEl.options[0].textContent = "No available devices found";
                            selectEl.options[0].disabled = true;
                        }
                    })
                    .catch(err => {
                        selectEl.options[0].textContent = "Error loading devices";
                        selectEl.options[0].disabled = true;
                        console.error("Device load error:", err);
                    });
            }
        }
    );
}
