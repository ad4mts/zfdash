/**
 * notifications.js - Toast notification system for ZfDash
 * Replaces ugly browser alert() boxes with beautiful Bootstrap toasts.
 */

let toastContainer = null;

/**
 * Initialize the notification system.
 * Creates the toast container div if it doesn't exist.
 */
export function initNotifications() {
    if (!document.getElementById('toast-container')) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        toastContainer.style.zIndex = '1100';
        document.body.appendChild(toastContainer);
    } else {
        toastContainer = document.getElementById('toast-container');
    }
}

/**
 * Show a toast notification.
 * @param {string} message - The message to display
 * @param {string} type - 'success', 'error', 'warning', 'info'
 * @param {number} duration - How long to show the toast (ms)
 */
export function showToast(message, type = 'info', duration = 5000) {
    if (!toastContainer) {
        initNotifications();
    }

    const icons = {
        success: 'bi-check-circle-fill',
        error: 'bi-exclamation-triangle-fill',
        warning: 'bi-exclamation-circle-fill',
        info: 'bi-info-circle-fill'
    };

    const bgClasses = {
        success: 'bg-success text-white',
        error: 'bg-danger text-white',
        warning: 'bg-warning text-dark',
        info: 'bg-info text-dark'
    };

    const toast = document.createElement('div');
    toast.className = `toast align-items-center ${bgClasses[type] || bgClasses.info} border-0`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');

    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                <i class="bi ${icons[type] || icons.info} me-2"></i>${escapeHtml(message)}
            </div>
            <button type="button" class="btn-close ${type === 'warning' || type === 'info' ? '' : 'btn-close-white'} me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;

    toastContainer.appendChild(toast);

    // Use Bootstrap's Toast API
    const bsToast = new bootstrap.Toast(toast, { delay: duration, autohide: true });
    bsToast.show();

    // Remove from DOM after hidden
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
}

/**
 * Show an error toast (longer duration).
 * @param {string} message - Error message
 */
export function showError(message) {
    showToast(message, 'error', 8000);
}

/**
 * Show a success toast.
 * @param {string} message - Success message
 */
export function showSuccess(message) {
    showToast(message, 'success', 4000);
}

/**
 * Show a warning toast.
 * @param {string} message - Warning message
 */
export function showWarning(message) {
    showToast(message, 'warning', 6000);
}

/**
 * Show an info toast.
 * @param {string} message - Info message
 */
export function showInfo(message) {
    showToast(message, 'info', 5000);
}

/**
 * Escape HTML to prevent XSS.
 * @param {string} text - Text to escape
 * @returns {string} - Escaped text
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize on module load
if (typeof document !== 'undefined') {
    // Wait for DOM to be ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initNotifications);
    } else {
        initNotifications();
    }
}
