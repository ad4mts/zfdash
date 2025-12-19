/**
 * Control Center Main Module
 * 
 * Handles UI logic for the Control Center page.
 */

import * as api from './control-center-api.js';
import { showSuccess, showError } from './notifications.js';
import { showConfirmModal } from './ui.js';

// State
let agents = [];
let currentMode = 'local';
let activeAlias = null;
let passwordModal = null;
let discoveryModal = null;
let editAgentModal = null;
let pendingConnectAlias = null;
let isScanning = false;

/**
 * Initialize the control center
 */
async function init() {
    console.log('Control Center: Initializing...');

    // Initialize Bootstrap modals
    const passwordModalEl = document.getElementById('passwordModal');
    if (passwordModalEl) {
        passwordModal = new bootstrap.Modal(passwordModalEl);
    }

    const discoveryModalEl = document.getElementById('discoveryModal');
    if (discoveryModalEl) {
        discoveryModal = new bootstrap.Modal(discoveryModalEl);
    }

    const editAgentModalEl = document.getElementById('editAgentModal');
    if (editAgentModalEl) {
        editAgentModal = new bootstrap.Modal(editAgentModalEl);
    }

    // Set up event listeners
    setupEventListeners();

    // Load agents
    await refreshAgentsList();
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Add agent form
    const addForm = document.getElementById('add-agent-form');
    if (addForm) {
        addForm.addEventListener('submit', handleAddAgent);
    }

    // Password form
    const passwordForm = document.getElementById('password-form');
    if (passwordForm) {
        passwordForm.addEventListener('submit', (e) => {
            e.preventDefault();
            handlePasswordSubmit();
        });
    }

    const passwordSubmitBtn = document.getElementById('password-submit-btn');
    if (passwordSubmitBtn) {
        passwordSubmitBtn.addEventListener('click', handlePasswordSubmit);
    }

    // Switch to local button
    const switchLocalBtn = document.getElementById('switch-local-btn');
    if (switchLocalBtn) {
        switchLocalBtn.addEventListener('click', () => handleSwitchAgent('local'));
    }

    // Discovery button
    const discoverBtn = document.getElementById('discover-btn');
    if (discoverBtn) {
        discoverBtn.addEventListener('click', handleDiscoverAgents);
    }

    // Rescan button
    const rescanBtn = document.getElementById('rescan-btn');
    if (rescanBtn) {
        rescanBtn.addEventListener('click', performDiscoveryScan);
    }

    // Select All checkbox
    const selectAllCheckbox = document.getElementById('select-all-agents');
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', handleSelectAllAgents);
    }

    // Add Selected button
    const addSelectedBtn = document.getElementById('add-selected-btn');
    if (addSelectedBtn) {
        addSelectedBtn.addEventListener('click', handleAddSelectedAgents);
    }

    // Edit Save button
    const editSaveBtn = document.getElementById('edit-save-btn');
    if (editSaveBtn) {
        editSaveBtn.addEventListener('click', handleSaveEdit);
    }

    // Edit form submit
    const editForm = document.getElementById('edit-agent-form');
    if (editForm) {
        editForm.addEventListener('submit', (e) => {
            e.preventDefault();
            handleSaveEdit();
        });
    }
}

/**
 * Handle add agent form submission
 */
async function handleAddAgent(e) {
    e.preventDefault();

    const alias = document.getElementById('agent-alias').value.trim();
    const host = document.getElementById('agent-host').value.trim();
    const port = parseInt(document.getElementById('agent-port').value);
    const useTls = document.getElementById('agent-use-tls').checked;

    if (!alias || !host || !port) {
        showError('All fields are required');
        return;
    }

    try {
        const result = await api.addAgent(alias, host, port, useTls);

        if (result.success) {
            showSuccess(`Agent '${alias}' added successfully`);
            e.target.reset();
            // Re-check the TLS checkbox after form reset (it defaults to checked)
            document.getElementById('agent-use-tls').checked = true;
            await refreshAgentsList();
        } else {
            showError(result.error || 'Failed to add agent');
        }
    } catch (error) {
        console.error('Error adding agent:', error);
        showError('Network error while adding agent');
    }
}

/**
 * Handle remove agent
 */
async function handleRemoveAgent(alias) {
    const confirmed = await showConfirmModal(
        "Remove Agent",
        `Are you sure you want to remove agent '<strong>${alias}</strong>'?`,
        "Remove",
        "btn-danger"
    );
    if (!confirmed) return;

    try {
        const result = await api.removeAgent(alias);

        if (result.success) {
            showSuccess(result.message || 'Agent removed successfully');
            await refreshAgentsList();
        } else {
            showError(result.error || 'Failed to remove agent');
        }
    } catch (error) {
        console.error('Error removing agent:', error);
        showError('Network error while removing agent');
    }
}

/**
 * Handle connect agent (shows password prompt)
 */
function handleConnectAgent(alias) {
    pendingConnectAlias = alias;
    const nameEl = document.getElementById('password-agent-name');
    if (nameEl) {
        nameEl.textContent = alias;
    }

    // Clear password field, error, and status
    const passwordField = document.getElementById('agent-password');
    if (passwordField) {
        passwordField.value = '';
    }
    const errorDiv = document.getElementById('password-error');
    if (errorDiv) {
        errorDiv.style.display = 'none';
    }
    const statusDiv = document.getElementById('password-status');
    if (statusDiv) {
        statusDiv.style.display = 'none';
    }

    // Reset submit button state
    resetSubmitButton();

    if (passwordModal) {
        passwordModal.show();

        // Focus password field after modal is shown
        setTimeout(() => {
            if (passwordField) {
                passwordField.focus();
            }
        }, 300);
    }
}

/**
 * Handle password modal submit
 */
async function handlePasswordSubmit() {
    const password = document.getElementById('agent-password').value;
    const errorDiv = document.getElementById('password-error');
    const statusDiv = document.getElementById('password-status');

    if (!password) {
        errorDiv.textContent = 'Password is required';
        errorDiv.style.display = 'block';
        return;
    }

    if (!pendingConnectAlias) {
        return;
    }

    // Show connecting status
    showConnectingStatus();

    try {
        const result = await api.connectAgent(pendingConnectAlias, password);

        // Hide connecting status
        hideConnectingStatus();

        if (result.success) {
            if (passwordModal) {
                passwordModal.hide();
            }
            showSuccess(result.message || 'Connected successfully');
            await refreshAgentsList();
        } else {
            const errorMsg = result.error || 'Authentication failed';

            // Check for structured TLS error codes
            if (result.tls_error_code === 'TLS_REQUIRED') {
                // Server requires TLS but client didn't use it
                errorDiv.innerHTML = `
                    ${escapeHtml(errorMsg)}
                    <div class="mt-2">
                        <button type="button" class="btn btn-info btn-sm" id="retry-tls-btn">
                            <i class="bi bi-shield-lock"></i> Retry with TLS
                        </button>
                    </div>
                `;
                errorDiv.style.display = 'block';

                document.getElementById('retry-tls-btn')?.addEventListener('click', async () => {
                    await handleRetryWithTls(password);
                });
            } else if (result.tls_error_code === 'TLS_UNAVAILABLE') {
                // Client wanted TLS but server doesn't support it
                errorDiv.innerHTML = `
                    ${escapeHtml(errorMsg)}
                    <div class="mt-2">
                        <button type="button" class="btn btn-warning btn-sm" id="retry-no-tls-btn">
                            <i class="bi bi-shield-slash"></i> Retry without TLS
                        </button>
                    </div>
                `;
                errorDiv.style.display = 'block';

                document.getElementById('retry-no-tls-btn')?.addEventListener('click', async () => {
                    await handleRetryWithoutTls(password);
                });
            } else {
                // Other error (auth failure, connection error, etc.)
                errorDiv.textContent = errorMsg;
                errorDiv.style.display = 'block';
            }
        }
    } catch (error) {
        console.error('Error connecting to agent:', error);
        hideConnectingStatus();
        errorDiv.textContent = 'Network error while connecting';
        errorDiv.style.display = 'block';
    }
}

/**
 * Handle retry connection without TLS (saves setting then reconnects)
 */
async function handleRetryWithoutTls(password) {
    if (!pendingConnectAlias) return;

    const errorDiv = document.getElementById('password-error');

    // First, update the TLS setting to disabled (this saves permanently)
    try {
        await api.updateTls(pendingConnectAlias, false);
    } catch (e) {
        console.error('Failed to update TLS setting:', e);
    }

    // Show connecting status
    showConnectingStatus();

    try {
        // Now connect (will use the updated TLS=false setting)
        const result = await api.connectAgent(pendingConnectAlias, password);

        // Hide connecting status
        hideConnectingStatus();

        if (result.success) {
            if (passwordModal) {
                passwordModal.hide();
            }
            showSuccess(result.message || 'Connected (TLS disabled)');
            await refreshAgentsList();
        } else {
            errorDiv.textContent = result.error || 'Connection failed';
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        console.error('Error retrying connection:', error);
        hideConnectingStatus();
        errorDiv.textContent = 'Network error while retrying';
        errorDiv.style.display = 'block';
    }
}

/**
 * Handle retry connection with TLS (saves setting then reconnects)
 */
async function handleRetryWithTls(password) {
    if (!pendingConnectAlias) return;

    const errorDiv = document.getElementById('password-error');

    // First, update the TLS setting to enabled (this saves permanently)
    try {
        await api.updateTls(pendingConnectAlias, true);
    } catch (e) {
        console.error('Failed to update TLS setting:', e);
    }

    // Show connecting status
    showConnectingStatus();

    try {
        // Now connect (will use the updated TLS=true setting)
        const result = await api.connectAgent(pendingConnectAlias, password);

        // Hide connecting status
        hideConnectingStatus();

        if (result.success) {
            if (passwordModal) {
                passwordModal.hide();
            }
            showSuccess(result.message || 'Connected (TLS enabled)');
            await refreshAgentsList();
        } else {
            errorDiv.textContent = result.error || 'Connection failed';
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        console.error('Error retrying connection with TLS:', error);
        hideConnectingStatus();
        errorDiv.textContent = 'Network error while retrying';
        errorDiv.style.display = 'block';
    }
}

/**
 * Handle toggle TLS setting for a disconnected agent
 */
async function handleToggleTls(alias) {
    try {
        // Get current agents list to find current TLS state
        const result = await api.listAgents();
        if (!result.success) {
            showError('Failed to get agent info');
            return;
        }

        const agent = result.connections.find(a => a.alias === alias);
        if (!agent) {
            showError('Agent not found');
            return;
        }

        // Toggle the TLS setting
        const newTlsSetting = !agent.use_tls;
        const updateResult = await api.updateTls(alias, newTlsSetting);

        if (updateResult.success) {
            showSuccess(`TLS ${newTlsSetting ? 'enabled' : 'disabled'} for '${alias}'`);
            await refreshAgentsList();
        } else {
            showError(updateResult.error || 'Failed to update TLS setting');
        }
    } catch (error) {
        console.error('Error toggling TLS:', error);
        showError('Network error while updating TLS setting');
    }
}

/**
 * Handle disconnect agent
 */
async function handleDisconnectAgent(alias) {
    try {
        const result = await api.disconnectAgent(alias);

        if (result.success) {
            showSuccess(result.message || 'Disconnected successfully');
            await refreshAgentsList();
        } else {
            showError(result.error || 'Failed to disconnect');
        }
    } catch (error) {
        console.error('Error disconnecting from agent:', error);
        showError('Network error while disconnecting');
    }
}

/**
 * Handle switch active agent
 */
async function handleSwitchAgent(alias) {
    try {
        const result = await api.switchAgent(alias);

        if (result.success) {
            showSuccess(result.message || 'Switched successfully');
            await refreshAgentsList();
        } else {
            showError(result.error || 'Failed to switch');
        }
    } catch (error) {
        console.error('Error switching agent:', error);
        showError('Network error while switching');
    }
}

/**
 * Refresh agents list from backend
 */
async function refreshAgentsList() {
    try {
        const result = await api.listAgents();

        if (result.success) {
            agents = result.connections || [];
            currentMode = result.current_mode || 'local';
            activeAlias = result.active_alias;

            renderAgentsList();
            updateModeIndicator();
        } else {
            showError(result.error || 'Failed to load agents');
        }
    } catch (error) {
        console.error('Error refreshing agents list:', error);
        showError('Network error while loading agents');
    }
}

/**
 * Render agents list in UI
 */
function renderAgentsList() {
    const container = document.getElementById('agents-list');
    if (!container) return;

    if (agents.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="bi bi-inbox display-1"></i>
                <p class="mt-3">No remote agents configured yet.</p>
                <p class="small">Add a remote agent above to get started.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = agents.map(agent => createAgentCard(agent)).join('');

    // Attach event listeners to buttons
    attachAgentCardListeners();
}

/**
 * Create agent card HTML
 */
function createAgentCard(agent) {
    const statusBadge = agent.connected
        ? '<span class="badge bg-success status-badge">Connected</span>'
        : '<span class="badge bg-secondary status-badge">Disconnected</span>';

    // TLS preference/status badges
    let tlsBadge = '';
    if (agent.connected) {
        // Show actual connection TLS status
        tlsBadge = agent.tls_active
            ? '<span class="badge bg-info status-badge ms-1" title="Connection is encrypted">🔒 TLS</span>'
            : '<span class="badge bg-danger status-badge ms-1" title="Connection is NOT encrypted!">⚠️ No TLS</span>';
    } else {
        // Show configured TLS preference
        tlsBadge = agent.use_tls
            ? '<span class="badge bg-secondary status-badge ms-1" title="TLS enabled (will encrypt when connected)"><i class="bi bi-shield-lock"></i></span>'
            : '<span class="badge bg-warning status-badge ms-1" title="TLS disabled"><i class="bi bi-shield-slash"></i> No TLS</span>';
    }

    const activeClass = agent.active ? ' active' : '';
    const connectedClass = agent.connected ? ' connected' : '';

    const actionButtons = agent.connected
        ? `
            <button class="btn btn-warning btn-sm me-1" data-action="disconnect" data-alias="${agent.alias}">
                <i class="bi bi-plug"></i> Disconnect
            </button>
            ${!agent.active ? `
                <button class="btn btn-primary btn-sm" data-action="switch" data-alias="${agent.alias}">
                    <i class="bi bi-arrow-left-right"></i> Switch
                </button>
            ` : '<span class="badge bg-primary">Active</span>'}
        `
        : `
            <button class="btn btn-success btn-sm me-1" data-action="connect" data-alias="${agent.alias}">
                <i class="bi bi-plug-fill"></i> Connect
            </button>
            <button class="btn btn-outline-secondary btn-sm me-1" data-action="edit" data-alias="${agent.alias}" title="Edit agent">
                <i class="bi bi-pencil"></i>
            </button>
        `;

    const lastConnected = agent.last_connected
        ? new Date(agent.last_connected).toLocaleString()
        : 'Never';

    return `
        <div class="card agent-card mb-2${activeClass}${connectedClass}">
            <div class="card-body">
                <div class="row align-items-center">
                    <div class="col-md-4">
                        <h5 class="mb-1">
                            <i class="bi bi-hdd-network me-2"></i>${escapeHtml(agent.alias)}
                        </h5>
                        <small class="text-muted">${escapeHtml(agent.host)}:${agent.port}</small>
                        <br>
                        <small class="text-muted">Last connected: ${lastConnected}</small>
                    </div>
                    <div class="col-md-4 text-center">
                        ${statusBadge}${tlsBadge}
                        ${agent.last_error ? `<div class="text-danger small mt-1">${escapeHtml(agent.last_error)}</div>` : ''}
                    </div>
                    <div class="col-md-4 text-end">
                        ${actionButtons}
                        <button class="btn btn-danger btn-sm" data-action="remove" data-alias="${agent.alias}">
                            <i class="bi bi-trash"></i>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

/**
 * Attach event listeners to agent card buttons
 */
function attachAgentCardListeners() {
    document.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const action = e.currentTarget.dataset.action;
            const alias = e.currentTarget.dataset.alias;

            switch (action) {
                case 'connect':
                    handleConnectAgent(alias);
                    break;
                case 'disconnect':
                    handleDisconnectAgent(alias);
                    break;
                case 'switch':
                    handleSwitchAgent(alias);
                    break;
                case 'remove':
                    handleRemoveAgent(alias);
                    break;
                case 'edit':
                    handleEditAgent(alias);
                    break;
            }
        });
    });
}

/**
 * Handle edit agent button click
 */
function handleEditAgent(alias) {
    const agent = agents.find(a => a.alias === alias);
    if (!agent) {
        showError('Agent not found');
        return;
    }

    // Get form elements
    const oldAliasField = document.getElementById('edit-old-alias');
    const aliasField = document.getElementById('edit-alias');
    const hostField = document.getElementById('edit-host');
    const portField = document.getElementById('edit-port');
    const tlsField = document.getElementById('edit-use-tls');

    // Check if modal elements exist (might be cached page without new modal)
    if (!oldAliasField || !aliasField || !hostField || !portField || !tlsField) {
        showError('Edit modal not found. Please refresh the page (Ctrl+Shift+R).');
        return;
    }

    // Populate edit form
    oldAliasField.value = agent.alias;
    aliasField.value = agent.alias;
    hostField.value = agent.host;
    portField.value = agent.port;
    tlsField.checked = agent.use_tls;

    // Clear any previous error
    const errorDiv = document.getElementById('edit-error');
    if (errorDiv) errorDiv.style.display = 'none';

    // Show modal
    if (editAgentModal) {
        editAgentModal.show();
    }
}

/**
 * Handle save edit button click
 */
async function handleSaveEdit() {
    const oldAlias = document.getElementById('edit-old-alias').value;
    const newAlias = document.getElementById('edit-alias').value.trim();
    const host = document.getElementById('edit-host').value.trim();
    const port = parseInt(document.getElementById('edit-port').value);
    const useTls = document.getElementById('edit-use-tls').checked;
    const errorDiv = document.getElementById('edit-error');
    const saveBtn = document.getElementById('edit-save-btn');

    if (!newAlias || !host || !port) {
        errorDiv.textContent = 'All fields are required';
        errorDiv.style.display = 'block';
        return;
    }

    // Disable button and show loading
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Saving...';
    }

    try {
        const result = await api.updateAgent(oldAlias, newAlias, host, port, useTls);

        if (result.success) {
            if (editAgentModal) editAgentModal.hide();
            showSuccess(result.message || 'Agent updated successfully');
            await refreshAgentsList();
        } else {
            errorDiv.textContent = result.error || 'Failed to update agent';
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        console.error('Error updating agent:', error);
        errorDiv.textContent = 'Network error while updating agent';
        errorDiv.style.display = 'block';
    } finally {
        // Reset button
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<i class="bi bi-check-lg"></i> Save Changes';
        }
    }
}

/**
 * Update mode indicator
 */
function updateModeIndicator() {
    const modeText = document.getElementById('current-mode-text');
    const localCard = document.getElementById('local-daemon-card');
    const switchLocalBtn = document.getElementById('switch-local-btn');

    if (currentMode === 'local') {
        if (modeText) modeText.textContent = 'Local Daemon';
        if (localCard) localCard.classList.add('active');
        if (switchLocalBtn) switchLocalBtn.disabled = true;
    } else {
        if (modeText) modeText.textContent = `Remote Agent: ${activeAlias}`;
        if (localCard) localCard.classList.remove('active');
        if (switchLocalBtn) switchLocalBtn.disabled = false;
    }
}


/**
 * Handle discover agents button click
 */
function handleDiscoverAgents() {
    if (discoveryModal) {
        // Reset modal state
        document.getElementById('discovery-scanning').style.display = 'block';
        document.getElementById('discovery-results').style.display = 'none';
        document.getElementById('discovery-empty').style.display = 'none';
        document.getElementById('mdns-status').textContent = 'checking...';
        document.getElementById('mdns-status').className = '';

        discoveryModal.show();
        performDiscoveryScan();
    }
}

/**
 * Perform network discovery scan
 */
async function performDiscoveryScan() {
    if (isScanning) return;
    isScanning = true;

    const scanningDiv = document.getElementById('discovery-scanning');
    const resultsDiv = document.getElementById('discovery-results');
    const emptyDiv = document.getElementById('discovery-empty');
    const rescanBtn = document.getElementById('rescan-btn');

    // Show scanning state
    scanningDiv.style.display = 'block';
    resultsDiv.style.display = 'none';
    emptyDiv.style.display = 'none';
    if (rescanBtn) rescanBtn.disabled = true;

    try {
        const result = await api.discoverAgents(3);

        // Update mDNS status
        const mdnsStatus = document.getElementById('mdns-status');
        if (result.mdns_available) {
            mdnsStatus.textContent = 'available';
            mdnsStatus.className = 'text-success';
        } else {
            mdnsStatus.textContent = 'not available';
            mdnsStatus.className = 'text-warning';
        }

        if (result.success && result.agents && result.agents.length > 0) {
            renderDiscoveredAgents(result.agents);
            scanningDiv.style.display = 'none';
            resultsDiv.style.display = 'block';
        } else {
            scanningDiv.style.display = 'none';
            emptyDiv.style.display = 'block';
        }
    } catch (error) {
        console.error('Discovery error:', error);
        showError('Failed to discover agents');
        scanningDiv.style.display = 'none';
        emptyDiv.style.display = 'block';
    } finally {
        isScanning = false;
        if (rescanBtn) rescanBtn.disabled = false;
    }
}

/**
 * Render discovered agents in the modal
 */
function renderDiscoveredAgents(discoveredAgents) {
    const container = document.getElementById('discovered-agents-list');
    if (!container) return;

    // Reset select all checkbox
    const selectAllCheckbox = document.getElementById('select-all-agents');
    if (selectAllCheckbox) selectAllCheckbox.checked = false;

    // Track which agents can be selected (not already configured)
    const selectableAgents = discoveredAgents.filter(a => !isAgentConfigured(a.host, a.port));

    container.innerHTML = discoveredAgents.map((agent, index) => {
        const isConfigured = isAgentConfigured(agent.host, agent.port);
        const tlsBadge = agent.tls
            ? '<span class="badge bg-success ms-2"><i class="bi bi-shield-lock"></i> TLS</span>'
            : '<span class="badge bg-warning ms-2"><i class="bi bi-shield-slash"></i> No TLS</span>';
        const sourceBadge = agent.source === 'mdns'
            ? '<span class="badge bg-info ms-1">mDNS</span>'
            : '<span class="badge bg-secondary ms-1">UDP</span>';

        // Checkbox for selection (only for unconfigured agents)
        const checkbox = isConfigured
            ? ''
            : `<input type="checkbox" class="form-check-input me-3 agent-select-checkbox" 
                 data-host="${escapeHtml(agent.host)}" 
                 data-port="${agent.port}" 
                 data-hostname="${escapeHtml(agent.hostname)}" 
                 data-tls="${agent.tls}">`;

        const actionButton = isConfigured
            ? '<span class="badge bg-secondary"><i class="bi bi-check"></i> Configured</span>'
            : `<button class="btn btn-outline-primary btn-sm" data-discover-action="add" 
                 data-host="${escapeHtml(agent.host)}" 
                 data-port="${agent.port}" 
                 data-hostname="${escapeHtml(agent.hostname)}" 
                 data-tls="${agent.tls}" title="Fill form with this agent">
                 <i class="bi bi-pencil"></i>
               </button>`;

        return `
            <div class="card mb-2${isConfigured ? ' opacity-50' : ''}">
                <div class="card-body py-2">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="d-flex align-items-center">
                            ${checkbox}
                            <div>
                                <strong><i class="bi bi-hdd-network me-2"></i>${escapeHtml(agent.hostname)}</strong>
                                ${tlsBadge}${sourceBadge}
                                <div class="small text-muted">${escapeHtml(agent.host)}:${agent.port}</div>
                            </div>
                        </div>
                        <div>${actionButton}</div>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    // Attach listeners for add buttons (fills form)
    container.querySelectorAll('[data-discover-action="add"]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const target = e.currentTarget;
            handleAddDiscoveredAgent({
                host: target.dataset.host,
                port: parseInt(target.dataset.port),
                hostname: target.dataset.hostname,
                tls: target.dataset.tls === 'true'
            });
        });
    });

    // Attach listeners for checkboxes
    container.querySelectorAll('.agent-select-checkbox').forEach(cb => {
        cb.addEventListener('change', updateSelectionCount);
    });

    // Update selection count
    updateSelectionCount();
}

/**
 * Update the selection count display and button state
 */
function updateSelectionCount() {
    const checkboxes = document.querySelectorAll('.agent-select-checkbox');
    const checkedCount = document.querySelectorAll('.agent-select-checkbox:checked').length;

    // Update count displays
    const selectedCountEl = document.getElementById('selected-count');
    const addSelectedCountEl = document.getElementById('add-selected-count');
    if (selectedCountEl) selectedCountEl.textContent = checkedCount;
    if (addSelectedCountEl) addSelectedCountEl.textContent = checkedCount;

    // Update Add Selected button state
    const addSelectedBtn = document.getElementById('add-selected-btn');
    if (addSelectedBtn) {
        addSelectedBtn.disabled = checkedCount === 0;
    }

    // Update Select All checkbox state
    const selectAllCheckbox = document.getElementById('select-all-agents');
    if (selectAllCheckbox && checkboxes.length > 0) {
        selectAllCheckbox.checked = checkedCount === checkboxes.length;
        selectAllCheckbox.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
    }
}

/**
 * Handle Select All checkbox
 */
function handleSelectAllAgents(e) {
    const isChecked = e.target.checked;
    document.querySelectorAll('.agent-select-checkbox').forEach(cb => {
        cb.checked = isChecked;
    });
    updateSelectionCount();
}

/**
 * Handle Add Selected button - adds all selected agents directly
 */
async function handleAddSelectedAgents() {
    const selectedCheckboxes = document.querySelectorAll('.agent-select-checkbox:checked');
    if (selectedCheckboxes.length === 0) return;

    const addSelectedBtn = document.getElementById('add-selected-btn');
    if (addSelectedBtn) {
        addSelectedBtn.disabled = true;
        addSelectedBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Adding...';
    }

    let successCount = 0;
    let errorCount = 0;

    // Track used aliases to handle duplicates during this batch
    const usedAliases = new Set(agents.map(a => a.alias.toLowerCase()));

    for (const cb of selectedCheckboxes) {
        const agent = {
            host: cb.dataset.host,
            port: parseInt(cb.dataset.port),
            hostname: cb.dataset.hostname,
            tls: cb.dataset.tls === 'true'
        };

        // Generate unique alias (handle duplicate hostnames)
        let alias = agent.hostname;
        let counter = 1;
        while (usedAliases.has(alias.toLowerCase())) {
            counter++;
            alias = `${agent.hostname}-${counter}`;
        }
        usedAliases.add(alias.toLowerCase());

        try {
            const result = await api.addAgent(alias, agent.host, agent.port, agent.tls);
            if (result.success) {
                successCount++;
            } else {
                errorCount++;
                console.error(`Failed to add ${alias}: ${result.error}`);
            }
        } catch (error) {
            errorCount++;
            console.error(`Error adding ${alias}:`, error);
        }
    }

    // Update button
    if (addSelectedBtn) {
        addSelectedBtn.innerHTML = '<i class="bi bi-plus-lg"></i> Add Selected (<span id="add-selected-count">0</span>)';
    }

    // Refresh agents list
    await refreshAgentsList();

    // Re-run discovery to update the modal
    await performDiscoveryScan();

    // Show result message
    if (successCount > 0 && errorCount === 0) {
        showSuccess(`Added ${successCount} agent${successCount > 1 ? 's' : ''} successfully`);
    } else if (successCount > 0 && errorCount > 0) {
        showSuccess(`Added ${successCount} agent${successCount > 1 ? 's' : ''}, ${errorCount} failed`);
    } else if (errorCount > 0) {
        showError(`Failed to add ${errorCount} agent${errorCount > 1 ? 's' : ''}`);
    }
}

/**
 * Check if an agent is already configured
 */
function isAgentConfigured(host, port) {
    return agents.some(a => a.host === host && a.port === port);
}

/**
 * Handle adding a discovered agent (fills form and closes modal)
 */
function handleAddDiscoveredAgent(agent) {
    // Fill the add agent form
    const aliasField = document.getElementById('agent-alias');
    const hostField = document.getElementById('agent-host');
    const portField = document.getElementById('agent-port');
    const tlsField = document.getElementById('agent-use-tls');

    if (aliasField) aliasField.value = agent.hostname;
    if (hostField) hostField.value = agent.host;
    if (portField) portField.value = agent.port;
    if (tlsField) tlsField.checked = agent.tls;

    // Close modal
    if (discoveryModal) {
        discoveryModal.hide();
    }

    // Focus on alias field so user can edit if needed
    if (aliasField) {
        aliasField.focus();
        aliasField.select();
    }

    showSuccess(`Form filled with ${agent.hostname}. Click "Add" to save.`);
}


/**
 * Show connecting status in the password modal
 */
function showConnectingStatus() {
    const statusDiv = document.getElementById('password-status');
    const submitBtn = document.getElementById('password-submit-btn');
    const passwordField = document.getElementById('agent-password');
    const errorDiv = document.getElementById('password-error');

    // Hide any existing error
    if (errorDiv) {
        errorDiv.style.display = 'none';
    }

    // Show status
    if (statusDiv) {
        statusDiv.style.display = 'flex';
    }

    // Disable inputs and button
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Connecting...';
    }
    if (passwordField) {
        passwordField.disabled = true;
    }
}

/**
 * Hide connecting status in the password modal
 */
function hideConnectingStatus() {
    const statusDiv = document.getElementById('password-status');
    if (statusDiv) {
        statusDiv.style.display = 'none';
    }

    resetSubmitButton();
}

/**
 * Reset the submit button to its default state
 */
function resetSubmitButton() {
    const submitBtn = document.getElementById('password-submit-btn');
    const passwordField = document.getElementById('agent-password');

    if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = 'Connect';
    }
    if (passwordField) {
        passwordField.disabled = false;
    }
}


/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(unsafe) {
    if (unsafe === null || unsafe === undefined) return '';
    return String(unsafe)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
