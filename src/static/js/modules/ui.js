/**
 * ui.js - UI Update Functions
 * 
 * Functions for updating UI state, status indicators, and modal dialogs.
 */

import dom from './dom-elements.js';

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
        alert("Modal Error - Check Console");
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
        alert("Modal Error - Check Console");
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
 * Show error alert to user
 * @param {string} title - Alert title
 * @param {string} message - Alert message
 */
export function showErrorAlert(title, message) {
    alert(`${title}\n\n${message}`);
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
