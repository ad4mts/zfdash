/**
 * details.js - Details Panel Module
 * 
 * Handles rendering the details panel when an item is selected.
 */

import * as state from './state.js';
import { apiCall } from './api.js';
import dom from './dom-elements.js';
import { renderDashboard } from './dashboard.js';
import { renderProperties } from './property-editor.js';
import { renderSnapshots } from './snapshots.js';
import { renderPoolStatus, renderPoolEditLayout, updatePoolEditActionStates } from './pool-status.js';
import { renderEncryptionInfo } from './encryption.js';

/**
 * Render details panel for selected object
 */
export async function renderDetails(obj) {
    if (!obj) {
        // If called with null obj after showing content, clear title and potentially show placeholder again
        if (dom.detailsTitle) dom.detailsTitle.textContent = 'Details';
        
        // Hide the tab content area
        if (dom.detailsTabContent) {
            dom.detailsTabContent.style.visibility = 'hidden';
            dom.detailsTabContent.style.opacity = '0';
        } else {
            console.warn("renderDetails: detailsTabContent element not found when clearing!");
        }
        
        // Clear dashboard
        renderDashboard(null);
        console.warn("renderDetails called with null object.");
        return;
    }

    // We have an object, set title first
    if (dom.detailsTitle) {
        dom.detailsTitle.textContent = `${obj.obj_type.charAt(0).toUpperCase() + obj.obj_type.slice(1)}: ${obj.name}`;
    }

    // Show the tab content area
    if (dom.detailsTabContent) {
        dom.detailsTabContent.style.visibility = 'visible';
        dom.detailsTabContent.style.opacity = '1';
    } else {
        console.warn("renderDetails: detailsTabContent element not found when showing content!");
    }

    // --- Tab Enabling/Disabling ---
    const isPool = obj.obj_type === 'pool';
    const isDataset = obj.obj_type === 'dataset';
    const isVolume = obj.obj_type === 'volume';
    const isDatasetOrVol = isDataset || isVolume;
    const isEncrypted = obj.is_encrypted;

    // Dashboard is always enabled
    const dashboardTabButton = document.getElementById('dashboard-tab-button');
    if (dashboardTabButton) dashboardTabButton.disabled = false;

    // Always enable properties tab if an object is selected
    document.getElementById('properties-tab-button').disabled = false;

    // Enable/disable other tabs based on type
    document.getElementById('snapshots-tab-button').disabled = !isDatasetOrVol;
    document.getElementById('pool-status-tab-button').disabled = !isPool;
    document.getElementById('pool-edit-tab-button').disabled = !isPool;
    document.getElementById('encryption-tab-button').disabled = !isEncrypted;

    // --- Clear/Populate Tab Content ---
    // Render dashboard first (always available)
    renderDashboard(obj);

    // Properties (handled below by fetching)
    renderProperties(null, true); // Show loading state

    // Snapshots
    if (isDatasetOrVol) {
        renderSnapshots(obj.snapshots || []);
    } else {
        renderSnapshots([]);
    }

    // Pool Status
    if (isPool) {
        state.setCurrentPoolStatusText(obj.status_details || '');
        renderPoolStatus(state.currentPoolStatusText);
    } else {
        renderPoolStatus('');
    }

    // Pool Edit Layout
    if (isPool) {
        renderPoolEditLayout(state.currentPoolStatusText);
    } else {
        renderPoolEditLayout('');
    }

    // Encryption Info
    const encTabButton = document.getElementById('encryption-tab-button');
    if (isEncrypted && encTabButton && !encTabButton.disabled) {
        renderEncryptionInfo(obj);
    } else {
        renderEncryptionInfo(null, true);
    }

    // --- Fetch and render properties ---
    try {
        const propsResult = await apiCall(`/api/properties/${encodeURIComponent(obj.name)}`);
        state.setCurrentProperties(propsResult.data);
        renderProperties(state.currentProperties);
    } catch (error) {
        console.error("Failed to fetch properties:", error);
        state.setCurrentProperties(null);
        if (dom.propertiesTableBody) {
            dom.propertiesTableBody.innerHTML = `<tr><td colspan="4" class="text-danger text-center">Failed to load properties: ${error.message}</td></tr>`;
        }
    }
}

/**
 * Update action button states based on current selection
 */
export function updateActionStates() {
    const obj = state.currentSelection;
    const isPool = obj?.obj_type === 'pool';
    const isDataset = obj?.obj_type === 'dataset';
    const isVolume = obj?.obj_type === 'volume';
    const isFilesystem = isDataset || isVolume;
    const props = obj?.properties || {};
    const isClone = isFilesystem && props.origin && props.origin !== '-';
    // Use the specific 'is_mounted' boolean field from the backend data if available, fallback to property otherwise
    const isMounted = (obj && typeof obj.is_mounted === 'boolean') ? obj.is_mounted : (props.mounted === 'yes');

    // --- Pool Actions ---
    document.getElementById('create-pool-button')?.classList.remove('disabled');
    document.getElementById('import-pool-button')?.classList.remove('disabled');

    document.getElementById('destroy-pool-button')?.classList.toggle('disabled', !isPool);
    document.getElementById('export-pool-button')?.classList.toggle('disabled', !isPool);
    // Scrub buttons depend on pool selection AND scrub status (potentially parsed later)
    document.getElementById('scrub-start-button')?.classList.toggle('disabled', !isPool);
    document.getElementById('scrub-stop-button')?.classList.toggle('disabled', !isPool);
    document.getElementById('clear-errors-button')?.classList.toggle('disabled', !isPool);

    // --- Dataset Actions ---
    const canCreateDataset = isPool || isFilesystem;
    document.getElementById('create-dataset-button')?.classList.toggle('disabled', !canCreateDataset);

    document.getElementById('destroy-dataset-button')?.classList.toggle('disabled', !isFilesystem);
    document.getElementById('rename-dataset-button')?.classList.toggle('disabled', !isFilesystem);

    // Mount/Unmount Logic (Relies on isDataset being correct)
    const canMount = isDataset && !isMounted;
    document.getElementById('mount-dataset-button')?.classList.toggle('disabled', !canMount);

    const canUnmount = isDataset && isMounted;
    document.getElementById('unmount-dataset-button')?.classList.toggle('disabled', !canUnmount);

    document.getElementById('promote-dataset-button')?.classList.toggle('disabled', !isClone);

    // --- Snapshot Actions (controlled within snapshot tab rendering) ---

    // --- Encryption Actions ---
    const encTabButton = document.getElementById('encryption-tab-button');
    // Check if obj exists before accessing properties for encryption check
    if (encTabButton && !encTabButton.disabled && obj && obj.is_encrypted) {
        renderEncryptionInfo(obj);
    } else if (encTabButton && !encTabButton.disabled && obj && !obj.is_encrypted) {
        // If dataset not encrypted, disable all buttons
        document.getElementById('load-key-button').disabled = true;
        document.getElementById('unload-key-button').disabled = true;
        document.getElementById('change-key-button').disabled = true;
        document.getElementById('change-key-location-button').disabled = true;
    } else if (encTabButton && !encTabButton.disabled && !obj) {
        // If the tab is somehow enabled but no object is selected, disable buttons
        document.getElementById('load-key-button').disabled = true;
        document.getElementById('unload-key-button').disabled = true;
        document.getElementById('change-key-button').disabled = true;
        document.getElementById('change-key-location-button').disabled = true;
    }

    // Pool Edit actions (controlled by updatePoolEditActionStates)
    const selectedEditItem = dom.poolEditTreeContainer?.querySelector('.selected');
    updatePoolEditActionStates(selectedEditItem);

    // Check pool status for scrub state more accurately if status text is available
    if (isPool && state.currentPoolStatusText) {
        const scrubRunning = state.currentPoolStatusText.includes('scrub in progress') || state.currentPoolStatusText.includes('resilver in progress');
        document.getElementById('scrub-start-button')?.classList.toggle('disabled', !isPool || scrubRunning);
        document.getElementById('scrub-stop-button')?.classList.toggle('disabled', !isPool || !scrubRunning);
    } else if (isPool) {
        // If pool but no status text, disable scrub stop button defensively
        document.getElementById('scrub-stop-button')?.classList.add('disabled');
    }
}
