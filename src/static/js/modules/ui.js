/**
 * ui.js - UI Update Functions
 * 
 * Functions for updating UI state, status indicators, and modal dialogs.
 */

import dom from './dom-elements.js';

/**
 * ARIA-HIDDEN FIX: When a modal starts hiding, Bootstrap sets aria-hidden="true" 
 * before focus leaves the modal. This causes a browser warning. 
 * Fix: blur any focused element before the hide animation starts.
 * Using capture phase to ensure we run before Bootstrap's handlers.
 */
document.addEventListener('hide.bs.modal', (event) => {
    // Blur focused element within modal
    const modal = event.target;
    const focusedElement = modal.querySelector(':focus');
    if (focusedElement) {
        focusedElement.blur();
    }
    // Also blur document active element as fallback
    if (document.activeElement && modal.contains(document.activeElement)) {
        document.activeElement.blur();
    }
}, true); // Capture phase for earlier execution

/**
 * Create a dynamically stacked modal that can overlay other modals.
 * 
 * This creates a new modal DOM element on the fly, allowing unlimited modal stacking.
 * The modal is automatically cleaned up (removed from DOM) when closed.
 * 
 * @param {object} config - Modal configuration
 * @param {string} config.title - Modal title
 * @param {string} config.bodyHtml - Modal body HTML content
 * @param {string} config.footerHtml - Modal footer HTML content
 * @param {number} config.zIndex - Z-index for stacking (default: auto-calculated)
 * @param {string} config.size - Modal size: 'sm', 'lg', 'xl' (default: normal)
 * @returns {object} - { element, modal, show(), hide() }
 */
export function createStackableModal(config) {
    const { title, bodyHtml, footerHtml, zIndex, size } = config;

    // Create unique ID
    const modalId = `stackable-modal-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    // Auto-calculate z-index if not provided (based on existing open modals)
    const existingModals = document.querySelectorAll('.modal.show');
    const calculatedZIndex = zIndex ?? (1055 + ((existingModals.length + 1) * 10));

    // Determine size class
    const sizeClass = size ? `modal-${size}` : '';

    // Create modal element
    const modalEl = document.createElement('div');
    modalEl.id = modalId;
    modalEl.className = 'modal fade';
    modalEl.tabIndex = -1;
    modalEl.setAttribute('aria-labelledby', `${modalId}-label`);
    modalEl.setAttribute('aria-hidden', 'true');
    // SECURITY NOTE: This is an internal API - all callers pass trusted, pre-sanitized HTML.
    // The bodyHtml and footerHtml parameters come from internal module calls, not user input.
    // lgtm[js/xss-through-dom]
    modalEl.innerHTML = `
        <div class="modal-dialog modal-dialog-centered ${sizeClass}">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="${modalId}-label">${title}</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">${bodyHtml}</div>
                <div class="modal-footer">${footerHtml}</div>
            </div>
        </div>
    `;

    // Append to body
    document.body.appendChild(modalEl);

    // Create Bootstrap modal instance
    const bsModal = new bootstrap.Modal(modalEl);

    // Set up z-index and backdrop handling when shown
    modalEl.addEventListener('shown.bs.modal', () => {
        modalEl.style.zIndex = calculatedZIndex.toString();

        // Find and raise the backdrop z-index
        const backdrops = document.querySelectorAll('.modal-backdrop');
        if (backdrops.length > 0) {
            backdrops[backdrops.length - 1].style.zIndex = (calculatedZIndex - 1).toString();
        }
    }, { once: true });

    // Clean up on close: dispose modal and remove element from DOM
    modalEl.addEventListener('hidden.bs.modal', () => {
        bsModal.dispose();
        modalEl.remove();
    }, { once: true });

    return {
        element: modalEl,
        modal: bsModal,
        show: () => bsModal.show(),
        hide: () => bsModal.hide()
    };
}

/**
 * Set loading state for the application
 * @param {boolean} isLoading - Whether app is loading
 */
export function setLoadingState(isLoading) {
    if (dom.refreshButton) {
        dom.refreshButton.disabled = isLoading;
    }

    if (isLoading) {
        if (dom.statusIndicator) {
            dom.statusIndicator.innerHTML = `<span class="spinner-border spinner-border-sm text-light" role="status" aria-hidden="true"></span> Loading...`;
        }
        if (dom.zfsTree) {
            dom.zfsTree.innerHTML = `<div class="text-center p-3"><span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading...</div>`;
        }
        // Disable action buttons in Pool and Dataset menus while loading
        document.querySelectorAll('#poolDropdown + .dropdown-menu .dropdown-item, #datasetDropdown + .dropdown-menu .dropdown-item').forEach(btn => btn.classList.add('disabled'));
    } else {
        if (dom.statusIndicator) {
            dom.statusIndicator.textContent = 'Idle';
        }
    }
}

/**
 * Update status indicator
 * @param {string} message - Status message
 * @param {string} type - Status type: 'info', 'busy', 'success', 'error'
 */
export function updateStatus(message, type = 'info') {
    if (!dom.statusIndicator) return;

    let indicatorClass = 'text-light';
    let indicatorIcon = '';

    if (type === 'busy') {
        indicatorClass = 'text-warning';
        indicatorIcon = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> `;
    } else if (type === 'success') {
        indicatorClass = 'text-success';
    } else if (type === 'error') {
        indicatorClass = 'text-danger';
    }

    dom.statusIndicator.className = `navbar-text me-2 ${indicatorClass}`;
    dom.statusIndicator.innerHTML = `${indicatorIcon}${message}`;

    // Clear status after a delay for success/error/info messages
    if (type === 'success' || type === 'error' || type === 'info') {
        setTimeout(() => {
            if (dom.statusIndicator.innerHTML.includes(message)) {
                dom.statusIndicator.textContent = 'Idle';
                dom.statusIndicator.className = 'navbar-text me-2 text-light';
            }
        }, 5000);
    }
}

/**
 * Show modal dialog
 * @param {string} title - Modal title
 * @param {string} bodyHtml - Modal body HTML content
 * @param {Function|null} onConfirm - Callback for confirm button
 * @param {object} options - Additional options: size, footerHtml, setupFunc, onConfirmAll
 */
export function showModal(title, bodyHtml, onConfirm, options = {}) {
    if (!dom.actionModal || !dom.actionModalBody || !dom.actionModalLabel || !dom.actionModalFooter) {
        console.error("Modal elements not found!");
        console.error("Modal Error - Modal elements not found!");
        return;
    }

    dom.actionModalLabel.textContent = title;
    dom.actionModalBody.innerHTML = bodyHtml;

    const modalDialog = dom.modalElement.querySelector('.modal-dialog');
    if (modalDialog) {
        modalDialog.classList.remove('modal-lg', 'modal-xl', 'modal-sm');
        if (options.size) {
            modalDialog.classList.add(`modal-${options.size}`);
        } else {
            modalDialog.classList.add('modal-lg');
        }
    } else {
        console.error("Modal dialog element not found!");
        console.error("Modal Error - Modal dialog element not found!");
        return;
    }

    // Clone and replace confirm button to remove old event listeners
    const oldConfirmButton = document.getElementById('actionModalConfirmButton');
    if (oldConfirmButton) {
        oldConfirmButton.replaceWith(oldConfirmButton.cloneNode(true));
    }

    if (options.footerHtml) {
        dom.actionModalFooter.innerHTML = options.footerHtml;
        const newConfirmButton = document.getElementById('actionModalConfirmButton');
        if (newConfirmButton && onConfirm) {
            newConfirmButton.addEventListener('click', onConfirm);
        }
        // Handle potential other buttons in custom footer
        const newImportAllButton = document.getElementById('importModalConfirmAllButton');
        if (newImportAllButton && options.onConfirmAll) {
            newImportAllButton.addEventListener('click', options.onConfirmAll);
        }
    } else {
        dom.actionModalFooter.innerHTML = `
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="actionModalConfirmButton">Confirm</button>`;
        const defaultConfirmButton = document.getElementById('actionModalConfirmButton');
        if (defaultConfirmButton && onConfirm) {
            defaultConfirmButton.addEventListener('click', onConfirm);
        } else if (defaultConfirmButton) {
            defaultConfirmButton.disabled = true;
        }
    }

    if (options.setupFunc && typeof options.setupFunc === 'function') {
        try {
            options.setupFunc();
        } catch (e) {
            console.error("Error in modal setup function:", e);
            dom.actionModalBody.innerHTML += `<div class="alert alert-danger mt-2">Error setting up modal: ${e.message}</div>`;
        }
    }

    dom.actionModal.show();
}

/**
 * Hide the action modal
 */
export function hideModal() {
    if (dom.actionModal) {
        dom.actionModal.hide();
    }
}

/**
 * Show error alert to user using a dedicated error modal with copyable text.
 * This uses a separate modal from the action modal to avoid conflicts.
 * @param {string} title - Alert title
 * @param {string} message - Alert message (can be multi-line)
 */
export function showErrorAlert(title, message) {
    // Ensure message is a string
    const msgStr = String(message || 'Unknown error');
    const titleStr = String(title || 'Error');

    // Check if error modal elements exist
    if (!dom.errorModal || !dom.errorModalBody || !dom.errorModalLabel) {
        console.error('Error modal elements not found! Falling back to console.');
        console.error(`${titleStr}: ${msgStr}`);
        return;
    }

    try {
        // Update title
        dom.errorModalLabel.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-2"></i>${escapeHtmlForModal(titleStr)}`;

        // Escape message for safe HTML display, then convert newlines to <br>
        const escapedMessage = msgStr
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\n/g, '<br>');

        // Escape for pre block (preserve newlines as text)
        const preContent = `${titleStr}\n\n${msgStr}`
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        dom.errorModalBody.innerHTML = `
            <p>${escapedMessage}</p>
            <hr>
            <details>
                <summary class="text-muted small">Copy Error Details</summary>
                <pre class="bg-dark text-light p-2 mt-2 rounded" style="white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow-y: auto; user-select: text;">${preContent}</pre>
            </details>
        `;

        // Show the error modal
        dom.errorModal.show();

        // Fix z-index for proper stacking when shown over actionModal
        dom.errorModalElement.addEventListener('shown.bs.modal', () => {
            dom.errorModalElement.style.zIndex = '1060';
            const backdrops = document.querySelectorAll('.modal-backdrop');
            if (backdrops.length > 1) {
                backdrops[backdrops.length - 1].style.zIndex = '1059';
            }
        }, { once: true });
    } catch (e) {
        console.error('showErrorAlert failed:', e);
        console.error(`${titleStr}: ${msgStr}`);
    }
}

/**
 * Helper to escape HTML for modal content
 */
function escapeHtmlForModal(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Show/hide details tab content area
 * @param {boolean} visible - Whether to show
 */
export function setDetailsVisible(visible) {
    if (dom.detailsTabContent) {
        dom.detailsTabContent.style.visibility = visible ? 'visible' : 'hidden';
        dom.detailsTabContent.style.opacity = visible ? '1' : '0';
    }
}

/**
 * Set details title text
 * @param {string} text - Title text
 */
export function setDetailsTitle(text) {
    if (dom.detailsTitle) {
        dom.detailsTitle.textContent = text;
    }
}

/**
 * Enable/disable a tab button
 * @param {string} tabId - Tab button ID
 * @param {boolean} disabled - Whether to disable
 */
export function setTabDisabled(tabId, disabled) {
    const tabButton = document.getElementById(tabId);
    if (tabButton) {
        tabButton.disabled = disabled;
    }
}

/**
 * Activate a specific tab
 * @param {string} tabId - Tab button ID
 */
export function activateTab(tabId) {
    const tabButton = document.getElementById(tabId);
    if (tabButton && !tabButton.disabled) {
        const tabInstance = bootstrap.Tab.getOrCreateInstance(tabButton);
        if (tabInstance) {
            tabInstance.show();
        }
    }
}

/**
 * Get the currently active tab ID
 * @returns {string|null} - Active tab button ID
 */
export function getActiveTabId() {
    const activeTabEl = document.querySelector('#details-tab .nav-link.active');
    return activeTabEl ? activeTabEl.id : null;
}

/**
 * Show a confirmation modal and wait for user response.
 * Uses a dynamically created stackable modal to allow proper stacking over other modals.
 * 
 * @param {string} title - Modal title
 * @param {string} htmlMessage - Message body (HTML allowed)
 * @param {string} confirmBtnText - Text for confirm button
 * @param {string} confirmBtnClass - Class for confirm button (e.g., 'btn-danger', 'btn-primary')
 * @param {number} zIndex - Optional z-index for stacking (auto-calculated if not provided)
 * @returns {Promise<boolean>} - Resolves to true if confirmed, false otherwise.
 */
export function showConfirmModal(title, htmlMessage, confirmBtnText = "Confirm", confirmBtnClass = "btn-primary", zIndex = null) {
    return new Promise((resolve) => {
        // Track whether user confirmed (default: false for cancel/dismiss)
        let userConfirmed = false;

        // Create footer with cancel and confirm buttons
        const footerHtml = `
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn ${confirmBtnClass}" id="stackableConfirmBtn">${confirmBtnText}</button>
        `;

        // Create dynamic stackable modal
        const stackable = createStackableModal({
            title,
            bodyHtml: htmlMessage,
            footerHtml,
            zIndex
        });

        const confirmBtn = stackable.element.querySelector('#stackableConfirmBtn');

        // Confirm button handler
        const handleConfirm = () => {
            userConfirmed = true;
            stackable.hide();
        };

        // Hidden event handler - resolve Promise AFTER animation completes
        stackable.element.addEventListener('hidden.bs.modal', () => {
            resolve(userConfirmed);
        }, { once: true });

        // Attach listener
        if (confirmBtn) confirmBtn.addEventListener('click', handleConfirm);

        // Show the modal
        stackable.show();
    });
}

/**
 * Show a modal with three choices: Option A, Option B, and Cancel.
 * Uses a dynamically created stackable modal to allow proper stacking over other modals.
 * 
 * @param {string} title - Modal title
 * @param {string} htmlMessage - Message body (HTML allowed)
 * @param {string} optionAText - Text for first option button
 * @param {string} optionAClass - Class for first option button (e.g., 'btn-warning')
 * @param {string} optionBText - Text for second option button
 * @param {string} optionBClass - Class for second option button (e.g., 'btn-danger')
 * @param {number} zIndex - Optional z-index for stacking (auto-calculated if not provided)
 * @returns {Promise<string|null>} - Resolves to 'optionA', 'optionB', or null if cancelled
 */
export function showTripleChoiceModal(title, htmlMessage, optionAText, optionAClass, optionBText, optionBClass, zIndex = null) {
    return new Promise((resolve) => {
        // Track user choice (null = cancelled)
        let userChoice = null;

        // Create footer with three buttons
        const footerHtml = `
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn ${optionBClass}" id="tripleChoiceBtnB">${optionBText}</button>
            <button type="button" class="btn ${optionAClass}" id="tripleChoiceBtnA">${optionAText}</button>
        `;

        // Create dynamic stackable modal
        const stackable = createStackableModal({
            title,
            bodyHtml: htmlMessage,
            footerHtml,
            zIndex
        });

        const btnA = stackable.element.querySelector('#tripleChoiceBtnA');
        const btnB = stackable.element.querySelector('#tripleChoiceBtnB');

        // Button handlers
        const handleOptionA = () => {
            userChoice = 'optionA';
            stackable.hide();
        };

        const handleOptionB = () => {
            userChoice = 'optionB';
            stackable.hide();
        };

        // Hidden event handler - resolve Promise AFTER animation completes
        stackable.element.addEventListener('hidden.bs.modal', () => {
            resolve(userChoice);
        }, { once: true });

        // Attach listeners
        if (btnA) btnA.addEventListener('click', handleOptionA);
        if (btnB) btnB.addEventListener('click', handleOptionB);

        // Show the modal
        stackable.show();
    });
}

/**
 * Show an input modal that replaces native prompt() dialogs.
 * Uses a dynamically created stackable modal to allow proper stacking over other modals.
 * 
 * @param {string} title - Modal title
 * @param {string} htmlMessage - Message/label HTML above the input
 * @param {string} defaultValue - Default value for the input field
 * @param {string} placeholder - Placeholder text for input field
 * @param {string} confirmBtnText - Text for confirm button
 * @param {string} confirmBtnClass - Class for confirm button
 * @param {number} zIndex - Optional z-index for stacking (auto-calculated if not provided)
 * @returns {Promise<string|null>} - Resolves to input value (trimmed) or null if cancelled
 */
export function showInputModal(title, htmlMessage, defaultValue = '', placeholder = '', confirmBtnText = 'OK', confirmBtnClass = 'btn-primary', zIndex = null) {
    return new Promise((resolve) => {
        // Track user input (null = cancelled)
        let userInput = null;

        // Create body with input field
        const bodyHtml = `
            <div class="mb-3">
                ${htmlMessage}
            </div>
            <input type="text" class="form-control" id="stackableInputField" 
                   value="${escapeHtmlForModal(defaultValue)}" 
                   placeholder="${escapeHtmlForModal(placeholder)}">
        `;

        // Create footer
        const footerHtml = `
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn ${confirmBtnClass}" id="stackableInputConfirmBtn">${confirmBtnText}</button>
        `;

        // Create dynamic stackable modal
        const stackable = createStackableModal({
            title,
            bodyHtml,
            footerHtml,
            zIndex
        });

        const inputField = stackable.element.querySelector('#stackableInputField');
        const confirmBtn = stackable.element.querySelector('#stackableInputConfirmBtn');

        // Confirm button handler
        const handleConfirm = () => {
            userInput = inputField ? inputField.value.trim() : '';
            stackable.hide();
        };

        // Handle Enter key in input field
        const handleKeydown = (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                handleConfirm();
            }
        };

        // Hidden event handler - resolve Promise AFTER animation completes
        stackable.element.addEventListener('hidden.bs.modal', () => {
            resolve(userInput);
        }, { once: true });

        // Attach listeners
        if (confirmBtn) confirmBtn.addEventListener('click', handleConfirm);
        if (inputField) inputField.addEventListener('keydown', handleKeydown);

        // Show the modal
        stackable.show();

        // Focus input after modal is shown
        stackable.element.addEventListener('shown.bs.modal', () => {
            if (inputField) {
                inputField.focus();
                inputField.select();
            }
        }, { once: true });
    });
}

/**
 * Show daemon disconnected overlay.
 * Creates a full-page overlay blocking the UI when daemon connection is lost.
 * @param {string} message - Error message to display
 * @param {Function} onReconnect - Callback function when Reconnect button is clicked
 * @param {object} options - title, showDaemonHelp, showSwitchAgentButton
 */
export function showDaemonDisconnectedOverlay(message, onReconnect = null, options = {}) {
    const {
        title = 'Daemon Connection Lost',
        showDaemonHelp = true,
        showSwitchAgentButton = false,
        reconnectButtonText = 'Reconnect'
    } = options;

    // Check if overlay already exists - update message if so
    const existingOverlay = document.getElementById('daemon-disconnected-overlay');
    if (existingOverlay) {
        const msgEl = existingOverlay.querySelector('.daemon-error-message');
        if (msgEl) {
            msgEl.textContent = message;
        }
        // Update title if changed
        const titleEl = existingOverlay.querySelector('.daemon-overlay-title');
        if (titleEl) titleEl.textContent = title;

        return;
    }

    const overlay = document.createElement('div');
    overlay.id = 'daemon-disconnected-overlay';
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.85);
        z-index: 9999;
        display: flex;
        align-items: center;
        justify-content: center;
    `;

    const helpHtml = showDaemonHelp ? `
                <p style="color: #555; font-size: 0.95rem; margin-bottom: 1rem;">
                    Click <strong style="color: #6a64e8;">Reconnect</strong> to try again, or start the daemon:
                </p>
                <div class="mb-4 p-3" style="background: #2d2d3a; border-radius: 8px; font-family: var(--bs-font-monospace); font-size: 0.85rem;">
                    <div style="color: #a0a0b0;">$ <span style="color: #fff;">zfdash --launch-daemon</span></div>
                    <div style="color: #777; font-size: 0.8rem; margin-top: 6px;">or: uv run src/main.py --launch-daemon</div>
                </div>`
        :
        `<p style="color: #555; font-size: 0.95rem; margin-bottom: 1rem;">
                    Click <strong style="color: #6a64e8;">Reconnect</strong> to try again.
                </p>`;

    // Switch Agent button for remote disconnections
    const switchAgentBtn = showSwitchAgentButton
        ? `<a href="/control-center" class="btn flex-fill py-2" 
               style="background: #f0f0f5; border-radius: 8px; color: #555; font-size: 0.95rem; text-decoration: none;">
               <i class="bi bi-hdd-network-fill me-1"></i>Switch Agent
           </a>`
        : `<button type="button" class="btn flex-fill py-2" onclick="location.reload()"
                style="background: #f0f0f5; border-radius: 8px; color: #555; font-size: 0.95rem;">
               <i class="bi bi-arrow-clockwise me-1"></i>Refresh
           </button>`;

    overlay.innerHTML = `
        <div class="card border-0" style="width: 440px; max-width: 95vw; margin: 20px; box-shadow: 0 10px 40px rgba(0,0,0,0.3); border-radius: 12px; overflow: hidden;">
            <div class="py-3 px-4" style="background: linear-gradient(135deg, #6a64e8 0%, #5752d6 100%);">
                <div class="d-flex align-items-center text-white">
                    <i class="bi bi-exclamation-triangle-fill me-2" style="font-size: 1.3rem;"></i>
                    <span class="daemon-overlay-title" style="font-weight: 600; font-size: 1.1rem;">${title}</span>
                </div>
            </div>
            <div class="px-4 py-4" style="background: #fff;">
                <div class="daemon-error-message mb-3 p-3" 
                     style="background: #f8f9fa; border-radius: 8px; font-family: var(--bs-font-monospace); font-size: 0.85rem; color: #dc3545; line-height: 1.4;">
                    ${escapeHtmlForModal(message)}
                </div>
                ${helpHtml}
                <div class="d-flex gap-2">
                    <button type="button" class="btn flex-fill text-white py-2" id="daemon-reconnect-btn" 
                            style="background: #6a64e8; border-radius: 8px; font-weight: 500; font-size: 0.95rem;">
                        <i class="bi bi-arrow-repeat me-1"></i>${reconnectButtonText}
                    </button>
                    ${switchAgentBtn}
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    // Attach reconnect handler
    const reconnectBtn = document.getElementById('daemon-reconnect-btn');
    if (reconnectBtn && onReconnect) {
        reconnectBtn.addEventListener('click', async () => {
            reconnectBtn.disabled = true;
            reconnectBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Connecting...';
            await onReconnect();
            reconnectBtn.disabled = false;
            reconnectBtn.innerHTML = `<i class="bi bi-arrow-repeat me-1"></i>${reconnectButtonText}`;
        });
    }
}

/**
 * Update the error message in the daemon disconnected overlay.
 * @param {string} message - New error message
 */
export function updateDaemonDisconnectedMessage(message) {
    const overlay = document.getElementById('daemon-disconnected-overlay');
    if (overlay) {
        const msgEl = overlay.querySelector('.daemon-error-message');
        if (msgEl) {
            msgEl.textContent = message;
        }
    }
}

/**
 * Hide daemon disconnected overlay if it exists.
 */
export function hideDaemonDisconnectedOverlay() {
    const overlay = document.getElementById('daemon-disconnected-overlay');
    if (overlay) {
        overlay.remove();
    }
}
