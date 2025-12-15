/**
 * app.js - Main Application Entry Point
 * 
 * ZfDash Web UI - Main application module that imports and initializes all components.
 * This is the entry point for the modular JavaScript application.
 * 
 * ES6 MODULE ARCHITECTURE NOTES
 * =============================
 * 
 * Key Patterns Used:
 * 
 * 1. DOM Elements (dom-elements.js):
 *    - Uses a mutable object container pattern
 *    - initDomElements() MUST be called after DOMContentLoaded
 *    - Access via: dom.zfsTree, dom.loginForm, etc.
 * 
 * 2. State Management (state.js):
 *    - Read state directly: state.currentSelection
 *    - Modify state via setters: state.setCurrentSelection(value)
 *    - Direct assignment will throw "read only property" error
 * 
 * 3. Callback Registration:
 *    - setTreeCallbacks() - for tree.js to call renderDetails, etc.
 *    - setAuthCallbacks() - for auth.js to call fetchAndRenderData after login
 *    - setFetchAndRenderDataRef() - for api.js to trigger data refresh
 *    - These are needed because ES6 modules resolve imports at load time,
 *      before functions are available. Callbacks allow late binding.
 * 
 * 4. Module Loading Order:
 *    - ES6 modules execute immediately when imported
 *    - DOMContentLoaded ensures DOM is ready before accessing elements
 *    - Callback setup ensures inter-module communication works
 */

// Import modules
import {
    EDITABLE_PROPERTIES_WEB,
    POOL_LEVEL_PROPERTIES,
    AUTO_SNAPSHOT_PROPS,
    AUTO_SNAPSHOT_SORT_ORDER_WEB,
    initializeAutoSnapshotProperties
} from './constants.js';

import * as state from './state.js';

import { apiCall, executeActionWithRefresh, setFetchAndRenderDataRef } from './api.js';

import { formatSize, findObjectByPath, validateSizeOrNone } from './utils.js';

// Import DOM elements container and initialization function
// Note: Use default import 'dom' to get the mutable object
import dom, { initDomElements } from './dom-elements.js';

import { setLoadingState, updateStatus, showModal, hideModal, showErrorAlert, showConfirmModal, showTripleChoiceModal, showDaemonDisconnectedOverlay, hideDaemonDisconnectedOverlay, updateDaemonDisconnectedMessage } from './ui.js';
import { showInfo, showSuccess, showError, showWarning } from './notifications.js';

// Health check state (for socket mode daemon disconnection detection)
let healthCheckInterval = null;
let healthCheckActive = false;
let daemonDisconnected = false;  // Tracks if daemon is currently disconnected
let reconnectInterval = null;  // Auto-reconnect interval

/**
 * Check if fetch response indicates auth failure (session expired).
 * If so, redirects to login and returns true. Otherwise returns false.
 */
function isAuthFailure(response) {
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json') || response.status === 401 || response.status === 403) {
        console.log('Session expired, redirecting to login');
        window.location.href = '/login';
        return true;
    }
    return false;
}

/**
 * Start health check polling (only for socket mode).
 * Polls /api/health every 5 seconds to detect daemon disconnection.
 * Also runs one check immediately on start.
 */
function startHealthCheck() {
    if (healthCheckInterval || healthCheckActive) return;
    healthCheckActive = true;

    healthCheckInterval = setInterval(doHealthCheck, 1000);  // Check every 1 second
    console.log('Health check polling started');
}

/**
 * The health check logic - checks daemon connection status.
 * Returns true if healthy, false if disconnected.
 */
async function doHealthCheck() {
    try {
        const response = await fetch('/api/health');
        if (isAuthFailure(response)) return false;  // Session expired, redirecting

        if (!response.ok) {
            // Server error - might be temporary
            console.warn('Health check failed with status:', response.status);
            return true;  // Treat as healthy, let data fetch handle it
        }

        const data = await response.json();

        // Only show overlay if not in pipe mode (owns_daemon=false) when unhealthy
        if (!data.healthy && !data.owns_daemon) {
            daemonDisconnected = true;
            stopHealthCheck();
            showDaemonDisconnectedOverlay(data.message || 'Daemon connection lost', handleReconnect);
            startAutoReconnect();  // Start auto-reconnect loop
            return false;
        }
        return true;
    } catch (error) {
        // Network error - could be server down or daemon issue
        // Don't set daemonDisconnected here since we can't determine if it's pipe mode
        // (in pipe mode, network errors mean the whole app is down anyway)
        console.error('Health check error:', error);
        stopHealthCheck();

        // Differentiate network error (WebUI server unreachable) from other errors
        if (error.name === 'TypeError' || (error.message && error.message.includes('Failed to fetch'))) {
            showDaemonDisconnectedOverlay(
                'Cannot reach ZfDash Web Interface.\nThe application server may have stopped.',
                handleReconnect,
                { title: 'Connection Lost', showDaemonHelp: false }
            );
        } else {
            showDaemonDisconnectedOverlay('Cannot connect to server. The daemon may have stopped.', handleReconnect);
        }

        startAutoReconnect();  // Start auto-reconnect loop
        return false;
    }
}

/**
 * Stop health check polling.
 */
function stopHealthCheck() {
    if (healthCheckInterval) {
        clearInterval(healthCheckInterval);
        healthCheckInterval = null;
    }
    healthCheckActive = false;
}

/**
 * Start auto-reconnect loop (tries every 1 second).
 */
function startAutoReconnect() {
    if (reconnectInterval) return;  // Already running

    reconnectInterval = setInterval(async () => {
        try {
            const response = await fetch('/api/reconnect', { method: 'POST' });
            if (isAuthFailure(response)) {
                stopAutoReconnect();
                return;  // Redirecting to login
            }
            const data = await response.json();

            if (data.success) {
                stopAutoReconnect();
                daemonDisconnected = false;
                hideDaemonDisconnectedOverlay();
                hideModal();

                if (dom.zfsTree) {
                    dom.zfsTree.innerHTML = '<div class="text-muted p-3">Loading...</div>';
                }

                showSuccess('Reconnected', 'Successfully reconnected to the daemon.');
                startHealthCheck();
                await fetchAndRenderData();
            }
        } catch (error) {
            // Silently continue trying
        }
    }, 2000);
}

/**
 * Stop auto-reconnect loop.
 */
function stopAutoReconnect() {
    if (reconnectInterval) {
        clearInterval(reconnectInterval);
        reconnectInterval = null;
    }
}

/**
 * Handle reconnect button click from the disconnected overlay.
 * Calls /api/reconnect and if successful, hides overlay and refreshes data.
 */
async function handleReconnect() {
    try {
        const response = await fetch('/api/reconnect', { method: 'POST' });
        if (isAuthFailure(response)) return;  // Redirecting to login
        const data = await response.json();

        if (data.success) {
            // Successfully reconnected
            stopAutoReconnect();  // Stop auto-reconnect loop
            daemonDisconnected = false;  // Clear disconnected flag
            hideDaemonDisconnectedOverlay();
            hideModal();  // Close any open error modal

            // Clear any error displayed in the tree view
            if (dom.zfsTree) {
                dom.zfsTree.innerHTML = '<div class="text-muted p-3">Loading...</div>';
            }

            showSuccess('Reconnected', 'Successfully reconnected to the daemon.');
            startHealthCheck();  // Restart health monitoring
            await fetchAndRenderData();  // Refresh all data
        } else {
            // Reconnect failed - update message in overlay
            updateDaemonDisconnectedMessage(data.message || 'Reconnect failed. Is the daemon running?');
        }
    } catch (error) {
        console.error('Reconnect error:', error);
        updateDaemonDisconnectedMessage('Reconnect failed: ' + error.message);
    }
}

import {
    updateAuthStateUI,
    checkAuthStatus,
    handleLogin,
    handleLogout,
    handleChangePassword,
    setAuthCallbacks  // Required to enable fetchAndRenderData call after successful auth
} from './auth.js';

import {
    buildTreeHtml,
    renderTree,
    handleTreeItemClick,
    handleTreeToggle,
    clearSelection,
    setTreeCallbacks  // Required to enable tree item click handling
} from './tree.js';

import { renderDashboard } from './dashboard.js';

import {
    renderSnapshots,
    handleCreateSnapshot,
    handleDeleteSnapshot,
    handleRollbackSnapshot,
    handleCloneSnapshot
} from './snapshots.js';

import {
    renderPoolStatus,
    renderPoolEditLayout,
    updatePoolEditActionStates,
    initPoolStatusButtons
} from './pool-status.js';

import {
    renderEncryptionInfo,
    handleLoadKey,
    handleUnloadKey,
    handleChangeKey,
    handleChangeKeyLocation
} from './encryption.js';

import { renderProperties, handleEditProperty, handleInheritProperty } from './property-editor.js';

import {
    handleCreatePool,
    handleImportPool,
    handlePoolAction
} from './pool-actions.js';

import {
    handleCreateDataset,
    handleDestroyDataset,
    handleRenameDataset,
    handlePromoteDataset,
    handleDatasetAction
} from './dataset-actions.js';

import {
    handlePoolEditAction,
    handleAddVdevDialog
} from './pool-edit-actions.js';

import { renderDetails, updateActionStates } from './details.js';

import { initHelpMenu } from './help.js';

// Make constants available globally for modules that may need them
window.EDITABLE_PROPERTIES_WEB = EDITABLE_PROPERTIES_WEB;
window.POOL_LEVEL_PROPERTIES = POOL_LEVEL_PROPERTIES;
window.AUTO_SNAPSHOT_PROPS = AUTO_SNAPSHOT_PROPS;
window.AUTO_SNAPSHOT_SORT_ORDER_WEB = AUTO_SNAPSHOT_SORT_ORDER_WEB;

/**
 * Fetch and render all ZFS data
 */
async function fetchAndRenderData() {
    // Skip if daemon is disconnected (overlay will handle reconnection)
    if (daemonDisconnected) {
        console.log('Skipping data fetch - daemon disconnected');
        setLoadingState(false);
        return;
    }

    if (!state.isAuthenticated) {
        setLoadingState(false);
        return;
    }

    setLoadingState(true);
    const activeTabEl = document.querySelector('#details-tab .nav-link.active');
    const activeTabId = activeTabEl ? activeTabEl.id : 'properties-tab-button';
    let success = false;

    try {
        const result = await apiCall('/api/data');
        renderTree(result.data);

        // Restore selection if possible
        let objectStillExists = false;
        let selectedPath = null;
        let selectedType = null;

        if (state.currentSelection) {
            selectedPath = state.currentSelection.name;
            selectedType = state.currentSelection.obj_type;
            const newSelection = findObjectByPath(selectedPath, selectedType, state.zfsDataCache);
            if (newSelection) {
                state.setCurrentSelection(newSelection);
                objectStillExists = true;
                state.saveSelectionToStorage();
            }
        }

        if (objectStillExists) {
            try {
                await renderDetails(state.currentSelection);
            } catch (detailsError) {
                console.error(`Error rendering details for ${selectedPath}:`, detailsError);
                clearSelection();
                showErrorAlert("Detail Render Error", `Could not render details for ${selectedPath}.\n\nError: ${detailsError.message}`);
            }
        } else if (selectedPath) {
            clearSelection();
        } else {
            clearSelection();
        }

        // Restore tab state
        try {
            const tabToActivate = document.getElementById(activeTabId);
            if (tabToActivate && !tabToActivate.disabled) {
                const tabInstance = bootstrap.Tab.getOrCreateInstance(tabToActivate);
                if (tabInstance) tabInstance.show();
            } else {
                const dashboardTab = document.getElementById('dashboard-tab-button');
                if (dashboardTab && !dashboardTab.disabled) {
                    const dashboardInstance = bootstrap.Tab.getOrCreateInstance(dashboardTab);
                    if (dashboardInstance) dashboardInstance.show();
                } else {
                    const propertiesTab = document.getElementById('properties-tab-button');
                    if (propertiesTab && !propertiesTab.disabled) {
                        const propertiesInstance = bootstrap.Tab.getOrCreateInstance(propertiesTab);
                        if (propertiesInstance) propertiesInstance.show();
                    } else {
                        const firstEnabledTab = document.getElementById('details-tab').querySelector('.nav-link:not(.disabled)');
                        if (firstEnabledTab) {
                            const firstEnabledInstance = bootstrap.Tab.getOrCreateInstance(firstEnabledTab);
                            if (firstEnabledInstance) firstEnabledInstance.show();
                        }
                    }
                }
            }
        } catch (tabError) {
            console.error("Error restoring active tab:", tabError);
            try {
                const dashboardTab = document.getElementById('dashboard-tab-button');
                if (dashboardTab && !dashboardTab.disabled) {
                    const dashboardInstance = bootstrap.Tab.getOrCreateInstance(dashboardTab);
                    if (dashboardInstance) dashboardInstance.show();
                }
            } catch (fallbackError) {
                console.error("Error activating fallback dashboard tab:", fallbackError);
            }
        }

        updateActionStates();
        success = true;

    } catch (error) {
        console.error("Failed to fetch ZFS data:", error);
        dom.zfsTree.innerHTML = `<div class="alert alert-danger" role="alert">Failed to load ZFS data: ${error.message}</div>`;
        showErrorAlert("Data Load Error", `Could not load pool/dataset information. Please ensure the ZFS daemon is running and accessible.\n\nError: ${error.message}${error.details ? '\nDetails: ' + error.details : ''}`);
        state.setZfsDataCache(null);
        clearSelection();
        updateActionStates();
    } finally {
        setLoadingState(false);
    }
}

/**
 * Handle shutdown daemon action
 * Uses dedicated endpoint with proper status messages.
 */
async function handleShutdownDaemon() {
    // First confirm with user
    const confirmed = await showConfirmModal(
        "Shutdown Daemon",
        "Stop the ZfDash background daemon process?<br><br>" +
        "If other clients (like the WebUI) are using this daemon, they will also be disconnected.",
        "Shutdown",
        "btn-danger"
    );

    if (!confirmed) return;

    updateStatus('Shutting down daemon...', 'busy');

    try {
        const response = await fetch('/api/shutdown_daemon', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        const result = await response.json();

        if (result.status === 'success') {
            updateStatus('Daemon shutdown requested.', 'success');
            showSuccess(result.message);
        } else if (result.status === 'info') {
            updateStatus('Shutdown not available.', 'info');
            showWarning(result.message);
        } else {
            updateStatus('Shutdown failed.', 'error');
            showErrorAlert(result.title || 'Shutdown Failed', result.message || 'Unknown error');
        }
    } catch (error) {
        console.error('Shutdown daemon request failed:', error);
        updateStatus('Shutdown error.', 'error');
        showErrorAlert('Network Error', `Could not send shutdown request:\n${error.message}`);
    }
}

/**
 * Initialize the application
 * 
 * INITIALIZATION ORDER IS CRITICAL:
 * 1. initDomElements() - Populate DOM references (must be first, DOM is now ready)
 * 2. state.initializeState() - Load persisted state from localStorage
 * 3. setTreeCallbacks() - Enable tree module to call back to app functions
 * 4. setFetchAndRenderDataRef() - Enable api module to trigger data refresh
 * 5. setAuthCallbacks() - Enable auth module to fetch data after successful login
 * 6. Event listeners - Wire up UI interactions
 * 7. checkAuthStatus() - Check if user is logged in and fetch data if so
 */
document.addEventListener('DOMContentLoaded', () => {

    // Initialize auto-snapshot properties in editable properties
    initializeAutoSnapshotProperties();

    // STEP 1: Initialize DOM element references
    // This populates the 'dom' object with actual DOM element references
    // Must be called first since other code depends on dom.* being populated
    initDomElements();

    // STEP 2: Initialize state from localStorage (expanded nodes, etc.)
    state.initializeState();

    // STEP 3: Set up callbacks for tree module
    // This allows tree.js to call renderDetails() when an item is clicked
    setTreeCallbacks(renderDetails, updateActionStates, clearSelection);

    // STEP 4: Set up callback for api module to enable automatic refresh
    // This allows api.js to trigger a full data refresh after actions
    setFetchAndRenderDataRef(fetchAndRenderData);

    // STEP 5: Set up callbacks for auth module
    // CRITICAL: This enables fetchAndRenderData() to be called after successful authentication
    // Without this, the app will authenticate but never load data!
    setAuthCallbacks(fetchAndRenderData, clearSelection);

    // STEP 6: Set up event listeners for UI interactions
    // --- Authentication Related Listeners ---
    if (dom.loginForm) {
        dom.loginForm.addEventListener('submit', handleLogin);
    }
    if (dom.logoutButton) {
        dom.logoutButton.addEventListener('click', handleLogout);
    }
    if (dom.changePasswordConfirmButton) {
        dom.changePasswordConfirmButton.addEventListener('click', handleChangePassword);
    }

    // Clear change password modal messages when shown
    if (dom.changePasswordModalElement) {
        dom.changePasswordModalElement.addEventListener('show.bs.modal', () => {
            if (dom.changePasswordError) dom.changePasswordError.style.display = 'none';
            if (dom.changePasswordSuccess) dom.changePasswordSuccess.style.display = 'none';
            if (dom.changePasswordForm) dom.changePasswordForm.reset();
        });
    }

    // --- Fix for encryption tab spacing ---
    const encryptionTab = document.getElementById('encryption-tab-button');
    if (encryptionTab) {
        encryptionTab.addEventListener('shown.bs.tab', function () {
            const encryptionPane = document.getElementById('encryption-tab-pane');
            if (encryptionPane) {
                const tabsNav = document.querySelector('.nav-tabs');
                if (tabsNav) {
                    Object.assign(encryptionPane.style, {
                        position: 'absolute',
                        top: tabsNav.offsetHeight + 'px',
                        left: '0',
                        right: '0',
                        zIndex: '10',
                        backgroundColor: '#fff',
                        borderTop: '0',
                        padding: '0',
                        margin: '0'
                    });
                }

                encryptionPane.querySelectorAll('table, th, td').forEach(el => {
                    Object.assign(el.style, {
                        margin: '0',
                        border: '0',
                        padding: '2px 8px'
                    });
                });

                encryptionPane.querySelectorAll('h5').forEach(h => {
                    Object.assign(h.style, {
                        marginTop: '0',
                        paddingTop: '5px',
                        marginBottom: '5px'
                    });
                });
            }
        });
    }

    // --- Disable action buttons initially ---
    const buttonsToDisable = [
        'destroy-pool-button', 'export-pool-button', 'scrub-start-button', 'scrub-stop-button', 'clear-errors-button',
        'create-dataset-button', 'destroy-dataset-button', 'rename-dataset-button', 'mount-dataset-button', 'unmount-dataset-button', 'promote-dataset-button'
    ];
    buttonsToDisable.forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.classList.add('disabled');
    });

    // These are always enabled initially
    document.getElementById('create-pool-button')?.classList.remove('disabled');
    document.getElementById('import-pool-button')?.classList.remove('disabled');

    // STEP 7: Check daemon health first (for socket mode)
    // This MUST complete before we try to fetch data
    (async () => {
        const healthy = await doHealthCheck();
        if (healthy) {
            startHealthCheck();  // Start periodic polling
        }

        // STEP 8: Check authentication status
        // If user is authenticated, this will call fetchAndRenderData() via the 
        // callback we set up with setAuthCallbacks() above
        checkAuthStatus(fetchAndRenderData);
    })();

    // Refresh button
    if (dom.refreshButton) {
        dom.refreshButton.addEventListener('click', () => {
            if (state.isAuthenticated) {
                fetchAndRenderData();
            } else {
                console.log("Refresh skipped: Not authenticated.");
            }
        });
    }

    // --- Global Action Buttons (Pool Actions) ---
    document.getElementById('create-pool-button')?.addEventListener('click', handleCreatePool);
    document.getElementById('import-pool-button')?.addEventListener('click', handleImportPool);
    document.getElementById('destroy-pool-button')?.addEventListener('click', () =>
        handlePoolAction('destroy_pool', true, `DANGER ZONE!<br><br>Destroy pool <strong>'${state.currentSelection?.name}'</strong> and ALL data?<br>THIS CANNOT BE UNDONE.`));
    document.getElementById('export-pool-button')?.addEventListener('click', async () => {
        const choice = await showTripleChoiceModal(
            "Export Pool",
            `Export pool <strong>'${state.currentSelection?.name}'</strong>?<br><br>Choose export type:<br>• <strong>Normal</strong>: Safe export (fails if datasets are in use)<br>• <strong>Force</strong>: Forces export even if in use (may cause issues)`,
            "Normal Export", "btn-primary",
            "Force Export", "btn-warning"
        );
        if (choice === 'optionA') {
            handlePoolAction('export_pool', false, null, [], { force: false });
        } else if (choice === 'optionB') {
            handlePoolAction('export_pool', false, null, [], { force: true });
        }
    });
    document.getElementById('scrub-start-button')?.addEventListener('click', () =>
        handlePoolAction('scrub_pool', false, null, [], { stop: false }));
    document.getElementById('scrub-stop-button')?.addEventListener('click', () =>
        handlePoolAction('scrub_pool', false, null, [], { stop: true }));
    document.getElementById('clear-errors-button')?.addEventListener('click', () =>
        handlePoolAction('clear_pool_errors', true, `Clear persistent errors for pool '${state.currentSelection?.name}'?`));

    // --- Dataset Button Listeners ---
    document.getElementById('create-dataset-button')?.addEventListener('click', handleCreateDataset);
    document.getElementById('destroy-dataset-button')?.addEventListener('click', handleDestroyDataset);
    document.getElementById('rename-dataset-button')?.addEventListener('click', handleRenameDataset);
    document.getElementById('mount-dataset-button')?.addEventListener('click', () => handleDatasetAction('mount_dataset'));
    document.getElementById('unmount-dataset-button')?.addEventListener('click', () => handleDatasetAction('unmount_dataset'));
    document.getElementById('promote-dataset-button')?.addEventListener('click', handlePromoteDataset);

    // --- Snapshot Tab Buttons ---
    document.getElementById('create-snapshot-button')?.addEventListener('click', handleCreateSnapshot);
    document.getElementById('delete-snapshot-button')?.addEventListener('click', handleDeleteSnapshot);
    document.getElementById('rollback-snapshot-button')?.addEventListener('click', handleRollbackSnapshot);
    document.getElementById('clone-snapshot-button')?.addEventListener('click', handleCloneSnapshot);

    // --- Pool Edit Tab Buttons ---
    document.getElementById('attach-device-button')?.addEventListener('click', () =>
        handlePoolEditAction('attach', dom.poolEditTreeContainer.querySelector('.selected')));
    document.getElementById('detach-device-button')?.addEventListener('click', () =>
        handlePoolEditAction('detach', dom.poolEditTreeContainer.querySelector('.selected')));
    document.getElementById('replace-device-button')?.addEventListener('click', () =>
        handlePoolEditAction('replace', dom.poolEditTreeContainer.querySelector('.selected')));
    document.getElementById('offline-device-button')?.addEventListener('click', () =>
        handlePoolEditAction('offline', dom.poolEditTreeContainer.querySelector('.selected')));
    document.getElementById('online-device-button')?.addEventListener('click', () =>
        handlePoolEditAction('online', dom.poolEditTreeContainer.querySelector('.selected')));
    document.getElementById('add-pool-vdev-button')?.addEventListener('click', handleAddVdevDialog);
    document.getElementById('remove-pool-vdev-button')?.addEventListener('click', () =>
        handlePoolEditAction('remove_vdev', dom.poolEditTreeContainer.querySelector('.selected')));
    document.getElementById('split-pool-button')?.addEventListener('click', () =>
        handlePoolEditAction('split', dom.poolEditTreeContainer.querySelector('.selected')));

    // --- Pool Status View Buttons ---
    initPoolStatusButtons();

    // --- Encryption Tab Buttons ---
    document.getElementById('load-key-button')?.addEventListener('click', handleLoadKey);
    document.getElementById('unload-key-button')?.addEventListener('click', handleUnloadKey);
    document.getElementById('change-key-button')?.addEventListener('click', handleChangeKey);
    document.getElementById('change-key-location-button')?.addEventListener('click', handleChangeKeyLocation);

    // --- Shutdown Button ---
    document.getElementById('shutdown-daemon-button')?.addEventListener('click', handleShutdownDaemon);

    // --- Help Menu (About, Check for Updates) ---
    initHelpMenu();
});

// --- END OF FILE src/static/js/app.js ---
