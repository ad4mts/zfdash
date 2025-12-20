/**
 * Connection Indicator Module
 * 
 * Shared module for navbar connection indicator with Quick Switch functionality.
 * Used by both app.js (main page) and backup-page.js.
 */

import * as api from './control-center-api.js';
import * as vault from './vault-ui.js';
import { showSuccess, showError } from './notifications.js';

// Module state
let passwordModal = null;
let pendingQuickSwitch = null;
let onSwitchSuccessCallback = null;

/**
 * Initialize the connection indicator module
 * @param {Function} onSwitchSuccess - Callback to run after successful switch (e.g., refresh data)
 */
export function init(onSwitchSuccess) {
    onSwitchSuccessCallback = onSwitchSuccess;

    // Initialize password modal if it exists
    const modalEl = document.getElementById('quickSwitchPasswordModal');
    if (modalEl) {
        passwordModal = new bootstrap.Modal(modalEl);
        setupPasswordModalHandlers();
    }
}

/**
 * Update the connection indicator in the navbar.
 * Fetches current connection status and renders Quick Switch menu.
 */
export async function updateConnectionIndicator() {
    const iconEl = document.getElementById('connection-status-icon');
    const textEl = document.getElementById('connection-status-text');
    const detailsEl = document.getElementById('connection-details');
    const quickSwitchMenu = document.getElementById('quick-switch-menu');

    if (!iconEl || !textEl) return;

    try {
        const data = await api.listAgents();
        if (!data.success) return;

        const isLocal = data.current_mode === 'local';
        const activeAlias = data.active_alias;
        const agents = data.connections || [];

        // Find the active agent details if remote
        let activeAgent = null;
        if (!isLocal && activeAlias && agents) {
            activeAgent = agents.find(c => c.alias === activeAlias && c.active);
        }

        // Update indicator icon and text
        if (isLocal) {
            iconEl.innerHTML = '<i class="bi bi-pc-display text-success"></i>';
            textEl.textContent = 'Local';
            textEl.className = 'small text-success';
            if (detailsEl) {
                detailsEl.innerHTML = '<i class="bi bi-check-circle me-1 text-success"></i> Connected to local daemon';
            }
        } else if (activeAgent) {
            const tlsIcon = activeAgent.tls_active
                ? '<i class="bi bi-shield-lock-fill text-info ms-1" title="TLS encrypted"></i>'
                : '';
            iconEl.innerHTML = '<i class="bi bi-hdd-network text-info"></i>';
            textEl.innerHTML = `${activeAgent.alias}${tlsIcon}`;
            textEl.className = 'small text-info';
            if (detailsEl) {
                const tlsStatus = activeAgent.tls_active ? '🔒 Encrypted' : '⚠️ Not encrypted';
                detailsEl.innerHTML = `
                    <i class="bi bi-cloud me-1 text-info"></i> Remote: ${activeAgent.host}:${activeAgent.port}<br>
                    <small class="text-muted">${tlsStatus}</small>
                `;
            }
        } else {
            iconEl.innerHTML = '<i class="bi bi-question-circle text-warning"></i>';
            textEl.textContent = 'Unknown';
            textEl.className = 'small text-warning';
        }

        // Render Quick Switch menu
        if (quickSwitchMenu) {
            renderQuickSwitchMenu(quickSwitchMenu, agents, isLocal, activeAlias);
            setupQuickSwitchToggle();
        }

    } catch (error) {
        console.warn('Failed to update connection indicator:', error);
    }
}

/**
 * Render Quick Switch submenu with agents (max 20, scrollable, with Show All for overflow)
 */
function renderQuickSwitchMenu(container, agents, isLocal, activeAlias) {
    const MAX_INLINE_AGENTS = 20;
    const hasOverflow = agents.length > MAX_INLINE_AGENTS;
    const displayAgents = hasOverflow ? agents.slice(0, MAX_INLINE_AGENTS) : agents;

    let html = '';

    // "Show All" link if overflow
    if (hasOverflow) {
        html += `
            <li>
                <a class="dropdown-item text-primary small" href="#" id="qs-show-all-link">
                    <i class="bi bi-list-ul me-1"></i>Show All (${agents.length})...
                </a>
            </li>
            <li><hr class="dropdown-divider my-1"></li>
        `;
    }

    // Scrollable container for agent list
    html += `<div class="qs-agent-list" style="max-height: 280px; overflow-y: auto;">`;

    // Local Daemon option
    html += `
        <a class="dropdown-item qs-item d-flex align-items-center py-1 ${isLocal ? 'active' : ''}" 
           href="#" data-quick-switch="local">
            <i class="bi bi-pc-display ${isLocal ? 'text-white' : 'text-success'} me-2" style="font-size: 0.85rem;"></i>
            <span class="flex-grow-1 text-truncate">Local</span>
            ${isLocal ? '<i class="bi bi-check-lg ms-2"></i>' : ''}
        </a>
    `;

    if (displayAgents.length > 0) {
        displayAgents.forEach(agent => {
            const isActive = !isLocal && agent.alias === activeAlias && agent.active;
            const isConnected = agent.connected;

            // Status indicator - small dot for connection status
            let statusDot = '';
            if (isConnected) {
                statusDot = '<span class="qs-status-dot bg-success"></span>';
            } else {
                statusDot = '<span class="qs-status-dot bg-secondary"></span>';
            }

            html += `
                <a class="dropdown-item qs-item d-flex align-items-center py-1 ${isActive ? 'active' : ''}" 
                   href="#" data-quick-switch="${agent.alias}">
                    ${statusDot}
                    <span class="flex-grow-1 text-truncate">${agent.alias}</span>
                    ${isActive ? '<i class="bi bi-check-lg ms-2"></i>' : ''}
                </a>
            `;
        });
    } else {
        html += `
            <div class="dropdown-item-text text-muted small py-1">
                <i class="bi bi-info-circle me-1"></i>No agents configured
            </div>
        `;
    }

    html += `</div>`; // Close scrollable container

    container.innerHTML = html;

    // Add CSS for Quick Switch styling if not already present
    if (!document.getElementById('qs-styles')) {
        const style = document.createElement('style');
        style.id = 'qs-styles';
        style.textContent = `
            /* Make connection dropdown wider */
            #connection-indicator .dropdown-menu {
                min-width: 220px;
            }
            
            /* Collapsible Quick Switch */
            .qs-collapsed {
                display: none;
            }
            .qs-expanded {
                display: block;
            }
            .qs-chevron {
                transition: transform 0.2s ease;
                font-size: 0.75rem;
            }
            .qs-chevron.rotated {
                transform: rotate(180deg);
            }
            
            /* Agent list styling */
            .qs-status-dot {
                width: 8px;
                height: 8px;
                border-radius: 50%;
                display: inline-block;
                margin-right: 8px;
                flex-shrink: 0;
            }
            .qs-item {
                font-size: 0.875rem;
                padding: 0.35rem 0.75rem !important;
                white-space: nowrap;
            }
            .qs-item:hover {
                background-color: rgba(255,255,255,0.1);
            }
            .qs-item.active {
                background-color: var(--bs-primary) !important;
            }
            .qs-agent-list {
                background: rgba(0,0,0,0.15);
                border-radius: 4px;
                margin: 0.25rem 0.5rem;
                padding: 0.25rem 0;
                overflow-x: hidden;
            }
            .qs-agent-list::-webkit-scrollbar {
                width: 4px;
            }
            .qs-agent-list::-webkit-scrollbar-thumb {
                background: rgba(255,255,255,0.2);
                border-radius: 2px;
            }
        `;
        document.head.appendChild(style);
    }

    // Attach click handlers for agent items
    container.querySelectorAll('[data-quick-switch]').forEach(item => {
        item.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const alias = item.dataset.quickSwitch;
            await handleQuickSwitch(alias);
        });
    });

    // Attach Show All handler if present
    const showAllLink = container.querySelector('#qs-show-all-link');
    if (showAllLink) {
        showAllLink.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            showAllAgentsModal(agents, isLocal, activeAlias);
        });
    }
}

/**
 * Setup Quick Switch toggle click handler for expand/collapse
 */
function setupQuickSwitchToggle() {
    const toggle = document.getElementById('quick-switch-toggle');
    const menu = document.getElementById('quick-switch-menu');
    const chevron = document.getElementById('qs-chevron');

    if (!toggle || !menu) return;

    // Remove existing handler and add new one
    toggle.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();

        const isCollapsed = menu.classList.contains('qs-collapsed');

        if (isCollapsed) {
            menu.classList.remove('qs-collapsed');
            menu.classList.add('qs-expanded');
            if (chevron) chevron.classList.add('rotated');
        } else {
            menu.classList.add('qs-collapsed');
            menu.classList.remove('qs-expanded');
            if (chevron) chevron.classList.remove('rotated');
        }
    };
}

/**
 * Show modal with all agents (for when there are >20)
 */
function showAllAgentsModal(agents, isLocal, activeAlias) {
    // Ensure modal exists
    ensureShowAllModalExists();

    const listContainer = document.getElementById('qs-all-agents-list');
    const searchInput = document.getElementById('qs-all-agents-search');

    if (!listContainer) return;

    // Render agents list
    renderAllAgentsList(listContainer, agents, isLocal, activeAlias, '');

    // Setup search filter
    if (searchInput) {
        searchInput.value = '';
        searchInput.oninput = () => {
            const filter = searchInput.value.toLowerCase();
            renderAllAgentsList(listContainer, agents, isLocal, activeAlias, filter);
        };
    }

    // Show modal
    const modalEl = document.getElementById('showAllAgentsModal');
    if (modalEl) {
        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        modal.show();
    }
}

/**
 * Render the full agents list in the Show All modal
 */
function renderAllAgentsList(container, agents, isLocal, activeAlias, filter) {
    let html = '';

    // Local option (always show unless filtered out)
    if ('local'.includes(filter)) {
        html += `
            <a class="list-group-item list-group-item-action d-flex align-items-center ${isLocal ? 'active' : ''}"
               href="#" data-qs-modal-switch="local">
                <i class="bi bi-pc-display ${isLocal ? '' : 'text-success'} me-2"></i>
                <span class="flex-grow-1">Local Daemon</span>
                ${isLocal ? '<i class="bi bi-check-lg"></i>' : ''}
            </a>
        `;
    }

    // Filter and render agents
    agents.forEach(agent => {
        if (filter && !agent.alias.toLowerCase().includes(filter) &&
            !(agent.host && agent.host.toLowerCase().includes(filter))) {
            return;
        }

        const isActive = !isLocal && agent.alias === activeAlias && agent.active;
        const isConnected = agent.connected;

        const statusClass = isConnected ? 'text-success' : 'text-secondary';
        const statusDot = `<span class="badge rounded-pill ${isConnected ? 'bg-success' : 'bg-secondary'}" 
                                style="width: 8px; height: 8px; padding: 0;"></span>`;

        html += `
            <a class="list-group-item list-group-item-action d-flex align-items-center ${isActive ? 'active' : ''}"
               href="#" data-qs-modal-switch="${agent.alias}">
                ${statusDot}
                <span class="ms-2 flex-grow-1">
                    <strong>${agent.alias}</strong>
                    <small class="text-muted ms-2">${agent.host}:${agent.port}</small>
                </span>
                ${isActive ? '<i class="bi bi-check-lg"></i>' : ''}
            </a>
        `;
    });

    if (!html) {
        html = '<div class="text-center text-muted py-3">No matching agents</div>';
    }

    container.innerHTML = html;

    // Attach click handlers
    container.querySelectorAll('[data-qs-modal-switch]').forEach(item => {
        item.addEventListener('click', async (e) => {
            e.preventDefault();
            const alias = item.dataset.qsModalSwitch;

            // Hide modal first
            const modalEl = document.getElementById('showAllAgentsModal');
            if (modalEl) {
                const modal = bootstrap.Modal.getInstance(modalEl);
                if (modal) modal.hide();
            }

            await handleQuickSwitch(alias);
        });
    });
}

/**
 * Ensure the Show All modal exists in the DOM
 */
function ensureShowAllModalExists() {
    if (document.getElementById('showAllAgentsModal')) return;

    const modalHtml = `
    <div class="modal fade" id="showAllAgentsModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title"><i class="bi bi-hdd-network me-2"></i>All Agents</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body p-0">
                    <div class="p-2 border-bottom">
                        <input type="text" class="form-control form-control-sm" 
                               id="qs-all-agents-search" placeholder="Search agents...">
                    </div>
                    <div class="list-group list-group-flush" id="qs-all-agents-list" 
                         style="max-height: 400px; overflow-y: auto;">
                        <!-- Populated dynamically -->
                    </div>
                </div>
                <div class="modal-footer justify-content-between">
                    <a href="/control-center" class="btn btn-outline-secondary btn-sm">
                        <i class="bi bi-gear me-1"></i>Control Center
                    </a>
                    <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Close</button>
                </div>
            </div>
        </div>
    </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

/**
 * Handle Quick Switch click
 * @param {string} alias - Agent alias or 'local'
 */
async function handleQuickSwitch(alias) {
    // Switch to local - no password needed
    if (alias === 'local') {
        try {
            const result = await api.switchAgent('local');
            if (result.success) {
                showSuccess('Switched to Local Daemon');
                await updateConnectionIndicator();
                if (onSwitchSuccessCallback) {
                    await onSwitchSuccessCallback();
                }
            } else {
                showError(result.error || 'Failed to switch to local');
            }
        } catch (error) {
            showError('Network error while switching');
        }
        return;
    }

    // Check if agent is already connected and active
    try {
        const listResult = await api.listAgents();
        if (listResult.success) {
            const agent = listResult.connections?.find(c => c.alias === alias);

            if (agent?.connected && agent?.active) {
                showSuccess(`Already connected to ${alias}`);
                return;
            }

            // If connected but not active, just switch
            if (agent?.connected) {
                const switchResult = await api.switchAgent(alias);
                if (switchResult.success) {
                    showSuccess(`Switched to ${alias}`);
                    await updateConnectionIndicator();
                    if (onSwitchSuccessCallback) {
                        await onSwitchSuccessCallback();
                    }
                    return;
                }
            }

            // Need to connect - check vault for password
            const savedPassword = await vault.getPassword(alias);

            if (savedPassword) {
                // Try to connect with saved password
                const connectResult = await api.connectAgent(alias, savedPassword);

                if (connectResult.success) {
                    // Connected, now switch
                    const switchResult = await api.switchAgent(alias);
                    if (switchResult.success) {
                        showSuccess(`Connected and switched to ${alias}`);
                        await updateConnectionIndicator();
                        if (onSwitchSuccessCallback) {
                            await onSwitchSuccessCallback();
                        }
                        return;
                    } else {
                        showPasswordModal(alias, switchResult.error || 'Failed to switch after connect');
                    }
                } else {
                    // Connection failed - show password modal with error
                    showPasswordModal(alias, connectResult.error || 'Authentication failed');
                }
            } else {
                // No saved password - show password modal
                showPasswordModal(alias, null);
            }
        }
    } catch (error) {
        // Any error - show password modal with error
        showPasswordModal(alias, error.message || 'Connection error');
    }
}

/**
 * Show password modal for manual entry
 * @param {string} alias - Agent alias
 * @param {string|null} errorMessage - Error message to display, or null for fresh prompt
 */
function showPasswordModal(alias, errorMessage) {
    pendingQuickSwitch = alias;

    // Ensure modal exists
    ensurePasswordModalExists();

    const nameEl = document.getElementById('qs-agent-name');
    const passwordField = document.getElementById('qs-password');
    const errorDiv = document.getElementById('qs-error');
    const saveCheckbox = document.getElementById('qs-save-password');

    if (nameEl) nameEl.textContent = alias;
    if (passwordField) passwordField.value = '';
    if (saveCheckbox) saveCheckbox.checked = false;

    if (errorDiv) {
        if (errorMessage) {
            errorDiv.textContent = errorMessage;
            errorDiv.style.display = 'block';
        } else {
            errorDiv.style.display = 'none';
        }
    }

    // Reset submit button
    const submitBtn = document.getElementById('qs-submit-btn');
    if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="bi bi-plug-fill"></i> Connect & Switch';
    }

    if (!passwordModal) {
        const modalEl = document.getElementById('quickSwitchPasswordModal');
        if (modalEl) {
            passwordModal = new bootstrap.Modal(modalEl);
        }
    }

    if (passwordModal) {
        passwordModal.show();
        setTimeout(() => {
            if (passwordField) passwordField.focus();
        }, 300);
    }
}

/**
 * Ensure the password modal exists in the DOM
 */
function ensurePasswordModalExists() {
    if (document.getElementById('quickSwitchPasswordModal')) return;

    const modalHtml = `
    <div class="modal fade" id="quickSwitchPasswordModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered modal-sm">
            <div class="modal-content">
                <div class="modal-header bg-primary text-white">
                    <h5 class="modal-title"><i class="bi bi-hdd-network me-2"></i>Quick Switch</h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <p class="small mb-2">Connect to <strong id="qs-agent-name"></strong></p>
                    <div class="alert alert-danger small py-2" id="qs-error" style="display: none;"></div>
                    <div class="mb-3">
                        <input type="password" class="form-control" id="qs-password" placeholder="Password">
                    </div>
                    <div class="form-check">
                        <input type="checkbox" class="form-check-input" id="qs-save-password">
                        <label class="form-check-label small" for="qs-save-password">
                            <i class="bi bi-safe"></i> Save to vault
                        </label>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancel</button>
                    <button type="button" class="btn btn-primary btn-sm" id="qs-submit-btn">
                        <i class="bi bi-plug-fill"></i> Connect & Switch
                    </button>
                </div>
            </div>
        </div>
    </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);
    setupPasswordModalHandlers();
}

/**
 * Setup password modal event handlers
 */
function setupPasswordModalHandlers() {
    const submitBtn = document.getElementById('qs-submit-btn');
    const passwordField = document.getElementById('qs-password');

    if (submitBtn) {
        // Remove existing handlers
        const newBtn = submitBtn.cloneNode(true);
        submitBtn.parentNode.replaceChild(newBtn, submitBtn);

        newBtn.addEventListener('click', handlePasswordSubmit);
    }

    if (passwordField) {
        passwordField.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                handlePasswordSubmit();
            }
        });
    }
}

/**
 * Handle password modal submit
 */
async function handlePasswordSubmit() {
    const password = document.getElementById('qs-password')?.value;
    const errorDiv = document.getElementById('qs-error');
    const submitBtn = document.getElementById('qs-submit-btn');
    const saveCheckbox = document.getElementById('qs-save-password');

    if (!password) {
        if (errorDiv) {
            errorDiv.textContent = 'Password is required';
            errorDiv.style.display = 'block';
        }
        return;
    }

    if (!pendingQuickSwitch) return;

    // Show loading state
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Connecting...';
    }

    try {
        const connectResult = await api.connectAgent(pendingQuickSwitch, password);

        if (connectResult.success) {
            // Save password if checkbox checked
            if (saveCheckbox?.checked) {
                await vault.savePassword(pendingQuickSwitch, password);
            }

            // Now switch to this agent
            const switchResult = await api.switchAgent(pendingQuickSwitch);

            if (switchResult.success) {
                if (passwordModal) passwordModal.hide();
                showSuccess(`Connected and switched to ${pendingQuickSwitch}`);
                await updateConnectionIndicator();
                if (onSwitchSuccessCallback) {
                    await onSwitchSuccessCallback();
                }
            } else {
                if (errorDiv) {
                    errorDiv.textContent = switchResult.error || 'Failed to switch';
                    errorDiv.style.display = 'block';
                }
            }
        } else {
            if (errorDiv) {
                errorDiv.textContent = connectResult.error || 'Connection failed';
                errorDiv.style.display = 'block';
            }
        }
    } catch (error) {
        if (errorDiv) {
            errorDiv.textContent = error.message || 'Network error';
            errorDiv.style.display = 'block';
        }
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="bi bi-plug-fill"></i> Connect & Switch';
        }
    }
}
