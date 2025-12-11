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
 * 
 * IMPORTANT: This uses a DEDICATED #confirmModal element, NOT #actionModal.
 * This prevents conflicts when confirmations are needed during other modal operations.
 * DO NOT change this to use #actionModal - it will cause modal state machine conflicts!
 * 
 * ROOT CAUSE FIX: The Promise only resolves AFTER the modal animation fully completes
 * (on 'hidden.bs.modal' event), not on button click. This ensures sequential showConfirmModal
 * calls work correctly by waiting for animation to finish before the next modal opens.
 * 
 * @param {string} title - Modal title
 * @param {string} htmlMessage - Message body (HTML allowed)
 * @param {string} confirmBtnText - Text for confirm button
 * @param {string} confirmBtnClass - Class for confirm button (e.g., 'btn-danger', 'btn-primary')
 * @returns {Promise<boolean>} - Resolves to true if confirmed, false otherwise.
 */
export function showConfirmModal(title, htmlMessage, confirmBtnText = "Confirm", confirmBtnClass = "btn-primary") {
    return new Promise((resolve) => {
        // Check if confirm modal elements exist
        if (!dom.confirmModal || !dom.confirmModalBody || !dom.confirmModalLabel || !dom.confirmModalConfirmBtn) {
            console.error('Confirm modal elements not found! Falling back to window.confirm.');
            resolve(window.confirm(title + '\n\n' + htmlMessage.replace(/<[^>]*>/g, '')));
            return;
        }

        // Track whether user confirmed (default: false for cancel/dismiss)
        let userConfirmed = false;

        // Set modal content
        dom.confirmModalLabel.textContent = title;
        dom.confirmModalBody.innerHTML = htmlMessage;

        // Update confirm button text and class
        dom.confirmModalConfirmBtn.textContent = confirmBtnText;
        dom.confirmModalConfirmBtn.className = `btn ${confirmBtnClass}`;

        // Confirm button handler - just record choice and close modal
        const handleConfirm = () => {
            userConfirmed = true;
            dom.confirmModal.hide(); // This triggers hidden.bs.modal
        };

        // Hidden event handler - resolve Promise AFTER animation completes
        const handleHidden = () => {
            // Cleanup listeners
            dom.confirmModalConfirmBtn.removeEventListener('click', handleConfirm);
            dom.confirmModalElement.removeEventListener('hidden.bs.modal', handleHidden);

            // Resolve with result AFTER modal is fully hidden
            resolve(userConfirmed);
        };

        // Attach listeners
        dom.confirmModalConfirmBtn.addEventListener('click', handleConfirm);
        dom.confirmModalElement.addEventListener('hidden.bs.modal', handleHidden, { once: true });

        // Show the modal
        dom.confirmModal.show();
    });
}

/**
 * Show a modal with three choices: Option A, Option B, and Cancel.
 * Uses the action modal to allow custom footer with three buttons.
 * 
 * @param {string} title - Modal title
 * @param {string} htmlMessage - Message body (HTML allowed)
 * @param {string} optionAText - Text for first option button
 * @param {string} optionAClass - Class for first option button (e.g., 'btn-warning')
 * @param {string} optionBText - Text for second option button
 * @param {string} optionBClass - Class for second option button (e.g., 'btn-danger')
 * @returns {Promise<string|null>} - Resolves to 'optionA', 'optionB', or null if cancelled
 */
export function showTripleChoiceModal(title, htmlMessage, optionAText, optionAClass, optionBText, optionBClass) {
    return new Promise((resolve) => {
        // Check if action modal elements exist
        if (!dom.actionModal || !dom.actionModalBody || !dom.actionModalLabel || !dom.actionModalFooter) {
            console.error('Action modal elements not found!');
            resolve(null);
            return;
        }

        // Track user choice (null = cancelled)
        let userChoice = null;

        // Set modal content
        dom.actionModalLabel.textContent = title;
        dom.actionModalBody.innerHTML = htmlMessage;

        // Create three-button footer
        dom.actionModalFooter.innerHTML = `
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn ${optionBClass}" id="tripleChoiceBtnB">${optionBText}</button>
            <button type="button" class="btn ${optionAClass}" id="tripleChoiceBtnA">${optionAText}</button>
        `;

        const btnA = document.getElementById('tripleChoiceBtnA');
        const btnB = document.getElementById('tripleChoiceBtnB');

        // Button handlers
        const handleOptionA = () => {
            userChoice = 'optionA';
            dom.actionModal.hide();
        };

        const handleOptionB = () => {
            userChoice = 'optionB';
            dom.actionModal.hide();
        };

        // Hidden event handler - resolve Promise AFTER animation completes
        const handleHidden = () => {
            // Cleanup listeners
            if (btnA) btnA.removeEventListener('click', handleOptionA);
            if (btnB) btnB.removeEventListener('click', handleOptionB);
            dom.modalElement.removeEventListener('hidden.bs.modal', handleHidden);

            // Resolve with result AFTER modal is fully hidden
            resolve(userChoice);
        };

        // Attach listeners
        if (btnA) btnA.addEventListener('click', handleOptionA);
        if (btnB) btnB.addEventListener('click', handleOptionB);
        dom.modalElement.addEventListener('hidden.bs.modal', handleHidden, { once: true });

        // Show the modal
        dom.actionModal.show();
    });
}

/**
 * Show an input modal that replaces native prompt() dialogs.
 * Uses the action modal with an input field.
 * 
 * @param {string} title - Modal title
 * @param {string} htmlMessage - Message/label HTML above the input
 * @param {string} defaultValue - Default value for the input field
 * @param {string} placeholder - Placeholder text for input field
 * @param {string} confirmBtnText - Text for confirm button
 * @param {string} confirmBtnClass - Class for confirm button
 * @returns {Promise<string|null>} - Resolves to input value (trimmed) or null if cancelled
 */
export function showInputModal(title, htmlMessage, defaultValue = '', placeholder = '', confirmBtnText = 'OK', confirmBtnClass = 'btn-primary') {
    return new Promise((resolve) => {
        // Check if action modal elements exist
        if (!dom.actionModal || !dom.actionModalBody || !dom.actionModalLabel || !dom.actionModalFooter) {
            console.error('Action modal elements not found! Falling back to window.prompt.');
            resolve(window.prompt(htmlMessage.replace(/<[^>]*>/g, ''), defaultValue));
            return;
        }

        // Track user input (null = cancelled)
        let userInput = null;

        // Set modal content with input field
        dom.actionModalLabel.textContent = title;
        dom.actionModalBody.innerHTML = `
            <div class="mb-3">
                ${htmlMessage}
            </div>
            <input type="text" class="form-control" id="inputModalField" 
                   value="${escapeHtmlForModal(defaultValue)}" 
                   placeholder="${escapeHtmlForModal(placeholder)}">
        `;

        // Create footer
        dom.actionModalFooter.innerHTML = `
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn ${confirmBtnClass}" id="inputModalConfirmBtn">${confirmBtnText}</button>
        `;

        const inputField = document.getElementById('inputModalField');
        const confirmBtn = document.getElementById('inputModalConfirmBtn');

        // Confirm button handler
        const handleConfirm = () => {
            userInput = inputField ? inputField.value.trim() : '';
            dom.actionModal.hide();
        };

        // Handle Enter key in input field
        const handleKeydown = (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                handleConfirm();
            }
        };

        // Hidden event handler - resolve Promise AFTER animation completes
        const handleHidden = () => {
            // Cleanup listeners
            if (confirmBtn) confirmBtn.removeEventListener('click', handleConfirm);
            if (inputField) inputField.removeEventListener('keydown', handleKeydown);
            dom.modalElement.removeEventListener('hidden.bs.modal', handleHidden);

            // Resolve with result AFTER modal is fully hidden
            resolve(userInput);
        };

        // Attach listeners
        if (confirmBtn) confirmBtn.addEventListener('click', handleConfirm);
        if (inputField) inputField.addEventListener('keydown', handleKeydown);
        dom.modalElement.addEventListener('hidden.bs.modal', handleHidden, { once: true });

        // Show the modal and focus input
        dom.actionModal.show();

        // Focus input after modal is shown
        dom.modalElement.addEventListener('shown.bs.modal', () => {
            if (inputField) {
                inputField.focus();
                inputField.select();
            }
        }, { once: true });
    });
}
