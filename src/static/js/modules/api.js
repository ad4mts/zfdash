/**
 * api.js - API Communication Layer
 * 
 * Handles all API calls to the backend server.
 * Includes error handling, authentication redirects, and action execution.
 */

import { updateStatus, showErrorAlert } from './ui.js';

/**
 * Make an API call to the backend
 * @param {string} endpoint - API endpoint path
 * @param {string} method - HTTP method (GET, POST, etc.)
 * @param {object|null} body - Request body for POST requests
 * @returns {Promise<object>} - Response data
 */
export async function apiCall(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: {
            'Accept': 'application/json',
        }
    };
    if (body) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
    }

    let response;
    try {
        response = await fetch(endpoint, options);

        if (!response.ok) {
            const statusCode = response.status;
            const contentType = response.headers.get('content-type');
            let error;
            let errorData = {
                status: 'error',
                error: `HTTP error! Status: ${statusCode}`,
                details: 'No further details provided.'
            };

            // Authentication Redirect Logic
            if ([401, 403].includes(statusCode) && !['/login', '/api/auth/status'].includes(endpoint)) {
                console.warn(`API call to ${endpoint} resulted in ${statusCode}. Redirecting to login.`);
                window.location.href = '/login';
                error = new Error("UnauthorizedRedirect");
                error.statusCode = statusCode;
                throw error;
            }

            // Attempt to parse error details if content type is JSON
            if (contentType && contentType.includes('application/json')) {
                try {
                    const jsonErrorData = await response.json();
                    errorData.error = jsonErrorData.error || errorData.error;
                    errorData.details = jsonErrorData.details || errorData.details;
                    errorData.status = jsonErrorData.status || 'error'; 
                } catch (parseError) {
                    console.error(`API call to ${endpoint} failed with status ${statusCode}, but couldn't parse JSON error response:`, parseError);
                    errorData.details = "Failed to parse error response from server.";
                }
            } else {
                try {
                    const textError = await response.text();
                    console.warn(`API call to ${endpoint} failed with status ${statusCode} and non-JSON response:`, textError.substring(0, 500)); 
                    errorData.details = `Server returned a non-JSON error page (status: ${statusCode}). Check console for details.`;
                } catch (textErrorErr) {
                    errorData.details = `Server returned a non-JSON error (status: ${statusCode}), and failed to read response body.`;
                }
            }
            
            error = new Error(errorData.error); 
            error.details = errorData.details;
            error.statusCode = statusCode;
            error.data = errorData;
            throw error;
        }

        // Handle successful response (assuming JSON)
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            const data = await response.json();
            return data;
        } else {
            console.error(`API call to ${endpoint} succeeded (status ${response.status}) but returned non-JSON content-type: ${contentType}`);
            const textResponse = await response.text();
            console.warn("Response Text:", textResponse.substring(0, 500));
            throw new Error("Received unexpected non-JSON response from server.");
        }

    } catch (error) {
        if (error.message !== "UnauthorizedRedirect") {
            console.error(`API call to ${endpoint} failed:`, error);
            if (error.data) {
                showErrorAlert(`API Error: ${endpoint}`, `${error.message}\n\nDetails: ${error.details || 'None'}`);
            }
        }
        throw error;
    }
}

/**
 * Execute a ZFS action via the API
 * @param {string} actionName - Name of the action to execute
 * @param {Array} args - Positional arguments for the action
 * @param {object} kwargs - Keyword arguments for the action
 * @param {string|null} successMessage - Message to show on success
 * @param {boolean} requireConfirm - Whether to require user confirmation
 * @param {string|null} confirmMessage - Custom confirmation message
 * @param {Function|null} onSuccess - Callback to execute on success (e.g., fetchAndRenderData)
 * @returns {Promise<void>}
 */
export async function executeAction(actionName, args = [], kwargs = {}, successMessage = null, requireConfirm = false, confirmMessage = null, onSuccess = null) {
    if (requireConfirm) {
        const defaultConfirm = `Are you sure you want to perform action '${actionName}'?`;
        if (!confirm(confirmMessage || defaultConfirm)) {
            updateStatus('Action cancelled.', 'info');
            return;
        }
    }

    updateStatus(`Executing: ${actionName}...`, 'busy');
    try {
        const payload = { args, kwargs };
        const result = await apiCall(`/api/action/${actionName}`, 'POST', payload);
        updateStatus(successMessage || result.data || `${actionName} successful.`, 'success');
        
        // Trigger refresh callback if provided
        if (onSuccess && typeof onSuccess === 'function') {
            onSuccess();
        }
    } catch (error) {
        console.error(`Action ${actionName} failed:`, error);
        let errorMsg = error.message;
        if (error.details) {
            errorMsg += `\n\nDetails:\n${error.details}`;
        }
        showErrorAlert(`Action Failed: ${actionName}`, errorMsg);
        updateStatus(`Failed: ${actionName}`, 'error');
    }
}

// Store reference to fetchAndRenderData for use in executeAction
let _fetchAndRenderDataRef = null;

/**
 * Set the fetchAndRenderData reference for use in executeAction
 * @param {Function} fn - The fetchAndRenderData function
 */
export function setFetchAndRenderDataRef(fn) {
    _fetchAndRenderDataRef = fn;
}

/**
 * Execute action with automatic data refresh on success
 * @param {string} actionName - Name of the action
 * @param {Array} args - Arguments
 * @param {object} kwargs - Keyword arguments  
 * @param {string|null} successMessage - Success message
 * @param {boolean} requireConfirm - Require confirmation
 * @param {string|null} confirmMessage - Confirmation message
 */
export async function executeActionWithRefresh(actionName, args = [], kwargs = {}, successMessage = null, requireConfirm = false, confirmMessage = null) {
    await executeAction(actionName, args, kwargs, successMessage, requireConfirm, confirmMessage, _fetchAndRenderDataRef);
}
