/**
 * Control Center Main Module
 * 
 * Handles UI logic for the Control Center page.
 */

import * as api from './control-center-api.js';

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

    if (!alias || !host || !port) {
        showError('All fields are required');
        return;
    }

    try {
        const result = await api.addAgent(alias, host, port);

        if (result.success) {
            showSuccess(`Agent '${alias}' added successfully`);
            e.target.reset();
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
    if (!confirm(`Remove agent '${alias}'?`)) {
        return;
    }

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

    // Clear password field and error
    const passwordField = document.getElementById('agent-password');
    if (passwordField) {
        passwordField.value = '';
    }
    const errorDiv = document.getElementById('password-error');
    if (errorDiv) {
        errorDiv.style.display = 'none';
    }

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

    if (!password) {
        errorDiv.textContent = 'Password is required';
        errorDiv.style.display = 'block';
        return;
    }

    if (!pendingConnectAlias) {
        return;
    }

    try {
        const result = await api.connectAgent(pendingConnectAlias, password);

        if (result.success) {
            if (passwordModal) {
                passwordModal.hide();
            }
            showSuccess(result.message || 'Connected successfully');
            await refreshAgentsList();
        } else {
            errorDiv.textContent = result.error || 'Authentication failed';
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        console.error('Error connecting to agent:', error);
        errorDiv.textContent = 'Network error while connecting';
        errorDiv.style.display = 'block';
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
                        ${statusBadge}
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
 * Show success message
 */
function showSuccess(message) {
    // Simple alert for now, can be enhanced with toast notifications
    alert(message);
}

/**
 * Show error message
 */
function showError(message) {
    alert('Error: ' + message);
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
