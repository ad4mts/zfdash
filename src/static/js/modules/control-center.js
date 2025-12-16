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
let pendingConnectAlias = null;

/**
 * Initialize the control center
 */
async function init() {
    console.log('Control Center: Initializing...');

    // Initialize Bootstrap modal
    const modalEl = document.getElementById('passwordModal');
    if (modalEl) {
        passwordModal = new bootstrap.Modal(modalEl);
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
            <button class="btn btn-outline-secondary btn-sm me-1" data-action="toggle-tls" data-alias="${agent.alias}" title="Toggle TLS">
                <i class="bi bi-${agent.use_tls ? 'shield-lock' : 'shield-slash'}"></i>
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
                case 'toggle-tls':
                    handleToggleTls(alias);
                    break;
            }
        });
    });
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
