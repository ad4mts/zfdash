/**
 * pool-edit-actions.js - Pool Edit Actions Module
 * 
 * Handles pool editing operations like adding VDEVs to existing pools.
 */

import * as state from './state.js';
import { apiCall, executeActionWithRefresh } from './api.js';
import { showModal, hideModal, showErrorAlert, showConfirmModal, showTripleChoiceModal, showInputModal } from './ui.js';
import { VDEV_TYPES } from './constants.js';
import { showError, showSuccess, showWarning } from './notifications.js';
import { renderVdevTypeInfo, hideVdevTypeInfo, loadHelpStrings, renderEmptyState } from './help.js';
import { initializeVdevManager, generateVdevModalHtml } from './components/vdev-manager.js';

// Import helper functions from pool-actions
import {
    addVdevTypeToPoolConfig,
    addDeviceToPoolVdev,
    removeDeviceFromPoolVdev,
    removeVdevFromPoolConfig,
    getSelectedPoolVdev,
    getSelectedPoolDeviceInVdev,
    escapeHtml
} from './pool-actions.js';

/**
 * Handle pool edit action (switch-based routing)
 */
export async function handlePoolEditAction(action, selectedLi) {
    if (!state.currentSelection || state.currentSelection.obj_type !== 'pool') {
        showError("Pool Edit Action Error: No pool selected.");
        return;
    }
    if (!selectedLi && action !== 'add_vdev') {
        showWarning("Pool Edit Action Error: No item selected in the pool layout for this action.");
        return;
    }

    const poolName = state.currentSelection.name;
    const devicePath = selectedLi?.dataset.devicePath;
    const vdevId = selectedLi?.dataset.name;
    const vdevType = selectedLi?.dataset.vdevType;

    switch (action) {
        case 'attach':
            if (!devicePath) {
                showWarning("Select the specific device or disk VDEV to attach to.");
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
                showWarning("Select the device within a mirror to detach.");
                return;
            }
            const parentLi = selectedLi?.parentElement?.closest('li.pool-edit-item');
            if (parentLi?.dataset.vdevType !== 'mirror') {
                showWarning("Detach is only possible for devices within a mirror.");
                return;
            }
            executeActionWithRefresh('detach_device', [poolName, devicePath], {},
                `Detach initiated for ${devicePath}.`, true,
                `Detach device '${devicePath}' from its mirror in pool '${poolName}'?`);
            break;

        case 'replace':
            if (!devicePath) {
                showWarning("Select the specific device or disk VDEV to replace.");
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

        case 'offline': {
            if (!devicePath) {
                showWarning("Select the specific device or disk VDEV to take offline.");
                return;
            }
            // Three-choice modal: Temporarily / Permanently / Cancel
            const choice = await showTripleChoiceModal(
                "Offline Device",
                `Take device '<strong>${devicePath}</strong>' offline in pool '<strong>${poolName}</strong>'?<br><br>
                <strong>Temporarily</strong> = May come back online after reboot<br>
                <strong>Permanently</strong> = Stays offline until manually brought online`,
                "Temporarily", "btn-warning",
                "Permanently", "btn-danger"
            );
            if (choice === null) {
                return; // User cancelled
            }
            const temporary = (choice === 'optionA'); // optionA = Temporarily
            executeActionWithRefresh('offline_device', [poolName, devicePath, temporary], {},
                `Offline initiated for ${devicePath} (${temporary ? 'temporary' : 'permanent'}).`, false);
            break;
        }

        case 'online': {
            if (!devicePath) {
                showWarning("Select the specific device or disk VDEV to bring online.");
                return;
            }
            // Three-choice modal: Expand / Don't Expand / Cancel
            const choice = await showTripleChoiceModal(
                "Online Device",
                `Bring device '<strong>${devicePath}</strong>' online in pool '<strong>${poolName}</strong>'?<br><br>
                <strong>Expand</strong> = Attempt to expand pool capacity if device is larger<br>
                <strong>Don't Expand</strong> = Just bring online without expansion`,
                "Yes, Expand", "btn-success",
                "Don't Expand", "btn-primary"
            );
            if (choice === null) {
                return; // User cancelled
            }
            const expand = (choice === 'optionA'); // optionA = Expand
            executeActionWithRefresh('online_device', [poolName, devicePath, expand], {},
                `Online initiated for ${devicePath}${expand ? ' (with expansion)' : ''}.`, false);
            break;
        }

        case 'remove_vdev':
            if (!vdevId) {
                showError("Could not identify VDEV to remove.");
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

        case 'split': {
            if (selectedLi?.dataset.itemType !== 'pool') {
                showWarning("Select the top-level pool item in the 'Edit Pool' tab to initiate split.");
                return;
            }
            const newPoolName = await showInputModal(
                "Split Pool",
                `Enter name for the new pool created by splitting '<strong>${poolName}</strong>':`,
                "",
                "new-pool-name",
                "Split", "btn-warning"
            );
            if (newPoolName === null) return;
            const newName = newPoolName.trim();
            if (!newName || newName === poolName || !/^[a-zA-Z][a-zA-Z0-9_\-:.%]*$/.test(newName) ||
                ['log', 'spare', 'cache', 'mirror', 'raidz', 'raidz1', 'raidz2', 'raidz3', 'replacing', 'initializing'].includes(newName.toLowerCase())) {
                showError("Invalid or reserved new pool name.");
                return;
            }
            executeActionWithRefresh('split_pool', [poolName, newName, {}], {},
                `Split initiated for ${poolName} into ${newName}.`, true,
                `Split pool '${poolName}' into new pool '${newName}'?<br>(Detaches second device of each top-level mirror)`);
            break;
        }
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
        showError("No pool selected for adding VDEV.");
        return;
    }

    const poolName = state.currentSelection.name;

    const poolHeader = `<h6>Add VDEVs to Pool '${poolName}'</h6>`;

    const modalHtml = poolHeader + generateVdevModalHtml({
        poolNameInput: '', // No pool name input for Add VDEV
        forceCheckboxId: 'pool-force-add-check',
        forceCheckboxLabel: 'Force Addition (-f)',
        vdevListLabel: 'VDEVs to Add:'
    });

    showModal(`Add VDEVs to Pool '${poolName}'`, modalHtml, handleAddVdevConfirm, { size: 'xl', setupFunc: setupAddVdevModal });
}

/**
 * Setup add VDEV modal - reuses the pool creation UI setup logic
 */
function setupAddVdevModal() {
    // Initialize VDEV manager with add vdev context
    initializeVdevManager({
        emptyStateContext: 'add_vdev_modal'
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
        showWarning("No VDEVs defined to add.");
        return;
    }

    let layoutValid = true;
    const minDevicesMap = { 'mirror': 2, 'raidz1': 3, 'raidz2': 4, 'raidz3': 5, 'special mirror': 2, 'dedup mirror': 2 };

    vdevItems.forEach(vdevLi => {
        const vdevType = vdevLi.dataset.vdevType;
        const devices = [];
        vdevLi.querySelectorAll('.pool-vdev-device-item').forEach(devLi => {
            devices.push(devLi.dataset.path);
        });

        const minDevices = minDevicesMap[vdevType] || 1;
        if (devices.length < minDevices) {
            showError(`VDEV type '${vdevType}' requires at least ${minDevices} device(s), found ${devices.length}.`);
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
    modalHtml += `
    <div class="form-check mt-2">
        <input class="form-check-input" type="checkbox" id="device-select-show-all">
        <label class="form-check-label small" for="device-select-show-all">Show All Devices</label>
    </div>`;

    showModal(title, modalHtml,
        () => {
            const selectedValue = document.getElementById('device-select-input').value;
            if (selectedValue === "" && !allowMarkOnly) {
                showWarning("Please select a device.");
                return;
            }
            if (selectedValue === null) return;

            hideModal();
            onConfirm(selectedValue);
        },
        {
            setupFunc: () => {
                const selectEl = document.getElementById('device-select-input');
                const showAllCheck = document.getElementById('device-select-show-all');

                let safeDevices = [];
                let allDevices = [];

                function populateSelect() {
                    // Save current selection if possible
                    const currentVal = selectEl.value;

                    // Clear options (keep first "Select..." or "Mark Only" depending on impl, but simplest is rebuild)
                    selectEl.innerHTML = '';

                    if (allowMarkOnly) {
                        selectEl.add(new Option("<Mark for replacement only>", ""));
                    } else {
                        const defaultOpt = new Option("Select a device...", "");
                        defaultOpt.disabled = true;
                        defaultOpt.selected = true;
                        selectEl.add(defaultOpt);
                    }

                    const showAll = showAllCheck.checked;
                    const devices = showAll ? allDevices : safeDevices;

                    if (devices.length > 0) {
                        devices.forEach(dev => {
                            selectEl.add(new Option(dev.display_name || dev.name, dev.name));
                        });
                        // Restore selection if it still exists in the list
                        if (currentVal && Array.from(selectEl.options).some(o => o.value === currentVal)) {
                            selectEl.value = currentVal;
                        } else if (!allowMarkOnly) {
                            selectEl.selectedIndex = 0;
                        }
                    } else {
                        const opt = new Option("No available devices found", "");
                        opt.disabled = true;
                        selectEl.add(opt);
                    }
                }

                if (showAllCheck) {
                    showAllCheck.addEventListener('change', populateSelect);
                }

                apiCall('/api/block_devices')
                    .then(result => {
                        safeDevices = result.data?.devices || [];
                        allDevices = result.data?.all_devices || [];
                        populateSelect();
                    })
                    .catch(err => {
                        selectEl.innerHTML = '<option disabled>Error loading devices</option>';
                        console.error("Device load error:", err);
                    });
            }
        }
    );
}
