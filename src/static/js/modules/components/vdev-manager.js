/**
 * vdev-manager.js - VDEV Configuration Manager Component
 * 
 * Reusable component for managing VDEV configuration in pool creation/editing modals.
 * Handles the device selection, VDEV tree, and all interactions between them.
 */

/**
 * Generate HTML for VDEV configuration modal
 * @param {Object} config - Configuration options
 * @param {string} config.poolNameInput - HTML for pool name input (optional, for Create Pool)
 * @param {string} config.forceCheckboxId - ID for force checkbox
 * @param {string} config.forceCheckboxLabel - Label for force checkbox
 * @param {string} config.vdevListLabel - Label for VDEV list ("VDEVs in Pool:" or "VDEVs to Add:")
 * @returns {string} - Generated HTML
 */
export function generateVdevModalHtml(config = {}) {
    const {
        poolNameInput = '',
        forceCheckboxId = 'pool-force-check',
        forceCheckboxLabel = 'Force (-f)',
        vdevListLabel = 'VDEVs in Pool:'
    } = config;

    const availableDevicesHtml = '<p class="text-muted">Loading available devices...</p>';

    return `
        ${poolNameInput}
        <div class="form-check mb-3">
            <input class="form-check-input" type="checkbox" value="" id="${forceCheckboxId}">
            <label class="form-check-label" for="${forceCheckboxId}">${forceCheckboxLabel}</label>
        </div>
        <hr>
        <h6>Pool Layout</h6>
        <div class="row align-items-center gx-2">
            <div class="col-md-5">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <label class="form-label mb-0 fw-bold">Available Devices:</label>
                    <div class="form-check form-check-sm mb-0">
                        <input class="form-check-input" type="checkbox" id="pool-show-all-devices-check">
                        <label class="form-check-label small" for="pool-show-all-devices-check">Show All</label>
                    </div>
                </div>
                <ul id="pool-available-devices" class="list-group list-group-flush border rounded shadow-sm custom-scrollbar" style="height: 400px; overflow-y: auto; overflow-x: hidden;">${availableDevicesHtml}</ul>
            </div>
            <div class="col-md-1 d-flex flex-column align-items-center justify-content-center" style="height: 400px;">
                <button type="button" id="pool-add-device-btn" class="btn btn-sm btn-outline-primary mb-3 shadow-sm" title="Add Selected Device(s) to VDEV">
                    <i class="bi bi-chevron-right"></i>
                </button>
                <button type="button" id="pool-remove-device-btn" class="btn btn-sm btn-outline-danger shadow-sm" title="Remove Selected Device/VDEV">
                    <i class="bi bi-chevron-left"></i>
                </button>
            </div>
            <div class="col-md-6">
                <label class="form-label fw-bold">${vdevListLabel}</label>
                <div id="pool-vdev-config" class="border rounded p-2 bg-light shadow-sm custom-scrollbar" style="height: 400px; overflow-y: auto; overflow-x: hidden;">
                    <div id="pool-vdev-empty-state"></div>
                    <ul class="list-unstyled mb-0" id="pool-vdev-list"></ul>
                </div>
                <div id="pool-vdev-type-info" class="alert alert-info small py-2 px-3 mt-2" style="display:none;"></div>
                <div class="input-group input-group-sm justify-content-end mt-2">
                    <select class="form-select form-select-sm shadow-sm" id="pool-vdev-type-select" style="max-width: 150px;">
                        ${VDEV_TYPES.map(t => `<option value="${t}">${t}</option>`).join('')}
                        <option value="custom">Custom...</option>
                    </select>
                    <button type="button" id="pool-add-vdev-btn" class="btn btn-sm btn-success shadow-sm"><i class="bi bi-plus-circle"></i> Add VDEV</button>
                </div>
            </div>
        </div>
    `;
}

import { apiCall } from '../api.js';
import { VDEV_TYPES } from '../constants.js';
import { showWarning } from '../notifications.js';
import { renderVdevTypeInfo, hideVdevTypeInfo, loadHelpStrings, renderEmptyState } from '../help.js';
import {
    addVdevTypeToPoolConfig,
    addDeviceToPoolVdev,
    removeDeviceFromPoolVdev,
    removeVdevFromPoolConfig,
    getSelectedPoolVdev,
    getSelectedPoolDeviceInVdev
} from '../pool-actions.js';

/**
 * Initialize VDEV manager for a modal
 * @param {Object} config - Configuration options
 * @param {string} config.emptyStateContext - Context for empty state rendering
 * @returns {Object} - Manager instance with public methods
 */
export function initializeVdevManager(config = {}) {
    const {
        emptyStateContext = 'create_pool_vdev_tree'
    } = config;

    const availableList = document.getElementById('pool-available-devices');
    const vdevList = document.getElementById('pool-vdev-list');
    const vdevTypeSelect = document.getElementById('pool-vdev-type-select');
    const vdevTypeInfoContainer = document.getElementById('pool-vdev-type-info');
    const showAllCheck = document.getElementById('pool-show-all-devices-check');

    // Store map on modal body
    const modalBody = document.getElementById('actionModalBody');
    if (!modalBody) {
        console.error("Modal body not found for map storage!");
        return null;
    }
    modalBody.modalAvailableDevicesMap = {};
    const availableDevicesMap = modalBody.modalAvailableDevicesMap;

    // Load help strings
    loadHelpStrings().catch(e => console.warn('Could not load help strings:', e));

    // VDEV type select change handler - show info
    if (vdevTypeSelect && vdevTypeInfoContainer) {
        vdevTypeSelect.addEventListener('change', () => {
            const type = vdevTypeSelect.value;
            if (type && type !== 'custom') {
                renderVdevTypeInfo(type, vdevTypeInfoContainer);
            } else {
                hideVdevTypeInfo(vdevTypeInfoContainer);
            }
        });
        // Show info for initial selection
        if (vdevTypeSelect.value && vdevTypeSelect.value !== 'custom') {
            renderVdevTypeInfo(vdevTypeSelect.value, vdevTypeInfoContainer);
        }
    }

    // Function to update empty state visibility
    function updateEmptyState() {
        const emptyState = document.getElementById('pool-vdev-empty-state');
        if (emptyState) {
            const hasItems = vdevList.children.length > 0;
            emptyState.style.display = hasItems ? 'none' : 'block';
            if (!hasItems) {
                renderEmptyState(emptyStateContext, emptyState);
            }
        }
    }

    // Initial render of empty state
    updateEmptyState();

    // Add event listeners
    document.getElementById('pool-add-vdev-btn')?.addEventListener('click', () => {
        const selectEl = document.getElementById('pool-vdev-type-select');
        const type = selectEl ? selectEl.value : null;
        addVdevTypeToPoolConfig(vdevList, type);
        updateEmptyState();
    });

    document.getElementById('pool-add-device-btn')?.addEventListener('click', () =>
        addDeviceToPoolVdev(availableList, vdevList, availableDevicesMap)
    );

    document.getElementById('pool-remove-device-btn')?.addEventListener('click', () => {
        const selectedVdev = getSelectedPoolVdev(vdevList);
        const selectedDevice = getSelectedPoolDeviceInVdev(vdevList);

        if (selectedDevice) {
            removeDeviceFromPoolVdev(availableList, vdevList, availableDevicesMap);
        } else if (selectedVdev) {
            removeVdevFromPoolConfig(selectedVdev, availableList, availableDevicesMap);
            updateEmptyState(); // Ensure empty state is checked after VDEV removal
        } else {
            showWarning("Please select a VDEV or a device within a VDEV to remove.");
        }
    });

    // Helper to render devices
    function renderAvailableDevices() {
        const showAll = showAllCheck ? showAllCheck.checked : false;
        const sourceDevices = showAll ? (modalBody.allDevices || []) : (modalBody.safeDevices || []);

        // Filter out devices already in the vdev config
        const usedPaths = new Set();
        vdevList.querySelectorAll('.pool-vdev-device-item').forEach(li => {
            usedPaths.add(li.dataset.path);
        });

        availableList.innerHTML = '';

        if (sourceDevices.length === 0) {
            availableList.innerHTML = '<li class="list-group-item text-muted">No devices found.</li>';
            return;
        }

        const filteredDevices = sourceDevices.filter(d => !usedPaths.has(d.name));

        if (filteredDevices.length === 0) {
            availableList.innerHTML = '<li class="list-group-item text-muted">No suitable devices available.</li>';
            return;
        }

        filteredDevices.forEach(dev => {
            // Update map just in case
            availableDevicesMap[dev.name] = dev;

            const li = document.createElement('li');
            li.className = 'list-group-item list-group-item-action pool-device-item';
            const displayName = dev.display_name || dev.name;
            // Use inline escaping for now (imported function from pool-actions.js)
            const escapedName = escapeHtml(displayName);
            li.innerHTML = `<i class="bi bi-hdd me-2 opacity-50"></i><span>${escapedName}</span>`;
            li.dataset.path = dev.name;
            li.onclick = (e) => e.currentTarget.classList.toggle('active');
            availableList.appendChild(li);
        });

        // Sort
        const items = Array.from(availableList.children);
        items.sort((a, b) => a.textContent.localeCompare(b.textContent));
        availableList.innerHTML = '';
        items.forEach(item => availableList.appendChild(item));
    }

    // Checkbox listener
    if (showAllCheck) {
        showAllCheck.addEventListener('change', () => renderAvailableDevices());
    }

    // Fetch available devices
    apiCall('/api/block_devices')
        .then(result => {
            availableList.innerHTML = '';
            if (result.data?.error) {
                availableList.innerHTML = `<li class="list-group-item text-danger">Error: ${result.data.error}</li>`;
                return;
            }

            // Store both lists
            modalBody.safeDevices = result.data?.devices || [];
            modalBody.allDevices = result.data?.all_devices || [];

            // Initial population of the map (using all devices so lookups work)
            (modalBody.allDevices).forEach(dev => {
                availableDevicesMap[dev.name] = dev;
            });

            // Initial Render
            renderAvailableDevices();
        })
        .catch(error => {
            availableList.innerHTML = `<li class="list-group-item text-danger">Error loading devices: ${error.message}</li>`;
        });

    // Public API
    return {
        updateEmptyState,
        renderAvailableDevices
    };
}

/**
 * Helper to escape HTML
 */
function escapeHtml(text) {
    if (!text) return text;
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
