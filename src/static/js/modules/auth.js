/**
 * auth.js - Authentication Module
 * 
 * Handles user authentication, login, logout, and password management.
 * 
 * CALLBACK PATTERN EXPLANATION
 * ============================
 * This module needs to call fetchAndRenderData() after successful authentication,
 * but that function is defined in app.js. Due to ES6 module circular dependency
 * limitations, we can't directly import it here.
 * 
 * Solution: app.js calls setAuthCallbacks() during initialization to provide
 * references to the functions this module needs. This is a form of dependency
 * injection that allows late binding after all modules are loaded.
 */

import { apiCall } from './api.js';
import { updateStatus, showErrorAlert } from './ui.js';
import * as state from './state.js';
import dom from './dom-elements.js';

// Store reference to data fetcher for auth success
// These are set by app.js via setAuthCallbacks() during initialization
let _fetchAndRenderDataRef = null;
let _clearSelectionRef = null;

/**
 * Set references to functions needed after auth
 * MUST be called by app.js before checkAuthStatus() is invoked
 * @param {Function} fetchFn - fetchAndRenderData function from app.js
 * @param {Function} clearFn - clearSelection function from tree.js
 */
export function setAuthCallbacks(fetchFn, clearFn) {
    _fetchAndRenderDataRef = fetchFn;
    _clearSelectionRef = clearFn;
}

/**
 * Update UI based on authentication state
 * @param {boolean} authenticated - Whether user is authenticated
 * @param {string|null} username - Username if authenticated
 */
export function updateAuthStateUI(authenticated, username = null) {
    state.setIsAuthenticated(authenticated);
    state.setCurrentUsername(username);

    if (authenticated) {
        dom.bodyElement.classList.remove('logged-out');
        dom.bodyElement.classList.add('logged-in');
        if (dom.navbarContentLoggedIn) dom.navbarContentLoggedIn.style.display = 'flex';
        if (dom.userMenu) dom.userMenu.style.display = 'block';
        if (dom.usernameDisplay && username) dom.usernameDisplay.textContent = username;
        
        // Clear any previous login errors
        if (dom.loginError) {
            dom.loginError.style.display = 'none';
            dom.loginError.textContent = '';
        }
    } else {
        dom.bodyElement.classList.remove('logged-in');
        dom.bodyElement.classList.add('logged-out');
        if (dom.navbarContentLoggedIn) dom.navbarContentLoggedIn.style.display = 'none';
        if (dom.usernameDisplay) dom.usernameDisplay.textContent = 'User';
        
        // Clear main app data/UI when logging out
        if (_clearSelectionRef) _clearSelectionRef();
        state.setZfsDataCache(null);
        if (dom.zfsTree) dom.zfsTree.innerHTML = '';
    }
}

/**
 * Check authentication status with server
 */
export async function checkAuthStatus() {
    try {
        const response = await fetch('/api/auth/status');
        const data = await response.json();

        if (response.ok && data.status === 'success' && data.authenticated) {
            console.log("User is authenticated:", data.username);
            updateAuthStateUI(true, data.username);
            if (_fetchAndRenderDataRef) _fetchAndRenderDataRef();
        } else {
            console.log("User is not authenticated.");
            updateAuthStateUI(false);
        }
    } catch (error) {
        console.error("Error checking auth status:", error);
        updateAuthStateUI(false);
        showErrorAlert("Authentication Check Failed", `Could not verify login status. Please try logging in.\n\nError: ${error.message}`);
    }
}

/**
 * Handle login form submission
 * @param {Event} event - Form submit event
 */
export async function handleLogin(event) {
    event.preventDefault();
    if (!dom.loginForm) return;

    const username = dom.loginForm.username.value;
    const password = dom.loginForm.password.value;

    if (!username || !password) {
        if (dom.loginError) {
            dom.loginError.textContent = "Username and password are required.";
            dom.loginError.style.display = 'block';
        }
        return;
    }

    updateStatus('Logging in...', 'busy');
    if (dom.loginError) dom.loginError.style.display = 'none';

    try {
        const result = await apiCall('/login', 'POST', { username, password });
        if (result.status === 'success') {
            updateStatus('Login successful.', 'success');
            await checkAuthStatus();
        } else {
            throw new Error(result.error || "Login failed with unknown error.");
        }
    } catch (error) {
        console.error("Login failed:", error);
        updateStatus('Login failed.', 'error');
        if (dom.loginError) {
            dom.loginError.textContent = error.message || "Invalid username or password.";
            dom.loginError.style.display = 'block';
        }
        updateAuthStateUI(false);
    }
}

/**
 * Handle logout
 */
export async function handleLogout() {
    updateStatus('Logging out...', 'busy');
    
    const logoutForm = document.getElementById('logout-form');
    if (logoutForm) {
        logoutForm.submit();
    } else {
        console.error('Logout form not found!');
        showErrorAlert("Logout Failed", "Could not find logout mechanism.");
        updateStatus('Logout failed.', 'error');
    }
}

/**
 * Handle password change
 */
export async function handleChangePassword() {
    if (!dom.changePasswordForm) return;

    const currentPassword = dom.changePasswordForm.current_password.value;
    const newPassword = dom.changePasswordForm.new_password.value;
    const confirmPassword = dom.changePasswordForm.confirm_password.value;

    // Client-side validation
    if (!currentPassword || !newPassword || !confirmPassword) {
        dom.changePasswordError.textContent = "All fields are required.";
        dom.changePasswordError.style.display = 'block';
        dom.changePasswordSuccess.style.display = 'none';
        return;
    }
    if (newPassword !== confirmPassword) {
        dom.changePasswordError.textContent = "New passwords do not match.";
        dom.changePasswordError.style.display = 'block';
        dom.changePasswordSuccess.style.display = 'none';
        return;
    }
    if (newPassword.length < 8) {
        dom.changePasswordError.textContent = "New password must be at least 8 characters long.";
        dom.changePasswordError.style.display = 'block';
        dom.changePasswordSuccess.style.display = 'none';
        return;
    }

    dom.changePasswordError.style.display = 'none';
    dom.changePasswordSuccess.style.display = 'none';
    updateStatus('Changing password...', 'busy');

    try {
        const result = await apiCall('/api/change-password', 'POST', {
            current_password: currentPassword,
            new_password: newPassword,
            confirm_password: confirmPassword
        });

        if (result.status === 'success') {
            updateStatus('Password changed successfully.', 'success');
            dom.changePasswordSuccess.textContent = result.message || "Password changed successfully.";
            dom.changePasswordSuccess.style.display = 'block';
            dom.changePasswordForm.reset();
            
            // Close modal after a delay
            setTimeout(() => {
                if (dom.changePasswordModal) dom.changePasswordModal.hide();
                dom.changePasswordSuccess.style.display = 'none';
            }, 2000);
        } else {
            throw new Error(result.error || "Failed to change password.");
        }
    } catch (error) {
        console.error("Change password failed:", error);
        updateStatus('Password change failed.', 'error');
        dom.changePasswordError.textContent = error.message || "An error occurred.";
        dom.changePasswordError.style.display = 'block';
    }
}

/**
 * Initialize change password modal event handlers
 */
export function initializeChangePasswordModal() {
    if (dom.changePasswordModalElement) {
        dom.changePasswordModalElement.addEventListener('show.bs.modal', () => {
            if (dom.changePasswordError) dom.changePasswordError.style.display = 'none';
            if (dom.changePasswordSuccess) dom.changePasswordSuccess.style.display = 'none';
            if (dom.changePasswordForm) dom.changePasswordForm.reset();
        });
    }
}
