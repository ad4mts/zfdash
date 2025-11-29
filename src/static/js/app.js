// DEPRECATED: use refractored modules> src/static/js/modules/app.js instead.
// Keep for reference.
// --- START OF FILE src/static/js/app.js ---
// --- SECTION 1: Globals and Helpers ---

// --- Globals ---
let zfsDataCache = null; // Cache the fetched data
let currentSelection = null; // Keep track of the selected ZfsObject path/data
let currentProperties = null; // Cache properties for the selected object
let currentPoolStatusText = null; // Cache pool status text
let currentPoolLayout = null; // Cache parsed pool layout
let isAuthenticated = false; // Track authentication state
let currentUsername = null; // Store username

// DOM Elements (cache frequently used ones)
const bodyElement = document.body;
const loginSection = document.getElementById('login-section');
const appSection = document.getElementById('app-section');
const loginForm = document.getElementById('login-form');
const loginError = document.getElementById('login-error');
const userMenu = document.getElementById('user-menu');
const usernameDisplay = document.getElementById('username-display');
const logoutButton = document.getElementById('logout-button');
const shutdownButtonItem = document.getElementById('shutdown-button-item');
const navbarContentLoggedIn = document.getElementById('navbar-content-loggedin'); // Added
const changePasswordModalElement = document.getElementById('changePasswordModal');
const changePasswordModal = changePasswordModalElement ? new bootstrap.Modal(changePasswordModalElement) : null;
const changePasswordForm = document.getElementById('change-password-form');
const changePasswordError = document.getElementById('change-password-error');
const changePasswordSuccess = document.getElementById('change-password-success');
const changePasswordConfirmButton = document.getElementById('changePasswordConfirmButton');

const zfsTree = document.getElementById('zfs-tree');
const statusIndicator = document.getElementById('status-indicator');
const detailsPlaceholder = document.getElementById('details-placeholder');
const detailsContent = document.getElementById('details-content');
const detailsTitle = document.getElementById('details-title');
const propertiesTableBody = document.getElementById('properties-table').querySelector('tbody');
const snapshotsTableBody = document.getElementById('snapshots-table').querySelector('tbody');
const poolStatusContent = document.getElementById('pool-status-content');
const poolEditTreeContainer = document.getElementById('pool-edit-tree-container');
const refreshButton = document.getElementById('refresh-button');
const modalElement = document.getElementById('actionModal');
const actionModal = modalElement ? new bootstrap.Modal(modalElement) : null;
const actionModalBody = document.getElementById('actionModalBody');
const actionModalLabel = document.getElementById('actionModalLabel');
const actionModalFooter = document.getElementById('actionModalFooter');
const detailsTabContent = document.getElementById('details-tab-content'); // Added
    
    // Persist selection across refreshes
    const SELECTED_SELECTION_KEY = 'zfdash_selected_item_v1';
    try {
        const storedSel = JSON.parse(localStorage.getItem(SELECTED_SELECTION_KEY) || 'null');
        if (storedSel && storedSel.name && storedSel.obj_type) {
            currentSelection = storedSel; // Will be used by renderTree to restore selection
        }
    } catch (e) {
        console.warn('Failed to load selected item from localStorage:', e);
    }
    
    function saveSelectionToStorage() {
        try {
            if (currentSelection) {
                localStorage.setItem(SELECTED_SELECTION_KEY, JSON.stringify({ name: currentSelection.name, obj_type: currentSelection.obj_type }));
            } else {
                localStorage.removeItem(SELECTED_SELECTION_KEY);
            }
        } catch (e) {
            console.warn('Failed to save selected item to localStorage:', e);
        }
    }


// --- API Helper ---
async function apiCall(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: {
            // Indicate that we prefer JSON responses
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

        // --- Check response status EARLY --- 
        if (!response.ok) {
            const statusCode = response.status;
            const contentType = response.headers.get('content-type');
            let error;
            let errorData = { // Default error structure
                status: 'error',
                error: `HTTP error! Status: ${statusCode}`,
                details: 'No further details provided.'
            };

            // --- *** Authentication Redirect Logic (Improved) *** ---
            // If we get a 401 Unauthorized or 403 Forbidden, redirect to login
            // regardless of content type, unless it's an auth endpoint itself.
            if ([401, 403].includes(statusCode) && !['/login', '/api/auth/status'].includes(endpoint)) {
                console.warn(`API call to ${endpoint} resulted in ${statusCode}. Redirecting to login.`);
                // Clear auth state and redirect
                // updateAuthStateUI(false); // Avoid potential UI flashes, let login page handle state
                window.location.href = '/login'; // Force reload to login page
                // Throw a specific error to stop further processing
                error = new Error("UnauthorizedRedirect");
                error.statusCode = statusCode;
                throw error;
            }
            // --- End Auth Redirect ---

            // Attempt to parse error details *if* content type is JSON
            if (contentType && contentType.includes('application/json')) {
                try {
                    const jsonErrorData = await response.json();
                    // Merge JSON error data into our default structure
                    errorData.error = jsonErrorData.error || errorData.error;
                    errorData.details = jsonErrorData.details || errorData.details;
                    // Use the status from JSON if available
                    errorData.status = jsonErrorData.status || 'error'; 
                } catch (parseError) {
                    console.error(`API call to ${endpoint} failed with status ${statusCode}, but couldn't parse JSON error response:`, parseError);
                    errorData.details = "Failed to parse error response from server.";
                }
            } else {
                 // If not JSON, try to get text, maybe it's a plain error message or HTML page
                 try {
                     const textError = await response.text();
                     // Log the HTML/Text for debugging but provide a generic message to user
                     console.warn(`API call to ${endpoint} failed with status ${statusCode} and non-JSON response:`, textError.substring(0, 500)); 
                     errorData.details = `Server returned a non-JSON error page (status: ${statusCode}). Check console for details.`;
                 } catch (textErrorErr) {
                      errorData.details = `Server returned a non-JSON error (status: ${statusCode}), and failed to read response body.`;
                 }
            }
            
            // Throw an error object based on the gathered info
            error = new Error(errorData.error); 
            error.details = errorData.details;
            error.statusCode = statusCode;
            error.data = errorData; // Include the full structured error data
            throw error;
        }

        // --- Handle successful response (assuming JSON) ---
        // We expect JSON for successful API calls
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
             const data = await response.json();
             return data; // Expected format: { status: "success", data: ... } or potentially { status: "error", ... } from ZFS calls
        } else {
             // Should not happen for successful calls to our API endpoints
             console.error(`API call to ${endpoint} succeeded (status ${response.status}) but returned non-JSON content-type: ${contentType}`);
             const textResponse = await response.text();
             console.warn("Response Text:", textResponse.substring(0, 500));
             throw new Error("Received unexpected non-JSON response from server.");
        }

    } catch (error) {
        // Avoid logging the specific "UnauthorizedRedirect" error as a failure in console
        if (error.message !== "UnauthorizedRedirect") {
            console.error(`API call to ${endpoint} failed:`, error);
             // If the error object has structured data, use it for alerts
            if (error.data) {
                 showErrorAlert(`API Error: ${endpoint}`, `${error.message}\n\nDetails: ${error.details || 'None'}`);
            }
        }
        // Re-throw the enriched error object (or the redirect error)
        throw error;
    }
}

// --- Persisted UI State ---
// Maintain a set of expanded node paths (persist across refreshes using localStorage)
const EXPANDED_NODES_KEY = 'zfdash_expanded_nodes_v1';
let expandedNodePaths = new Set();
try {
    const stored = JSON.parse(localStorage.getItem(EXPANDED_NODES_KEY) || '[]');
    if (Array.isArray(stored)) {
        // Normalize stored entries to the new key format 'name::type' for backward compatibility
        const normalized = stored.map(entry => {
            entry = String(entry);
            if (entry.includes('::')) return entry; // already in new format
            // old store might just have 'name' only; convert to 'name::' (empty type)
            return nodeStorageKey(entry, '');
        });
        expandedNodePaths = new Set(normalized);
    }
} catch (e) {
    console.warn('Failed to load expanded nodes from localStorage:', e);
    expandedNodePaths = new Set();
}

function saveExpandedNodes() {
    try {
        localStorage.setItem(EXPANDED_NODES_KEY, JSON.stringify(Array.from(expandedNodePaths)));
    } catch (e) {
        console.warn('Failed to save expanded nodes to localStorage', e);
    }
}

function nodeStorageKey(name, objType) {
    return `${name}::${objType || ''}`; // include obj_type for uniqueness between pool and dataset
}

// --- Action Helper ---
async function executeAction(actionName, args = [], kwargs = {}, successMessage = null, requireConfirm = false, confirmMessage = null) {
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
        // Trigger refresh after successful action
        fetchAndRenderData();
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

// --- END OF SECTION 1 ---

// --- START OF SECTION 1.5: Authentication UI & Logic ---

function updateAuthStateUI(authenticated, username = null) {
    isAuthenticated = authenticated;
    currentUsername = username;

    if (authenticated) {
        bodyElement.classList.remove('logged-out');
        bodyElement.classList.add('logged-in');
        if (navbarContentLoggedIn) navbarContentLoggedIn.style.display = 'flex'; // Show navbar content
        if (userMenu) userMenu.style.display = 'block'; // This is inside navbarContentLoggedIn now
        // if (shutdownButtonItem) shutdownButtonItem.style.display = 'block'; // This is inside navbarContentLoggedIn now
        if (usernameDisplay && username) usernameDisplay.textContent = username;
        // Clear any previous login errors
        if (loginError) {
            loginError.style.display = 'none';
            loginError.textContent = '';
        }
    } else {
        bodyElement.classList.remove('logged-in');
        bodyElement.classList.add('logged-out');
        if (navbarContentLoggedIn) navbarContentLoggedIn.style.display = 'none'; // Hide navbar content
        // if (userMenu) userMenu.style.display = 'none'; // No need, parent is hidden
        // if (shutdownButtonItem) shutdownButtonItem.style.display = 'none'; // No need, parent is hidden
        if (usernameDisplay) usernameDisplay.textContent = 'User';
        // Clear main app data/UI when logging out
        clearSelection();
        zfsDataCache = null;
        if (zfsTree) zfsTree.innerHTML = ''; // Clear tree
    }
}

async function checkAuthStatus() {
    //console.log("Checking authentication status...");
    try {
        // Use a slightly modified apiCall that doesn't redirect on 401 for this specific check
        const response = await fetch('/api/auth/status');
        const data = await response.json(); // Assume it returns JSON even for 401 handled by Flask

        if (response.ok && data.status === 'success' && data.authenticated) {
            console.log("User is authenticated:", data.username);
            updateAuthStateUI(true, data.username);
            fetchAndRenderData(); // Load data now that we know user is logged in
        } else {
            console.log("User is not authenticated.");
            updateAuthStateUI(false);
            // No need to redirect here, the UI update handles showing the login form
        }
    } catch (error) {
        console.error("Error checking auth status:", error);
        updateAuthStateUI(false); // Assume not authenticated on error
        showErrorAlert("Authentication Check Failed", `Could not verify login status. Please try logging in.\n\nError: ${error.message}`);
    }
}

async function handleLogin(event) {
    event.preventDefault(); // Prevent default form submission
    if (!loginForm) return;

    const username = loginForm.username.value;
    const password = loginForm.password.value;

    if (!username || !password) {
        if (loginError) {
            loginError.textContent = "Username and password are required.";
            loginError.style.display = 'block';
        }
        return;
    }

    updateStatus('Logging in...', 'busy');
    if (loginError) loginError.style.display = 'none'; // Hide previous errors

    try {
        const result = await apiCall('/login', 'POST', { username, password });
        if (result.status === 'success') {
            updateStatus('Login successful.', 'success');
            // Fetch auth status again to get username and update UI properly
            await checkAuthStatus();
            // checkAuthStatus will call fetchAndRenderData if successful
        } else {
            // This path might not be reached if apiCall throws on non-OK status
            throw new Error(result.error || "Login failed with unknown error.");
        }
    } catch (error) {
        console.error("Login failed:", error);
        updateStatus('Login failed.', 'error');
        if (loginError) {
            loginError.textContent = error.message || "Invalid username or password.";
            loginError.style.display = 'block';
        }
        updateAuthStateUI(false); // Ensure UI is in logged-out state
    }
}

async function handleLogout() {
    updateStatus('Logging out...', 'busy');
    // Instead of apiCall, submit the hidden form which triggers the redirect
    const logoutForm = document.getElementById('logout-form');
    if (logoutForm) {
        logoutForm.submit();
        // No need to update UI here, the browser will navigate to the login page
    } else {
        // Fallback or error if form isn't found
        console.error('Logout form not found!');
        showErrorAlert("Logout Failed", "Could not find logout mechanism.");
        updateStatus('Logout failed.', 'error');
    }

}

async function handleChangePassword() {
    if (!changePasswordForm) return;

    const currentPassword = changePasswordForm.current_password.value;
    const newPassword = changePasswordForm.new_password.value;
    const confirmPassword = changePasswordForm.confirm_password.value;

    // Basic client-side validation
    if (!currentPassword || !newPassword || !confirmPassword) {
        changePasswordError.textContent = "All fields are required.";
        changePasswordError.style.display = 'block';
        changePasswordSuccess.style.display = 'none';
        return;
    }
    if (newPassword !== confirmPassword) {
        changePasswordError.textContent = "New passwords do not match.";
        changePasswordError.style.display = 'block';
        changePasswordSuccess.style.display = 'none';
        return;
    }
     if (newPassword.length < 8) {
        changePasswordError.textContent = "New password must be at least 8 characters long.";
        changePasswordError.style.display = 'block';
        changePasswordSuccess.style.display = 'none';
        return;
    }


    changePasswordError.style.display = 'none';
    changePasswordSuccess.style.display = 'none';
    updateStatus('Changing password...', 'busy');

    try {
        const result = await apiCall('/api/change-password', 'POST', {
            current_password: currentPassword,
            new_password: newPassword,
            confirm_password: confirmPassword
        });

        if (result.status === 'success') {
            updateStatus('Password changed successfully.', 'success');
            changePasswordSuccess.textContent = result.message || "Password changed successfully.";
            changePasswordSuccess.style.display = 'block';
            changePasswordForm.reset(); // Clear form
            // Optionally close modal after a delay
            setTimeout(() => {
                if (changePasswordModal) changePasswordModal.hide();
                changePasswordSuccess.style.display = 'none'; // Hide success message on close
            }, 2000);
        } else {
            // Should be caught by apiCall's error handling, but handle just in case
            throw new Error(result.error || "Failed to change password.");
        }
    } catch (error) {
        console.error("Change password failed:", error);
        updateStatus('Password change failed.', 'error');
        changePasswordError.textContent = error.message || "An error occurred.";
        changePasswordError.style.display = 'block';
    }
}

// --- END OF SECTION 1.5 ---

// --- START OF SECTION 2 ---

// --- Data Fetching and Rendering ---

function setLoadingState(isLoading) {
    refreshButton.disabled = isLoading;
    if (isLoading) {
        statusIndicator.innerHTML = `<span class="spinner-border spinner-border-sm text-light" role="status" aria-hidden="true"></span> Loading...`;
        zfsTree.innerHTML = `<div class="text-center p-3"><span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading...</div>`;
        // Disable action buttons *specifically* in Pool and Dataset menus while loading
        document.querySelectorAll('#poolDropdown + .dropdown-menu .dropdown-item, #datasetDropdown + .dropdown-menu .dropdown-item').forEach(btn => btn.classList.add('disabled'));
    } else {
        statusIndicator.textContent = 'Idle';
        // Pool/Dataset action buttons will be re-enabled by updateActionStates after data loads.
        // User menu buttons are no longer disabled by this function.
    }
}

function updateStatus(message, type = 'info') { // types: info, busy, success, error
    //console.log(`Status (${type}):`, message);
    let indicatorClass = 'text-light'; // Default/info
    let indicatorIcon = '';

    if (type === 'busy') {
        indicatorClass = 'text-warning';
        indicatorIcon = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> `;
    } else if (type === 'success') {
        indicatorClass = 'text-success';
    } else if (type === 'error') {
        indicatorClass = 'text-danger';
    }

    statusIndicator.className = `navbar-text me-2 ${indicatorClass}`;
    statusIndicator.innerHTML = `${indicatorIcon}${message}`;

    // Optional: Clear status after a delay for success/error messages
    if (type === 'success' || type === 'error' || type === 'info') {
        setTimeout(() => {
            // Only clear if the current message is the one we set
            if (statusIndicator.innerHTML.includes(message)) {
                statusIndicator.textContent = 'Idle';
                statusIndicator.className = 'navbar-text me-2 text-light';
            }
        }, 5000); // Clear after 5 seconds
    }
}

function buildTreeHtml(items, level = 0) {
    if (!items || items.length === 0) {
        return '<div class="text-muted ps-3">No pools found.</div>';
    }
    let html = '<ul class="list-unstyled mb-0">';
    items.forEach(item => {
        const indent = level * 20; // Indentation in pixels
        const isPool = item.obj_type === 'pool';
        const isDataset = item.obj_type === 'dataset';
        const isVolume = item.obj_type === 'volume';
        const hasChildren = item.children && item.children.length > 0;
        const hasSnapshots = item.snapshots && item.snapshots.length > 0;

        let iconClass = 'bi-hdd'; // Default Pool
        if (isDataset) iconClass = 'bi-folder';
        if (isVolume) iconClass = 'bi-hdd-stack'; // Or maybe 'bi-database'

        let healthClass = '';
        let healthIndicator = '';
        if (isPool) {
            const health = item.health?.toUpperCase();
            if (health === 'ONLINE') healthClass = 'text-success';
            else if (health === 'DEGRADED') healthClass = 'text-warning';
            else if (health === 'FAULTED' || health === 'UNAVAIL' || health === 'REMOVED') healthClass = 'text-danger';
            else if (health === 'OFFLINE') healthClass = 'text-muted';
            if (health && health !== 'ONLINE') {
                healthIndicator = `<span class="badge bg-${healthClass.replace('text-','')} ms-1">${health}</span>`;
            }
        }

        // Determine if this node should be expanded according to user state
    const nodeKey = nodeStorageKey(item.name, item.obj_type);
    const isExpanded = expandedNodePaths.has(nodeKey);
        let toggleHtml = '';
        if (hasChildren) {
            toggleHtml = `<i class="bi ${isExpanded ? 'bi-caret-down-fill' : 'bi-caret-right-fill'} me-1 tree-toggle"></i>`;
        } else {
            toggleHtml = `<i class="bi bi-dot me-1 text-muted"></i>`; // Placeholder for alignment
        }

        // Display only the last part of the name for non-pools
        const displayName = isPool ? item.name : item.name.split('/').pop();

        // Add data attributes for easy selection and identification
    html += `
        <li style="padding-left: ${indent}px;">
    <div class="tree-item ${(currentSelection?.name === item.name && currentSelection?.obj_type === item.obj_type) ? 'selected' : ''}"
        data-path="${item.name}"
        data-type="${item.obj_type}"
        title="${item.name} (${item.obj_type})">
        ${toggleHtml}<i class="bi ${iconClass} me-1 ${healthClass}"></i>
        <span class="tree-item-name">${displayName}</span>
        ${healthIndicator}
        ${item.is_encrypted ? '<i class="bi bi-lock-fill text-warning ms-1" title="Encrypted"></i>' : ''}
        ${item.is_mounted ? '<i class="bi bi-cloud-arrow-up-fill text-info ms-1" title="Mounted"></i>' : ''}
        </div>
    ${hasChildren ? `<div class="tree-children" style="display: ${isExpanded ? 'block' : 'none'};">${buildTreeHtml(item.children, level + 1)}</div>` : ''}
        </li>
        `;
    });
    html += '</ul>';
    return html;
}

// --- END OF SECTION 2 ---
// --- Start OF SECTION 3 ---

function renderTree(data) {
    // --- START REVISED renderTree ---
    zfsDataCache = data; // Store data
    const treeHtml = buildTreeHtml(data);
    zfsTree.innerHTML = treeHtml; // Set the HTML content
    // Ensure no stray selected classes remain before restoration
    zfsTree.querySelectorAll('.tree-item.selected').forEach(el => el.classList.remove('selected'));

    // Check if treeHtml is empty or indicates no pools
    if (!treeHtml || treeHtml.includes("No pools found")) {
        console.log("renderTree: No pools found or empty data.");
        clearSelection(); // Ensure details are cleared
        updateActionStates(); // Update buttons for the "no pools" state
        return; // Stop further processing for this function
    }

    // Add event listeners ONLY if the tree has content
    try {
        zfsTree.querySelectorAll('.tree-item').forEach(item => {
            item.addEventListener('click', handleTreeItemClick);
        });
        zfsTree.querySelectorAll('.tree-toggle').forEach(toggle => {
            toggle.addEventListener('click', handleTreeToggle);
        });
    } catch (e) {
        console.error("Error adding event listeners to tree:", e);
        // Optionally display an error message in the tree container
        zfsTree.innerHTML = '<div class="alert alert-warning">Error initializing tree view.</div>';
        clearSelection();
        updateActionStates();
        return;
    }


    // Restore selection if possible
    let selectionRestored = false;
    if (currentSelection) {
        // --- FIX: Use CSS.escape for potentially problematic characters in paths ---
        // --- FIX: Also use data-type for more specific selection restoration ---
        const escapedPath = CSS.escape(currentSelection.name);
        const selector = `.tree-item[data-path="${escapedPath}"][data-type="${currentSelection.obj_type}"]`;
        const selectedElement = zfsTree.querySelector(selector);

        if (selectedElement) {
            try {
                selectedElement.classList.add('selected');
                // Ensure parents are expanded
                let parentLi = selectedElement.closest('li');
                while (parentLi) {
                    const childrenDiv = parentLi.querySelector(':scope > .tree-children'); // Use :scope for direct children
                    const toggleIcon = parentLi.querySelector(':scope > .tree-item > .tree-toggle');
                    if (childrenDiv && toggleIcon && childrenDiv.style.display !== 'block') { // Expand only if not already expanded
                        childrenDiv.style.display = 'block';
                        toggleIcon.classList.replace('bi-caret-right-fill', 'bi-caret-down-fill');
                        // Persist expanded state for parent
                        try {
                            const parentItemDiv = parentLi.querySelector(':scope > .tree-item');
                            const parentPath = parentItemDiv?.dataset?.path;
                            const parentType = parentItemDiv?.dataset?.type;
                            if (parentPath) {
                                const parentKey = nodeStorageKey(parentPath, parentType);
                                expandedNodePaths.add(parentKey);
                                saveExpandedNodes();
                            }
                        } catch (e) {
                            console.warn('Failed to persist expanded parent:', e);
                        }
                    }
                    // Find the next parent `li` correctly
                    const parentUl = parentLi.parentElement; // This is the `ul.tree-children` or the root `ul`
                    parentLi = parentUl ? parentUl.closest('li') : null; // Find the `li` containing that `ul`
                }
                selectionRestored = true;
            } catch (e) {
                console.error("Error expanding parents for selected item:", e);
                // Continue without restoration if expansion fails
                selectionRestored = false; // Mark as not restored
            }
        } else {
            console.log(`renderTree: Could not find element for previous selection '${currentSelection.name}' with type '${currentSelection.obj_type}'`);
        }
    }

    // If selection wasn't restored (either wasn't set, or element not found/error), clear details
    if (!selectionRestored) {
        clearSelection();
    }
    // Update global action buttons regardless of selection restoration
    updateActionStates();
    // --- END REVISED renderTree ---
}

async function fetchAndRenderData() {
    // --- START REVISED fetchAndRenderData ---
    if (!isAuthenticated) {
        //console.log("fetchAndRenderData skipped: User not authenticated.");
        // Ensure loading state is off if called erroneously
        setLoadingState(false);
        return;
    }
    setLoadingState(true);
    const activeTabEl = document.querySelector('#details-tab .nav-link.active');
    const activeTabId = activeTabEl ? activeTabEl.id : 'properties-tab-button';
    let success = false; // Track overall success

    try {
        const result = await apiCall('/api/data');
        //console.log("Fetched data:", result.data); // Log fetched data
        // Ensure renderTree runs even if there's no data, it handles the empty case
        renderTree(result.data); // This updates zfsDataCache, tree view, and calls updateActionStates

        // Now, try to restore selection and details, but wrap in try/catch
        let objectStillExists = false;
        let selectedPath = null;
        let selectedType = null; // Store type as well
        if (currentSelection) {
            selectedPath = currentSelection.name; // Store path before potential clear
            selectedType = currentSelection.obj_type; // Store type before potential clear
            // Use type hint when finding the object again
            const newSelection = findObjectByPath(selectedPath, selectedType, zfsDataCache);
            if (newSelection) {
                //console.log(`Restoring selection: ${selectedPath} (Type: ${selectedType})`);
                currentSelection = newSelection; // Update ref to new object
                objectStillExists = true;
                // Persist the restored selection
                saveSelectionToStorage();
            } else {
                //console.log(`Selection ${selectedPath} (Type: ${selectedType}) not found in new data cache.`);
            }
        }

        if (objectStillExists) {
            try {
                // This is the part most likely to fail if renderDetails has issues
                await renderDetails(currentSelection); // Re-render details
            } catch (detailsError) {
                console.error(`Error rendering details for ${selectedPath}:`, detailsError);
                // Clear details pane on error, but tree and actions might still be okay
                clearSelection();
                showErrorAlert("Detail Render Error", `Could not render details for ${selectedPath}.\n\nError: ${detailsError.message}`);
            }
        } else if (selectedPath) {
            // Selection existed before but object is gone now
            //console.log(`Selected item ${selectedPath} (Type: ${selectedType}) no longer found after refresh.`);
            clearSelection();
        } else {
            // No selection previously, or it wasn't found. Ensure cleared state.
            clearSelection();
        }
        // If there was no previous selection, clearSelection was called by renderTree if needed


        // Restore tab state (do this *after* potential renderDetails errors)
        try {
            const tabToActivate = document.getElementById(activeTabId);
            // Ensure tab exists AND is not disabled before trying to activate
            if (tabToActivate && !tabToActivate.disabled) {
                const tabInstance = bootstrap.Tab.getOrCreateInstance(tabToActivate);
                if (tabInstance) tabInstance.show(); // Ensure instance exists before showing
            } else {
                // Fallback to dashboard tab first, then properties
                const dashboardTab = document.getElementById('dashboard-tab-button');
                if (dashboardTab && !dashboardTab.disabled) {
                    const dashboardInstance = bootstrap.Tab.getOrCreateInstance(dashboardTab);
                    if (dashboardInstance) dashboardInstance.show();
                } else {
                    const propertiesTab = document.getElementById('properties-tab-button');
                    // Ensure properties tab itself is enabled before showing
                    if (propertiesTab && !propertiesTab.disabled) {
                        const propertiesInstance = bootstrap.Tab.getOrCreateInstance(propertiesTab);
                        if (propertiesInstance) propertiesInstance.show();
                    } else if (document.getElementById('details-tab').querySelector('.nav-link:not(.disabled)')) {
                        // If properties also disabled, try activating the *first available* enabled tab
                        const firstEnabledTab = document.getElementById('details-tab').querySelector('.nav-link:not(.disabled)');
                        if(firstEnabledTab) {
                            const firstEnabledInstance = bootstrap.Tab.getOrCreateInstance(firstEnabledTab);
                            if(firstEnabledInstance) firstEnabledInstance.show();
                        }
                    }
                }
            }
        } catch(tabError) {
            console.error("Error restoring active tab:", tabError);
            // Attempt to activate dashboard tab as a last resort
            try {
                const dashboardTab = document.getElementById('dashboard-tab-button');
                if (dashboardTab && !dashboardTab.disabled) {
                    const dashboardInstance = bootstrap.Tab.getOrCreateInstance(dashboardTab);
                    if (dashboardInstance) dashboardInstance.show();
                }
            } catch (fallbackError) {
                console.error("Error activating fallback dashboard tab:", fallbackError);
            }
        }

        // Update action states again *after* details render attempt and tab restoration
        updateActionStates();

        success = true; // Mark as successful if we got this far without throwing

    } catch (error) {
        console.error("Failed to fetch ZFS data:", error);
        zfsTree.innerHTML = `<div class="alert alert-danger" role="alert">Failed to load ZFS data: ${error.message}</div>`;
        showErrorAlert("Data Load Error", `Could not load pool/dataset information. Please ensure the ZFS daemon is running and accessible.\n\nError: ${error.message}${error.details ? '\nDetails: '+error.details : ''}`);
        zfsDataCache = null; // Clear cache on error
        clearSelection(); // Clear selection and details
        updateActionStates(); // Ensure actions are disabled
    } finally {
        // Ensure loading state is always removed
        setLoadingState(false);
        //console.log("fetchAndRenderData finished. Success:", success);
    }
    // --- END REVISED fetchAndRenderData ---
}

// --- Event Handlers ---

function handleTreeToggle(event) {
    event.stopPropagation(); // Prevent item selection when clicking toggle
    const icon = event.target;
    const li = icon.closest('li');
    const childrenDiv = li.querySelector(':scope > .tree-children'); // Direct child
    if (childrenDiv) {
        const isVisible = childrenDiv.style.display === 'block';
        childrenDiv.style.display = isVisible ? 'none' : 'block';
        icon.classList.toggle('bi-caret-right-fill', isVisible);
        icon.classList.toggle('bi-caret-down-fill', !isVisible);
        // Update expanded state set (use path of the tree-item under this li)
        const treeItemDiv = li.querySelector(':scope > .tree-item');
        const itemPath = treeItemDiv?.dataset?.path;
        const itemType = treeItemDiv?.dataset?.type;
        if (itemPath) {
            const nodeKey = nodeStorageKey(itemPath, itemType);
            if (!isVisible) {
                // it is now visible (expanded)
                expandedNodePaths.add(nodeKey);
            } else {
                // it is now hidden (collapsed)
                expandedNodePaths.delete(nodeKey);
            }
            saveExpandedNodes();
        }
    }
}

async function handleTreeItemClick(event) { // Make async
    const targetItem = event.currentTarget;
    const path = targetItem.dataset.path;
    const type = targetItem.dataset.type; // *** Get the type ***
    if (!path || !type) { // Check type as well
        console.warn("Clicked tree item missing data-path or data-type attribute.");
        return;
    }

    // Remove selection from any previously selected items (in case multiple are mistakenly selected)
    zfsTree.querySelectorAll('.tree-item.selected').forEach(el => el.classList.remove('selected'));

    // Add selection to clicked item
    targetItem.classList.add('selected');
    
    // --- START REVISED: Show the main tab content area ---
    if (detailsTabContent) {
        detailsTabContent.style.visibility = 'visible'; // Make the whole tab area visible
        detailsTabContent.style.opacity = '1';
    } else {
        console.warn("handleTreeItemClick: detailsTabContent element not found!");
    }
    // --- END REVISED ---

    // Find the corresponding object in the cache using path AND type hint
    currentSelection = findObjectByPath(path, type); // *** Pass the type ***
    //console.log("Selected:", currentSelection?.name, "(Type:", currentSelection?.obj_type, ") Data:", currentSelection); // Log type

    if (currentSelection) {
        try {
            // Render details (await as it fetches properties)
            await renderDetails(currentSelection);
            // Update actions *after* details are rendered
            updateActionStates();
            // Persist selection to localStorage
            saveSelectionToStorage();
        } catch(error) {
            console.error(`Error rendering details on click for ${path} (Type: ${type}):`, error);
            showErrorAlert("Detail Render Error", `Could not render details for ${path}.\n\nError: ${error.message}`);
            clearSelection(); // Clear the right pane if details fail
            updateActionStates(); // Update actions for cleared state
        }
    } else {
        console.warn("Could not find object for path:", path, "and type:", type);
        clearSelection();
        updateActionStates();
    }
}

function clearSelection() {
    currentSelection = null;
    currentProperties = null;
    currentPoolStatusText = null;
    currentPoolLayout = null;
    zfsTree.querySelectorAll('.tree-item.selected').forEach(el => el.classList.remove('selected'));
    // Persist cleared selection
    saveSelectionToStorage();
    // Clear dashboard
    renderDashboard(null);
    // --- START REVISED: Hide the tab content area ---
    if (detailsTabContent) {
        detailsTabContent.style.visibility = 'hidden'; // Hide the tab content
        detailsTabContent.style.opacity = '0';
    } else {
        console.warn("clearSelection: detailsTabContent element not found!");
    }
     // Also reset the title
    if (detailsTitle) detailsTitle.textContent = 'Details';
    // --- END REVISED ---
    // Update Pool Edit actions when selection is cleared
    updatePoolEditActionStates(null);
    // NOTE: updateActionStates() will be called by the function *triggering* the clear (e.g., fetch, click failure)
}

// --- Action States ---

function updateActionStates() {
    const obj = currentSelection;
    // Add more detailed logging
    //console.log("[updateActionStates] Called. currentSelection:", JSON.stringify(obj, (key, value) => key === 'children' || key === 'snapshots' ? (Array.isArray(value) ? `[${value.length} items]` : value) : value, 2));
    //console.log("Updating actions for selection:", obj?.name, "Type:", obj?.obj_type, "is_mounted:", obj?.is_mounted, "props.mounted:", obj?.properties?.mounted);
    const isPool = obj?.obj_type === 'pool';
    // *** This is the core check ***
    const isDataset = obj?.obj_type === 'dataset'; // Should be true for root and child datasets
    const isVolume = obj?.obj_type === 'volume';
    const isFilesystem = isDataset || isVolume;
    const props = obj?.properties || {};
    const isClone = isFilesystem && props.origin && props.origin !== '-';
    // Use the specific 'is_mounted' boolean field from the backend data if available, fallback to property otherwise
    const isMounted = (obj && typeof obj.is_mounted === 'boolean') ? obj.is_mounted : (props.mounted === 'yes');

    // --- Pool Actions ---
    document.getElementById('create-pool-button').classList.remove('disabled');
    document.getElementById('import-pool-button').classList.remove('disabled');

    document.getElementById('destroy-pool-button').classList.toggle('disabled', !isPool);
    document.getElementById('export-pool-button').classList.toggle('disabled', !isPool);
    // Scrub buttons depend on pool selection AND scrub status (potentially parsed later)
    document.getElementById('scrub-start-button').classList.toggle('disabled', !isPool);
    document.getElementById('scrub-stop-button').classList.toggle('disabled', !isPool);
    document.getElementById('clear-errors-button').classList.toggle('disabled', !isPool);


    // --- Dataset Actions ---
    const canCreateDataset = isPool || isFilesystem;
    document.getElementById('create-dataset-button').classList.toggle('disabled', !canCreateDataset);
    //console.log(`Create Dataset Button - Enabled: ${canCreateDataset} (isPool: ${isPool}, isFilesystem: ${isFilesystem})`);

    document.getElementById('destroy-dataset-button').classList.toggle('disabled', !isFilesystem);
    document.getElementById('rename-dataset-button').classList.toggle('disabled', !isFilesystem);

    // *** Mount/Unmount Logic (Relies on isDataset being correct now) ***
    const canMount = isDataset && !isMounted;
    document.getElementById('mount-dataset-button').classList.toggle('disabled', !canMount);
    //console.log(`Mount Button - Enabled: ${canMount} (isDataset: ${isDataset}, isMounted: ${isMounted})`);

    const canUnmount = isDataset && isMounted;
    document.getElementById('unmount-dataset-button').classList.toggle('disabled', !canUnmount);
    //console.log(`Unmount Button - Enabled: ${canUnmount} (isDataset: ${isDataset}, isMounted: ${isMounted})`);

    document.getElementById('promote-dataset-button').classList.toggle('disabled', !isClone);

    // Snapshot Actions (controlled within snapshot tab rendering)

    // Encryption Actions (controlled within encryption tab rendering)
    const encTabButton = document.getElementById('encryption-tab-button');
    // --- FIX: Check if obj exists before accessing properties for encryption check ---
    if(encTabButton && !encTabButton.disabled && obj && obj.is_encrypted) {
        renderEncryptionInfo(obj);
    } else if (encTabButton && !encTabButton.disabled && obj && !obj.is_encrypted) {
        // If dataset not encrypted, disable all buttons
        document.getElementById('load-key-button').disabled = true;
        document.getElementById('unload-key-button').disabled = true;
        document.getElementById('change-key-button').disabled = true;
        document.getElementById('change-key-location-button').disabled = true;
    } else if (encTabButton && !encTabButton.disabled && !obj) {
        // If the tab is somehow enabled but no object is selected, disable buttons
        document.getElementById('load-key-button').disabled = true;
        document.getElementById('unload-key-button').disabled = true;
        document.getElementById('change-key-button').disabled = true;
        document.getElementById('change-key-location-button').disabled = true;
    }


    // Pool Edit actions (controlled by updatePoolEditActionStates)
    const selectedEditItem = poolEditTreeContainer.querySelector('.selected');
    updatePoolEditActionStates(selectedEditItem);

    // Check pool status for scrub state more accurately if status text is available
    if (isPool && currentPoolStatusText) {
        const scrubRunning = currentPoolStatusText.includes('scrub in progress') || currentPoolStatusText.includes('resilver in progress');
        document.getElementById('scrub-start-button').classList.toggle('disabled', !isPool || scrubRunning);
        document.getElementById('scrub-stop-button').classList.toggle('disabled', !isPool || !scrubRunning);
    } else if (isPool) {
        // If pool but no status text, disable scrub stop button defensively
        document.getElementById('scrub-stop-button').classList.add('disabled');
    }
}


// --- END OF SECTION 3 ---

// --- START OF SECTION 4 ---

// --- Utility Function - findObjectByPath ---
// Updated to accept an optional typeHint for disambiguation
function findObjectByPath(path, typeHint = null, items = zfsDataCache) {
    if (!items || !path) return null;
    let firstMatchByName = null; // Store first item matching name only

    for (const item of items) {
        // Check for match by name first
        if (item.name === path) {
            // If typeHint is provided, check if the object's type matches
            if (typeHint && item.obj_type === typeHint) {
                // Exact match (name and type) - return immediately
                return item;
            }
            // If no typeHint OR type didn't match, store this as a potential candidate
            // (We prioritize the type match if found later or recursively)
            if (firstMatchByName === null) {
                firstMatchByName = item;
            }
        }

        // Recursive search in children
        if (item.children && item.children.length > 0) {
            // Pass typeHint down recursively
            const found = findObjectByPath(path, typeHint, item.children);
            if (found) {
                // If found recursively, it must be the correct match (either exact or best found so far)
                return found;
            }
        }
    }
    // Loop finished. If an exact match (name+type) was found, it would have returned.
    // If not, return the first item that matched by name only (could be null).
    return firstMatchByName;
}


// --- Utility Function - formatSize ---
function formatSize(value) { // Changed parameter name from bytes for clarity
    // Handle non-numeric, null, undefined, and special string values
    if (value === null || value === undefined || value === '-' || value === '') return "-";

    const valueStr = String(value).trim();

    // Handle specific non-numeric values expected from ZFS properties
    const knownStrings = ['on', 'off', 'yes', 'no', 'none', 'default', 'local', 'standard', 'always', 'disabled', 'latency', 'throughput', 'passphrase', 'hex', 'raw', 'available', 'unavailable'];
    if (knownStrings.includes(valueStr.toLowerCase())) {
        return valueStr;
    }
    // Handle "inherited from..." and "received" values
    if (valueStr.toLowerCase().startsWith('inherited from') || valueStr.toLowerCase().startsWith('received')) {
        return valueStr;
    }
    // Handle ratios like '1.00x'
    if (/^\d+(\.\d+)?x$/i.test(valueStr)) {
        return valueStr;
    }

    // Handle potentially very large numbers as strings from backend or numbers
    // Allow optional leading '-' for negative numbers (though size shouldn't be negative)
    if (!/^-?\d+(\.\d+)?$/.test(valueStr)) {
        // If it doesn't look like a plain number, return original value after handling known strings/patterns
        return valueStr;
    }

    // Now parse as number
    const bytes = parseFloat(valueStr);

    // Handle parsing errors or negative numbers (shouldn't happen for size, but defensively)
    if (isNaN(bytes) || bytes < 0) return valueStr;
    if (bytes === 0) return "0B";

    const units = ['B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y'];
    let i = 0;
    let size = bytes;
    // Use 1024 for K, M, G etc.
    while (size >= 1024 && i < units.length - 1) {
        size /= 1024.0;
        i++;
    }

    // Adjust precision based on unit and value
    if (i === 0) return `${Math.round(size)}${units[i]}`; // Bytes, no decimals
    if (size < 10) return `${size.toFixed(2)}${units[i]}`; // e.g., 9.87K
    if (size < 100) return `${size.toFixed(1)}${units[i]}`; // e.g., 98.7K
    return `${Math.round(size)}${units[i]}`; // e.g., 101K, 1.2G -> 1G (rounding)
}

// --- Rendering Functions ---

// --- Dashboard Rendering Functions ---
function renderDashboard(obj) {
    const dashboardName = document.getElementById('dashboard-name');
    const dashboardTypeBadge = document.getElementById('dashboard-type-badge');
    const dashboardHealthBadge = document.getElementById('dashboard-health-badge');
    const dashboardHealthText = document.getElementById('dashboard-health-text');
    const primaryStorageWrapper = document.getElementById('primary-storage-wrapper');
    const secondaryStorageWrapper = document.getElementById('secondary-storage-wrapper');
    const generalInfo = document.getElementById('dashboard-general-info');
    const configInfo = document.getElementById('dashboard-config-info');
    const statsInfo = document.getElementById('dashboard-stats-info');
    const systemInfo = document.getElementById('dashboard-system-info');

    // Reset to default state
    if (!obj) {
        if (dashboardName) dashboardName.textContent = 'Select a pool or dataset';
        if (dashboardTypeBadge) dashboardTypeBadge.style.display = 'none';
        if (dashboardHealthBadge) dashboardHealthBadge.style.display = 'none';
        clearStorageBar('primary');
        if (secondaryStorageWrapper) secondaryStorageWrapper.style.display = 'none';
        if (generalInfo) generalInfo.innerHTML = '<div class="info-row"><span class="info-label"></span><span class="info-value muted">Select an item from the tree to view its dashboard</span></div>';
        if (configInfo) configInfo.innerHTML = '<div class="info-row"><span class="info-label">-</span><span class="info-value">-</span></div>';
        if (statsInfo) statsInfo.innerHTML = '<div class="info-row"><span class="info-label">-</span><span class="info-value">-</span></div>';
        renderSystemInfo(systemInfo);
        return;
    }

    const isPool = obj.obj_type === 'pool';
    const isDataset = obj.obj_type === 'dataset';
    const isVolume = obj.obj_type === 'volume';
    const isSnapshot = obj.obj_type === 'snapshot';

    // Set name
    if (dashboardName) dashboardName.textContent = obj.name;

    // Set type badge
    if (dashboardTypeBadge) {
        let typeText = obj.obj_type.toUpperCase();
        let typeClass = obj.obj_type;
        dashboardTypeBadge.textContent = typeText;
        dashboardTypeBadge.className = 'dashboard-type-badge ' + typeClass;
        dashboardTypeBadge.style.display = 'inline-block';
    }

    // Set health/status badge
    if (dashboardHealthBadge && dashboardHealthText) {
        if (isPool) {
            const health = (obj.health || 'UNKNOWN').toUpperCase();
            dashboardHealthText.textContent = health;
            dashboardHealthBadge.className = 'dashboard-health-badge ' + health.toLowerCase();
            dashboardHealthBadge.style.display = 'inline-flex';
        } else if (isDataset) {
            const mounted = obj.is_mounted;
            dashboardHealthText.textContent = mounted ? 'MOUNTED' : 'UNMOUNTED';
            dashboardHealthBadge.className = 'dashboard-health-badge ' + (mounted ? 'mounted' : 'unmounted');
            dashboardHealthBadge.style.display = 'inline-flex';
        } else {
            dashboardHealthBadge.style.display = 'none';
        }
    }

    // Render storage bars
    if (isPool) {
        renderStorageBar('primary', obj.alloc || 0, obj.size || 0, 'Pool Capacity');
        if (secondaryStorageWrapper) secondaryStorageWrapper.style.display = 'none';
    } else if (isDataset || isVolume) {
        const total = (obj.used || 0) + (obj.available || 0);
        renderStorageBar('primary', obj.used || 0, total, 'Space Used');
        if (obj.referenced && obj.referenced > 0) {
            renderStorageBar('secondary', obj.referenced, total, 'Referenced Data');
            if (secondaryStorageWrapper) secondaryStorageWrapper.style.display = 'block';
        } else {
            if (secondaryStorageWrapper) secondaryStorageWrapper.style.display = 'none';
        }
    } else if (isSnapshot) {
        renderStorageBar('primary', obj.used || 0, obj.referenced || obj.used || 0, 'Snapshot Size');
        if (secondaryStorageWrapper) secondaryStorageWrapper.style.display = 'none';
    } else {
        clearStorageBar('primary');
        if (secondaryStorageWrapper) secondaryStorageWrapper.style.display = 'none';
    }

    // Render info cards based on type
    if (isPool) {
        renderPoolDashboardInfo(obj, generalInfo, configInfo, statsInfo);
    } else if (isDataset || isVolume) {
        renderDatasetDashboardInfo(obj, generalInfo, configInfo, statsInfo);
    } else if (isSnapshot) {
        renderSnapshotDashboardInfo(obj, generalInfo, configInfo, statsInfo);
    }

    // System info
    renderSystemInfo(systemInfo, obj);
}

function renderStorageBar(prefix, used, total, label) {
    const labelEl = document.getElementById(`${prefix}-storage-label`);
    const percentEl = document.getElementById(`${prefix}-storage-percent`);
    const barEl = document.getElementById(`${prefix}-storage-bar`);
    const usedEl = document.getElementById(`${prefix}-storage-used`);
    const freeEl = document.getElementById(`${prefix}-storage-free`);
    const totalEl = document.getElementById(`${prefix}-storage-total`);

    if (!barEl) return;

    let percentage = 0;
    let free = 0;

    if (total > 0) {
        percentage = Math.min(100, Math.round((used / total) * 100));
        free = Math.max(0, total - used);
    }

    if (labelEl) labelEl.textContent = label;
    if (percentEl) percentEl.textContent = `${percentage}%`;

    barEl.style.width = `${percentage}%`;
    barEl.setAttribute('aria-valuenow', percentage);

    // Color coding based on usage
    barEl.classList.remove('warning', 'danger', 'info');
    if (prefix === 'secondary') {
        barEl.classList.add('info');
    } else if (percentage >= 90) {
        barEl.classList.add('danger');
    } else if (percentage >= 75) {
        barEl.classList.add('warning');
    }

    if (usedEl) usedEl.textContent = `Used: ${formatSize(used)}`;
    if (freeEl) freeEl.textContent = `Free: ${formatSize(free)}`;
    if (totalEl) totalEl.textContent = `Total: ${formatSize(total)}`;
}

function clearStorageBar(prefix) {
    const labelEl = document.getElementById(`${prefix}-storage-label`);
    const percentEl = document.getElementById(`${prefix}-storage-percent`);
    const barEl = document.getElementById(`${prefix}-storage-bar`);
    const usedEl = document.getElementById(`${prefix}-storage-used`);
    const freeEl = document.getElementById(`${prefix}-storage-free`);
    const totalEl = document.getElementById(`${prefix}-storage-total`);

    if (labelEl) labelEl.textContent = 'Storage';
    if (percentEl) percentEl.textContent = '0%';
    if (barEl) {
        barEl.style.width = '0%';
        barEl.setAttribute('aria-valuenow', 0);
        barEl.classList.remove('warning', 'danger', 'info');
    }
    if (usedEl) usedEl.textContent = 'Used: -';
    if (freeEl) freeEl.textContent = 'Free: -';
    if (totalEl) totalEl.textContent = 'Total: -';
}

function createInfoRow(label, value, valueClass = '') {
    const classAttr = valueClass ? ` class="info-value ${valueClass}"` : ' class="info-value"';
    return `<div class="info-row"><span class="info-label">${label}</span><span${classAttr}>${value}</span></div>`;
}

function renderPoolDashboardInfo(pool, generalInfo, configInfo, statsInfo) {
    const props = pool.properties || {};
    const health = (pool.health || 'UNKNOWN').toUpperCase();
    const healthClass = health === 'ONLINE' ? 'success' : (health === 'DEGRADED' ? 'warning' : 'danger');

    // General Info
    if (generalInfo) {
        generalInfo.innerHTML = 
            createInfoRow('Name:', pool.name) +
            createInfoRow('Health:', health, healthClass) +
            createInfoRow('GUID:', pool.guid || '-') +
            createInfoRow('Version:', props.version || '-') +
            createInfoRow('Altroot:', props.altroot || '-');
    }

    // Config Info
    if (configInfo) {
        configInfo.innerHTML = 
            createInfoRow('Deduplication:', pool.dedup || 'off') +
            createInfoRow('Fragmentation:', pool.frag || '-') +
            createInfoRow('Capacity:', pool.cap || '-') +
            createInfoRow('Autotrim:', props.autotrim || '-') +
            createInfoRow('Autoexpand:', props.autoexpand || '-') +
            createInfoRow('Failmode:', props.failmode || '-');
    }

    // Stats Info
    if (statsInfo) {
        const numDatasets = countDatasetsInPool(pool);
        const numSnapshots = countSnapshotsInPool(pool);
        statsInfo.innerHTML = 
            createInfoRow('Total Size:', formatSize(pool.size)) +
            createInfoRow('Allocated:', formatSize(pool.alloc)) +
            createInfoRow('Free:', formatSize(pool.free)) +
            createInfoRow('Datasets:', numDatasets) +
            createInfoRow('Snapshots:', numSnapshots);
    }
}

function renderDatasetDashboardInfo(dataset, generalInfo, configInfo, statsInfo) {
    const props = dataset.properties || {};

    // General Info
    if (generalInfo) {
        generalInfo.innerHTML = 
            createInfoRow('Name:', dataset.name) +
            createInfoRow('Pool:', dataset.pool_name || '-') +
            createInfoRow('Type:', (dataset.obj_type || 'dataset').charAt(0).toUpperCase() + (dataset.obj_type || 'dataset').slice(1)) +
            createInfoRow('Mountpoint:', dataset.mountpoint || '-') +
            createInfoRow('Mounted:', dataset.is_mounted ? 'Yes' : 'No', dataset.is_mounted ? 'success' : 'muted');
    }

    // Config Info
    if (configInfo) {
        let configHtml = 
            createInfoRow('Compression:', props.compression || '-') +
            createInfoRow('Dedup:', props.dedup || '-') +
            createInfoRow('Atime:', props.atime || '-') +
            createInfoRow('Sync:', props.sync || '-') +
            createInfoRow('Record Size:', props.recordsize || '-');

        if (dataset.is_encrypted) {
            configHtml += createInfoRow('Encrypted:', 'Yes', 'danger') +
                         createInfoRow('Key Status:', props.keystatus || '-');
        } else {
            configHtml += createInfoRow('Encrypted:', 'No');
        }
        configInfo.innerHTML = configHtml;
    }

    // Stats Info
    if (statsInfo) {
        const numChildren = dataset.children ? dataset.children.length : 0;
        const numSnapshots = dataset.snapshots ? dataset.snapshots.length : 0;
        let statsHtml = 
            createInfoRow('Used:', formatSize(dataset.used)) +
            createInfoRow('Available:', formatSize(dataset.available)) +
            createInfoRow('Referenced:', formatSize(dataset.referenced)) +
            createInfoRow('Child Datasets:', numChildren) +
            createInfoRow('Snapshots:', numSnapshots);

        const quota = props.quota;
        const refquota = props.refquota;
        if (quota && quota !== 'none' && quota !== '-' && quota !== '0') {
            statsHtml += createInfoRow('Quota:', quota);
        }
        if (refquota && refquota !== 'none' && refquota !== '-' && refquota !== '0') {
            statsHtml += createInfoRow('Ref Quota:', refquota);
        }
        statsInfo.innerHTML = statsHtml;
    }
}

function renderSnapshotDashboardInfo(snapshot, generalInfo, configInfo, statsInfo) {
    const props = snapshot.properties || {};

    // Extract snapshot name
    const snapName = snapshot.name.includes('@') ? snapshot.name.split('@')[1] : snapshot.name;
    const parentDs = snapshot.name.includes('@') ? snapshot.name.split('@')[0] : '-';

    // General Info
    if (generalInfo) {
        generalInfo.innerHTML = 
            createInfoRow('Snapshot:', snapName) +
            createInfoRow('Dataset:', parentDs) +
            createInfoRow('Pool:', snapshot.pool_name || '-') +
            createInfoRow('Created:', snapshot.creation_time || '-');
    }

    // Config Info
    if (configInfo) {
        configInfo.innerHTML = 
            createInfoRow('Clones:', props.clones || '-') +
            createInfoRow('Defer Destroy:', props.defer_destroy || '-') +
            createInfoRow('Hold Tags:', props.userrefs || '-');
    }

    // Stats Info
    if (statsInfo) {
        statsInfo.innerHTML = 
            createInfoRow('Used:', formatSize(snapshot.used)) +
            createInfoRow('Referenced:', formatSize(snapshot.referenced));
    }
}

function renderSystemInfo(systemInfo, obj = null) {
    if (!systemInfo) return;

    // Basic system info (platform detection happens server-side, we show generic info)
    let html = createInfoRow('Application:', 'ZfDash Web UI');

    if (obj && obj.obj_type === 'pool' && obj.properties) {
        const zfsVersion = obj.properties.version;
        if (zfsVersion && zfsVersion !== '-') {
            html += createInfoRow('ZFS Version:', zfsVersion);
        }
    }

    systemInfo.innerHTML = html;
}

function countDatasetsInPool(pool) {
    let count = 0;
    if (pool.children) {
        pool.children.forEach(child => {
            count += 1 + countDatasetsRecursive(child);
        });
    }
    return count;
}

function countDatasetsRecursive(dataset) {
    let count = 0;
    if (dataset.children) {
        dataset.children.forEach(child => {
            count += 1 + countDatasetsRecursive(child);
        });
    }
    return count;
}

function countSnapshotsInPool(pool) {
    let count = 0;
    if (pool.children) {
        pool.children.forEach(child => {
            count += countSnapshotsRecursive(child);
        });
    }
    return count;
}

function countSnapshotsRecursive(dataset) {
    let count = dataset.snapshots ? dataset.snapshots.length : 0;
    if (dataset.children) {
        dataset.children.forEach(child => {
            count += countSnapshotsRecursive(child);
        });
    }
    return count;
}

// --- End Dashboard Rendering Functions ---

async function renderDetails(obj) { // Made async
    if (!obj) {
        // If called with null obj after showing content, clear title and potentially show placeholder again or a message
        if (detailsTitle) detailsTitle.textContent = 'Details';
        // --- START REVISED: Hide the tab content area ---
        if (detailsTabContent) {
             detailsTabContent.style.visibility = 'hidden'; // Hide the tab content
             detailsTabContent.style.opacity = '0';
        } else {
             console.warn("renderDetails: detailsTabContent element not found when clearing!");
        }
        // --- END REVISED ---
        // Clear dashboard
        renderDashboard(null);
        console.warn("renderDetails called with null object.");
        return; // Exit early if no object
    }

    // We have an object, set title first
    if (detailsTitle) detailsTitle.textContent = `${obj.obj_type.charAt(0).toUpperCase() + obj.obj_type.slice(1)}: ${obj.name}`;

    // --- START REVISED: Show the tab content area ---
    if (detailsTabContent) {
        detailsTabContent.style.visibility = 'visible'; // Ensure visible
        detailsTabContent.style.opacity = '1';
    } else {
        console.warn("renderDetails: detailsTabContent element not found when showing content!");
    }
    // --- END REVISED ---

    // --- Tab Enabling/Disabling ---
    // Ensure all potentially relevant tabs are handled
    const isPool = obj.obj_type === 'pool';
    // A root dataset ALSO has obj_type === 'dataset'
    const isDataset = obj.obj_type === 'dataset';
    const isVolume = obj.obj_type === 'volume';
    const isDatasetOrVol = isDataset || isVolume;
    const isEncrypted = obj.is_encrypted;

    // Dashboard is always enabled
    const dashboardTabButton = document.getElementById('dashboard-tab-button');
    if (dashboardTabButton) dashboardTabButton.disabled = false;

    // Always enable properties tab if an object is selected
    document.getElementById('properties-tab-button').disabled = false;

    // Enable/disable other tabs based on type
    document.getElementById('snapshots-tab-button').disabled = !isDatasetOrVol;
    document.getElementById('pool-status-tab-button').disabled = !isPool;
    document.getElementById('pool-edit-tab-button').disabled = !isPool;
    document.getElementById('encryption-tab-button').disabled = !isEncrypted; // Only enable if actually encrypted

    // --- Clear/Populate Tab Content ---
    // Render dashboard first (always available)
    renderDashboard(obj);

    // Properties (handled below by fetching)
    renderProperties(null, true); // Show loading state

    // Snapshots
    if (isDatasetOrVol) {
        renderSnapshots(obj.snapshots || []); // Use cached snapshots first
    } else {
        renderSnapshots([]); // Clear snapshot table if not applicable
    }

    // Pool Status
    if (isPool) {
        currentPoolStatusText = obj.status_details || ''; // Update cache
        renderPoolStatus(currentPoolStatusText); // Use cached status
    } else {
        renderPoolStatus(''); // Clear pool status if not a pool
    }

    // Pool Edit Layout
    if (isPool) {
        // Parse and render layout using updated text
        // Note: renderPoolEditLayout might also update currentPoolLayout cache internally
        renderPoolEditLayout(currentPoolStatusText);
    } else {
        renderPoolEditLayout(''); // Clear pool edit layout if not a pool
    }

    // Encryption Info
    // --- START MODIFICATION: Check if tab enabled before rendering ---
    const encTabButton = document.getElementById('encryption-tab-button');
    // Only render if the object is encrypted AND the tab itself isn't disabled
    if (isEncrypted && encTabButton && !encTabButton.disabled) {
        renderEncryptionInfo(obj); // Render based on current obj data
    } else {
        // If not encrypted or tab disabled, ensure buttons are disabled (defensive)
        renderEncryptionInfo(null, true); // Pass flag to just disable buttons
    }
    // --- END MODIFICATION ---


    // --- Fetch and render properties ---
    try {
        // Ensure properties are fetched even on refresh if object selected
        const propsResult = await apiCall(`/api/properties/${encodeURIComponent(obj.name)}`);
        currentProperties = propsResult.data; // Update cache
        renderProperties(currentProperties);
    } catch (error) {
        console.error("Failed to fetch properties:", error);
        currentProperties = null; // Clear cache on error
        propertiesTableBody.innerHTML = `<tr><td colspan="4" class="text-danger text-center">Failed to load properties: ${error.message}</td></tr>`;
    }

    // Tab activation logic is handled by fetchAndRenderData restoration
}

function renderProperties(props, isLoading = false) {
    propertiesTableBody.innerHTML = ''; // Clear existing
    if (isLoading) {
        propertiesTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-muted"><span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading properties...</td></tr>`;
        return;
    }
    if (!props) { // Handle null props after loading finished (e.g., fetch error)
        propertiesTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-danger">Failed to load properties or none available.</td></tr>`;
        return;
    }
    // If props is an empty object (valid fetch, but no props set/returned)
    if (Object.keys(props).length === 0 && !Object.keys(window.EDITABLE_PROPERTIES_WEB || {}).length > 0) {
         propertiesTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">No properties available for this item.</td></tr>`;
         return;
    }

    // Get all property keys returned by the backend
    const fetchedKeys = Object.keys(props);
    
    // Separate editable and non-editable properties
    const editableKeys = [];
    const nonEditableKeys = [];
    
    // Process fetched properties first
    fetchedKeys.forEach(key => {
        // Check if property is defined as editable in our config
        const editInfo = window.EDITABLE_PROPERTIES_WEB?.[key];
        let isEditable = false;
        if (editInfo) {
            // Check readOnlyFunc if it exists
             const isReadOnlyForObject = editInfo.readOnlyFunc && editInfo.readOnlyFunc(currentSelection);
             isEditable = !isReadOnlyForObject;
        }
        
        if (isEditable) {
            editableKeys.push(key);
        } else {
            nonEditableKeys.push(key);
        }
    });

    // --- START: Add missing editable properties ---
    // Now check for editable properties defined in config but NOT returned by backend
    Object.keys(window.EDITABLE_PROPERTIES_WEB || {}).forEach(editableKey => {
        if (!props.hasOwnProperty(editableKey)) { // If not found in fetched props
             const editInfo = window.EDITABLE_PROPERTIES_WEB[editableKey];
             // Check if readOnlyFunc makes it non-editable for the current object
             const isReadOnlyForObject = editInfo.readOnlyFunc && editInfo.readOnlyFunc(currentSelection);
             if (!isReadOnlyForObject) {
                 // Only add if not already somehow present in editableKeys
                 if (!editableKeys.includes(editableKey)) { 
                    editableKeys.push(editableKey);
                 }
             } else {
                 // If read-only for this object, add to non-editable list if not already there
                 if (!nonEditableKeys.includes(editableKey) && !editableKeys.includes(editableKey)) {
                      nonEditableKeys.push(editableKey);
                 }
             }
        }
    });
    // --- END: Add missing editable properties ---

    // Sort editable keys: Auto-snapshot first by custom order, then others alphabetically
    const autoSnapshotEditable = editableKeys.filter(k => AUTO_SNAPSHOT_PROPS.includes(k)).sort((a, b) => {
        const indexA = AUTO_SNAPSHOT_SORT_ORDER_WEB.indexOf(a);
        const indexB = AUTO_SNAPSHOT_SORT_ORDER_WEB.indexOf(b);
        // Handle cases where a key might not be in the sort order list (shouldn't happen here)
        if (indexA === -1 && indexB === -1) return a.localeCompare(b); // Fallback alpha sort
        if (indexA === -1) return 1; // Place unknown at end
        if (indexB === -1) return -1; // Place unknown at end
        return indexA - indexB;
    });
    const otherEditable = editableKeys.filter(k => !AUTO_SNAPSHOT_PROPS.includes(k)).sort();
    const sortedEditableKeys = [...autoSnapshotEditable, ...otherEditable];

    // Sort non-editable keys alphabetically
    nonEditableKeys.sort();
    
    // --- Render Sections ---
    // Add section header for editable properties if any exist
    if (sortedEditableKeys.length > 0) {
        const headerRow = propertiesTableBody.insertRow();
        headerRow.className = "table-primary table-group-header"; // Add class for potential styling
        headerRow.innerHTML = `<td colspan="4"><strong>Editable Properties</strong></td>`;
        
        // Render editable properties (pass the sorted keys)
        renderPropertyGroup(sortedEditableKeys, props, true);
        
        // Add spacing row only if there are also non-editable properties
        if (nonEditableKeys.length > 0) {
            const spacerRow = propertiesTableBody.insertRow();
            spacerRow.className = "table-light";
            spacerRow.style.height = "8px";
            spacerRow.innerHTML = `<td colspan="4"></td>`;
        }
    }
    
    // Render non-editable properties if any exist
    if (nonEditableKeys.length > 0) {
        // Add section header for non-editable properties
        const nonEditableHeader = propertiesTableBody.insertRow();
        nonEditableHeader.className = "table-secondary table-group-header"; // Add class
        // Adjust header text based on whether editable properties were shown
        nonEditableHeader.innerHTML = `<td colspan="4"><strong>${sortedEditableKeys.length > 0 ? 'Other' : 'All'} Properties</strong></td>`;
        
        // Render non-editable properties
        renderPropertyGroup(nonEditableKeys, props, false);
    }

    // Handle case where there were no keys at all (after checking editable)
     if (sortedEditableKeys.length === 0 && nonEditableKeys.length === 0) {
         propertiesTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">No properties available for this item.</td></tr>`;
     }
}

// Helper function to render a group of properties
function renderPropertyGroup(keys, props, isEditable) {
    const datasetName = currentSelection?.name; // Get the name for data attributes

    keys.forEach(key => {
        // --- START: Handle potentially missing propData for unset editable props ---
        const propData = props[key]; // Might be undefined if key was added because it's editable but unset
        const value = propData?.value ?? '-'; // Default to '-' if propData or value is missing
        const source = propData?.source ?? (datasetName?.includes('/') ? 'inherited' : 'default'); // Guess source if missing
        const isInherited = source && !['-', 'local', 'default', 'received'].includes(source);
        const displayValue = (propData === undefined && isEditable) ? '-' : formatSize(value);
        const displaySource = (propData === undefined && isEditable) ? (datasetName?.includes('/') ? 'inherited' : 'default') : (source === '-' ? 'local/default' : source);
        // --- END: Handle potentially missing propData ---
        
        const row = propertiesTableBody.insertRow();
        // Add specific class if it's an editable property, even if read-only for *this* object
        if (window.EDITABLE_PROPERTIES_WEB?.[key]) { 
             row.className = "editable-property-config"; // Use a class to indicate it's generally editable
        }
        // --- Add specific class for master switch ---
        if (key === "com.sun:auto-snapshot") {
            row.classList.add("master-snapshot-switch"); // Add class for CSS styling (e.g., bold)
        }
        // --- End class add ---

        // Render row content
        row.innerHTML = `
        <td><span title="Internal: ${key}">${window.EDITABLE_PROPERTIES_WEB?.[key]?.displayName || key}</span></td>
        <td class="${isInherited ? 'text-muted' : ''}" title="Raw: ${value}">${displayValue}</td>
        <td>${displaySource}</td>
        <td class="text-end"></td>
        `;
        const actionCell = row.cells[3];

        // Add Edit button only if it's *actually* editable for this object
        if (isEditable) {
            const editBtn = document.createElement('button');
            editBtn.className = 'btn properties-table-btn edit-btn me-1'; // *** RESTORED ORIGINAL CLASS ***
            editBtn.innerHTML = '<i class="bi bi-pencil"></i>';
            editBtn.title = `Edit ${key}`;
            // Pass the actual current value ('-' if undefined) to the handler
            editBtn.onclick = () => handleEditProperty(key, value, window.EDITABLE_PROPERTIES_WEB[key]); 
            actionCell.appendChild(editBtn);
        }

        // Allow inherit if source is 'local' or 'received'
        // Do not show inherit button if propData is undefined (it's already inherited/default)
        // Pool properties cannot be inherited (zpool has no inherit command)
        const isPoolProperty = currentSelection?.obj_type === 'pool' && POOL_LEVEL_PROPERTIES.has(key);
        if (propData && (source === 'local' || source === 'received') && !isPoolProperty) {
            const inheritBtn = document.createElement('button');
            inheritBtn.className = 'btn properties-table-btn inherit-btn'; // *** RESTORED ORIGINAL CLASS ***
            inheritBtn.innerHTML = '<i class="bi bi-arrow-down-left-circle"></i>';
            inheritBtn.title = `Inherit ${key}`;
            inheritBtn.onclick = () => handleInheritProperty(key);
            actionCell.appendChild(inheritBtn);
        }
    });
}

function renderSnapshots(snapshots) {
    snapshotsTableBody.innerHTML = ''; // Clear
    // Reset button state regardless of content
    document.getElementById('delete-snapshot-button').disabled = true;
    document.getElementById('rollback-snapshot-button').disabled = true;
    document.getElementById('clone-snapshot-button').disabled = true;
    snapshotsTableBody.dataset.selectedSnapshot = ""; // Clear selected snapshot data

    if (!snapshots || snapshots.length === 0) {
        snapshotsTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">No snapshots available.</td></tr>`;
        return;
    }

    // Sort by creation time (assuming string sort works or backend provides sortable format)
    snapshots.sort((a, b) => (a.properties?.creation || '').localeCompare(b.properties?.creation || ''));

    snapshots.forEach(snap => {
        // Get the full snapshot name safely from properties, fallback if missing
        const fullSnapName = snap.properties?.full_snapshot_name || `${snap.dataset_name}@${snap.name}`;
        const row = snapshotsTableBody.insertRow();
        row.innerHTML = `
        <td><span title="${fullSnapName}">@${snap.name}</span></td>
        <td class="text-end">${formatSize(snap.used)}</td>
        <td class="text-end">${formatSize(snap.referenced)}</td>
        <td>${snap.creation_time || snap.properties?.creation || '-'}</td>
        `;
        // Add click listener to row for selection feedback and enabling buttons
        row.style.cursor = 'pointer';
        row.onclick = () => {
            // Remove selected class from other rows
            snapshotsTableBody.querySelectorAll('tr.table-active').forEach(r => r.classList.remove('table-active'));
            // Add selected class to clicked row
            row.classList.add('table-active');
            // Enable action buttons
            document.getElementById('delete-snapshot-button').disabled = false;
            document.getElementById('rollback-snapshot-button').disabled = false;
            document.getElementById('clone-snapshot-button').disabled = false;
            // Store selected snapshot name (e.g., on the table element or a global var)
            snapshotsTableBody.dataset.selectedSnapshot = fullSnapName;
        };
    });
}


// --- END OF SECTION 4 ---


// --- START OF SECTION 5 ---

function renderPoolStatus(statusText) {
    poolStatusContent.textContent = statusText || 'Pool status not available.';
}

function renderEncryptionInfo(obj) {
    if (!obj) return; // Should not happen if tab is enabled

    const props = obj.properties || {};
    const isEncrypted = props.encryption && props.encryption !== 'off' && props.encryption !== '-';
    const keyStatus = props.keystatus || (isEncrypted ? 'unavailable' : 'N/A'); // Assume unavailable if encrypted but no status
    const isAvailable = keyStatus === 'available';
    const isMounted = obj.is_mounted;

    // --- START MODIFICATION: Add null checks for all getElementById ---
    const encStatusEl = document.getElementById('enc-status');
    if (encStatusEl) encStatusEl.textContent = isEncrypted ? 'Yes' : 'No';

    const encAlgorithmEl = document.getElementById('enc-algorithm');
    if (encAlgorithmEl) encAlgorithmEl.textContent = isEncrypted ? (props.encryption || '-') : '-';

    const encKeyStatusEl = document.getElementById('enc-key-status');
    if (encKeyStatusEl) encKeyStatusEl.textContent = keyStatus.charAt(0).toUpperCase() + keyStatus.slice(1);

    const encKeyLocationEl = document.getElementById('enc-key-location');
    if (encKeyLocationEl) encKeyLocationEl.textContent = isEncrypted ? (props.keylocation || 'prompt') : '-';

    const encKeyFormatEl = document.getElementById('enc-key-format');
    if (encKeyFormatEl) encKeyFormatEl.textContent = isEncrypted ? (props.keyformat || '-') : '-';

    const encPbkdf2itersEl = document.getElementById('enc-pbkdf2iters');
    if (encPbkdf2itersEl) encPbkdf2itersEl.textContent = isEncrypted ? (props.pbkdf2iters || '-') : '-';

    // Enable/disable buttons
    const loadEnabled = isEncrypted && !isAvailable;
    const unloadEnabled = isEncrypted && isAvailable; // Check mount on click
    const changeKeyEnabled = isEncrypted && isAvailable;
    const changeLocEnabled = isEncrypted;

    const loadKeyBtn = document.getElementById('load-key-button');
    if (loadKeyBtn) loadKeyBtn.disabled = !loadEnabled;

    const unloadKeyBtn = document.getElementById('unload-key-button');
    if (unloadKeyBtn) unloadKeyBtn.disabled = !unloadEnabled;

    const changeKeyBtn = document.getElementById('change-key-button');
    if (changeKeyBtn) changeKeyBtn.disabled = !changeKeyEnabled;

    const changeLocBtn = document.getElementById('change-key-location-button');
    if (changeLocBtn) changeLocBtn.disabled = !changeLocEnabled;

    // Update tooltips
    if (loadKeyBtn) {
        loadKeyBtn.title = loadEnabled ? `Load key for ${obj.name}` : "Load Key (Not applicable or already loaded)";
    }

    if (unloadKeyBtn) {
        let unloadTooltip = "Unload the encryption key (makes data inaccessible)";
        if (isEncrypted && isAvailable && isMounted) {
            unloadTooltip += "\n(Dataset must be unmounted first)";
        } else if (!unloadEnabled && isEncrypted) {
            unloadTooltip = "Key must be loaded (available) to unload.";
        }
        unloadKeyBtn.title = unloadTooltip;
    }

    if (changeKeyBtn) {
        changeKeyBtn.title = changeKeyEnabled ? `Change encryption key/passphrase for ${obj.name}` : "Change Key (Key must be loaded)";
    }

    if (changeLocBtn) {
        changeLocBtn.title = changeLocEnabled ? `Change key location property for ${obj.name}` : "Change Key Location (Not applicable)";
    }
    // --- END MODIFICATION ---

}

function renderPoolEditLayout(statusText) {
    poolEditTreeContainer.innerHTML = ''; // Clear
    if (!statusText || !currentSelection || currentSelection.obj_type !== 'pool') {
        poolEditTreeContainer.innerHTML = '<div class="text-center p-3 text-muted">Pool layout details not available or item is not a pool.</div>';
        updatePoolEditActionStates(null); // Disable buttons
        return;
    }

    // --- START REWRITE: Pool Edit Parsing ---
    const lines = statusText.split('\n');
    const poolName = currentSelection.name;

    // Create root element for the tree structure (using ul/li)
    const rootUl = document.createElement('ul');
    rootUl.className = 'list-unstyled mb-0 pool-edit-tree-root'; // Add class for potential styling

    // Explicitly create the top-level pool item
    const poolLi = document.createElement('li');
    poolLi.dataset.indent = -1; // Special indent for root
    poolLi.dataset.name = poolName;
    poolLi.dataset.itemType = 'pool';
    poolLi.dataset.vdevType = 'pool'; // Consistent type attribute
    // Extract overall pool state and scan info first
    let poolState = 'UNKNOWN';
    let scanInfo = '';
    for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith('state:')) { poolState = trimmed.substring(6).trim(); }
        else if (trimmed.startsWith('scan:')) { scanInfo = trimmed.substring(5).trim(); }
        else if (trimmed.startsWith('config:')) { break; } // Stop before config section
    }
    poolLi.dataset.state = poolState;
    // Set display text and icon
    let poolStateClass = 'text-muted';
    if (poolState === 'ONLINE') poolStateClass = 'text-success';
    else if (poolState === 'DEGRADED') poolStateClass = 'text-warning';
    else if (poolState === 'FAULTED' || poolState === 'UNAVAIL' || poolState === 'REMOVED') poolStateClass = 'text-danger';
    else if (poolState === 'OFFLINE') poolStateClass = 'text-muted fw-light';
    poolLi.innerHTML = `<i class="bi bi-hdd-rack-fill me-1 ${poolStateClass}"></i> ${poolName} <span class="badge bg-light ${poolStateClass} float-end">${poolState}</span>`;
    poolLi.title = `Pool: ${poolName}\nState: ${poolState}\nScan: ${scanInfo}`;
    poolLi.classList.add('pool-edit-item', 'fw-bold'); // Make pool name bold
    poolLi.onclick = (e) => { // Make pool item selectable
        e.stopPropagation();
        poolEditTreeContainer.querySelectorAll('.selected').forEach(el => el.classList.remove('selected'));
        poolLi.classList.add('selected');
        updatePoolEditActionStates(poolLi);
    };
    rootUl.appendChild(poolLi);

    // Regexes adapted from Python version
    const itemRe = /^(\s+)(.+?)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)/; // With state/errors
    const groupRe = /^(\s+)(\S+.*)/; // Without state/errors
    const devicePatternRe = /^(\/dev\/\S+|ata-|wwn-|scsi-|nvme-|usb-|dm-|zd\d+|[a-z]+[0-9]+|gpt\/.*|disk\/by-.*)/i;
    const vdevGroupPatterns = {
        'mirror': /^mirror-\d+/, 'raidz1': /^raidz1-\d+/,
        'raidz2': /^raidz2-\d+/, 'raidz3': /^raidz3-\d+/,
        'draid': /^draid\d*:/, 'log': /^logs$/, // Match 'logs' exactly
        'cache': /^cache$/, 'spare': /^spares$/, 'special': /^special$/
    };

    let inConfigSection = false;
    // Stack of <ul> elements where the next item should be appended
    let parentStack = [poolLi]; // Start with the pool item itself

    // Process config section
    for (const line of lines) {
        const lineStrip = line.trim();
        if (lineStrip.startsWith("config:")) {
            inConfigSection = true;
            continue;
        }
        if (!inConfigSection || !lineStrip) continue;
        if (lineStrip.startsWith("errors:")) break;

        // Parse line data
        let matchItem = itemRe.exec(line);
        let matchGroup = groupRe.exec(line);
        let indent = 0;
        let name = "";
        let state = "N/A";
        let r = 'N/A', w = 'N/A', c = 'N/A'; // Read, Write, Checksum errors

        if (matchItem) {
            let indentStr = matchItem[1];
            name = matchItem[2].trim();
            state = matchItem[3];
            r = matchItem[4]; w = matchItem[5]; c = matchItem[6];
            indent = indentStr.length;
        } else if (matchGroup) {
            let indentStr = matchGroup[1];
            name = matchGroup[2].trim();
            indent = indentStr.length;
            // State remains N/A for groups
        } else {
            console.warn("Pool Edit: Skipping unparseable line:", lineStrip);
            continue;
        }

        // Skip header row and pool name repetition
        if (name === "NAME" && state === "STATE") continue;
        if (name === poolName && parentStack.length === 1 && parentStack[0] === poolLi) continue;

        // Adjust parent stack based on indentation
        // Use > comparison because current indent must be *greater* than parent's indent
        // If <=, pop until we find the correct parent level or reach the pool root.
        while (parentStack.length > 1 && indent <= parseInt(parentStack[parentStack.length - 1].dataset.indent || '0')) {
            parentStack.pop();
        }
        let currentParentLi = parentStack[parentStack.length - 1];
        // Ensure the parent has a UL child to append to, create if necessary
        let currentParentUl = currentParentLi.querySelector(':scope > ul.pool-edit-children');
        if (!currentParentUl) {
            currentParentUl = document.createElement('ul');
            currentParentUl.className = 'list-unstyled mb-0 ps-3 pool-edit-children'; // Add padding
            currentParentLi.appendChild(currentParentUl);
        }


        // Determine item type
        let itemType = 'unknown';
        let vdevType = 'unknown';
        let isVdevGroup = false;
        let isDevice = false;
        let devicePathForRole = null;

        for (const vtype in vdevGroupPatterns) {
            if (vdevGroupPatterns[vtype].test(name)) {
                itemType = 'vdev';
                vdevType = vtype;
                isVdevGroup = true;
                break;
            }
        }

        const parentVdevType = currentParentLi.dataset.vdevType;
        const isUnderKnownVdevGroup = parentVdevType && parentVdevType !== 'unknown' && parentVdevType !== 'pool';

        if (!isVdevGroup && devicePatternRe.test(name)) {
            // It looks like a device path
            if (matchItem || isUnderKnownVdevGroup) { // Only treat as device if it has state OR is under a group
                itemType = 'device';
                isDevice = true;
                devicePathForRole = name;
                if (isUnderKnownVdevGroup) {
                    vdevType = parentVdevType; // Inherit type from parent group
                } else if (currentParentLi === poolLi) {
                    // Device directly under pool -> implies 'disk' vdev concept, but item itself is device
                    vdevType = 'disk';
                }
            } else if (currentParentLi === poolLi && !matchItem){
                // Could be a single disk VDEV (path as name, no state cols)
                itemType = 'vdev';
                vdevType = 'disk';
                devicePathForRole = name; // Use name as path
            }
        } else if (!isVdevGroup && !isDevice && currentParentLi === poolLi) {
            // Item directly under pool, not a known group/device pattern -> assume single disk vdev
            itemType = 'vdev';
            vdevType = 'disk';
            devicePathForRole = name; // Use name as path
        }

        if (itemType === 'unknown') {
            console.warn("Pool Edit: Could not determine item type for:", name, "under", currentParentLi.dataset.name);
        }

        // Create the list item
        const li = document.createElement('li');
        li.classList.add('pool-edit-item');
        li.dataset.indent = indent;
        li.dataset.name = name; // Store original name/path
        li.dataset.itemType = itemType;
        li.dataset.vdevType = vdevType;
        li.dataset.state = state;
        if (devicePathForRole) li.dataset.devicePath = devicePathForRole;

        // Determine icon
        let iconClass = 'bi-question-circle'; // Unknown
        if (itemType === 'pool') iconClass = 'bi-hdd-rack-fill';
        else if (itemType === 'vdev') {
            if (vdevType === 'disk') iconClass = 'bi-hdd';
            else if (['log', 'cache', 'spare', 'special'].includes(vdevType)) iconClass = 'bi-drive-fill'; // Different icon for special VDEVs
            else iconClass = 'bi-hdd-stack'; // Mirror, raidz etc.
        } else if (itemType === 'device') iconClass = 'bi-disc'; // Leaf device

        // Set text and state badge
        let stateHtml = '';
        if (state !== 'N/A' && state !== name) {
            let stateClass = 'text-muted';
            if (state === 'ONLINE') stateClass = 'text-success';
            else if (state === 'DEGRADED') stateClass = 'text-warning';
            else if (state === 'FAULTED' || state === 'UNAVAIL' || state === 'REMOVED') stateClass = 'text-danger';
            else if (state === 'OFFLINE') stateClass = 'text-muted fw-light';
            stateHtml = `<span class="badge bg-light ${stateClass} float-end">${state}</span>`;
        }
        // Display errors if present
        let errorHtml = '';
        if (matchItem && (r !== '0' || w !== '0' || c !== '0')) {
            errorHtml = ` <small class="text-danger">(${r}R ${w}W ${c}C)</small>`;
        }

        li.innerHTML = `<i class="bi ${iconClass} me-1"></i> ${name}${errorHtml}${stateHtml}`;
        li.title = `Type: ${itemType}\nVDEV Type: ${vdevType}\nState: ${state}${devicePathForRole ? '\nPath: '+devicePathForRole : ''}${errorHtml ? `\nErrors: ${r}R ${w}W ${c}C` : ''}`;

        // Add click handler
        li.onclick = (e) => {
            e.stopPropagation();
            poolEditTreeContainer.querySelectorAll('.selected').forEach(el => el.classList.remove('selected'));
            li.classList.add('selected');
            updatePoolEditActionStates(li);
        };

        // Append to the correct parent UL
        currentParentUl.appendChild(li);

        // If it's a VDEV group, push it onto the stack so its children go inside it
        if (itemType === 'vdev' || itemType === 'pool') { // Pool is already on stack
            parentStack.push(li);
        }
    }
    // --- END REWRITE ---

    poolEditTreeContainer.appendChild(rootUl);
    updatePoolEditActionStates(null); // Initial state (no selection)
}

// --- END OF SECTION 5 ---
// --- START OF SECTION 6 ---

function updatePoolEditActionStates(selectedLi) {
    // Reset all buttons first
    const buttonIds = ['attach-device-button', 'detach-device-button', 'replace-device-button',
    'offline-device-button', 'online-device-button', 'remove-pool-vdev-button',
    'split-pool-button']; // Add VDEV handled separately
    buttonIds.forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = true;
    });

        // Add VDEV button is always enabled if a pool is selected
        const addVdevBtn = document.getElementById('add-pool-vdev-button');
        if (addVdevBtn) addVdevBtn.disabled = !currentSelection || currentSelection.obj_type !== 'pool';

        // --- START REWRITE: Button Logic based on new attributes ---
        if (!selectedLi || !currentSelection || currentSelection.obj_type !== 'pool') {
            return; // No selection or not viewing a pool
        }

        const itemType = selectedLi.dataset.itemType;
        const vdevType = selectedLi.dataset.vdevType;
        const state = selectedLi.dataset.state?.toUpperCase();
        const devicePath = selectedLi.dataset.devicePath; // Actual path if device/disk-vdev
        const isDevice = itemType === 'device';
        const isVdev = itemType === 'vdev';
        const isPoolItem = itemType === 'pool';

        // Determine parent item type and vdev type
        const parentLi = selectedLi.parentElement?.closest('li.pool-edit-item');
        const parentItemType = parentLi?.dataset.itemType;
        const parentVdevType = parentLi?.dataset.vdevType;

        // --- Attach Button ---
        // Enabled if selecting a device that is ONLINE and either:
        // 1. Directly under the pool (becomes first disk of new mirror)
        // 2. Under a 'disk' VDEV (becomes first disk of new mirror)
        // 3. Under a non-mirror VDEV group (less common, but possible? Let's allow)
        if (state === 'ONLINE' && devicePath) {
            if (parentItemType === 'pool' || parentVdevType === 'disk' || (parentVdevType && !['mirror', 'log', 'cache', 'spare'].includes(parentVdevType))) {
                document.getElementById('attach-device-button').disabled = false;
            }
        }

        // --- Detach Button ---
        // Enabled if selecting a 'device' that is inside a 'mirror' VDEV,
        // AND the mirror has more than one child device listed.
        if (isDevice && parentVdevType === 'mirror' && parentLi) {
            const siblingDevices = parentLi.querySelectorAll(':scope > ul.pool-edit-children > li[data-item-type="device"]');
            if (siblingDevices.length > 1) {
                document.getElementById('detach-device-button').disabled = false;
            }
        }

        // --- Replace Button ---
        // Enabled if selecting a 'device' OR a 'disk' vdev (which implies a device path).
        if (devicePath && (isDevice || (isVdev && vdevType === 'disk'))) {
            document.getElementById('replace-device-button').disabled = false;
        }

        // --- Offline Button ---
        // Enabled if selecting a 'device' OR 'disk' vdev that is ONLINE.
        if (devicePath && state === 'ONLINE' && (isDevice || (isVdev && vdevType === 'disk'))) {
            document.getElementById('offline-device-button').disabled = false;
        }

        // --- Online Button ---
        // Enabled if selecting a 'device' OR 'disk' vdev that is OFFLINE.
        if (devicePath && state === 'OFFLINE' && (isDevice || (isVdev && vdevType === 'disk'))) {
            document.getElementById('online-device-button').disabled = false;
        }

        // --- Remove VDEV Button ---
        // Enabled if selecting a VDEV that is directly under the pool item.
        if (isVdev && parentItemType === 'pool') {
            // Allow removing log/cache/spare VDEVs anytime
            if (['log', 'cache', 'spare'].includes(vdevType)) {
                document.getElementById('remove-pool-vdev-button').disabled = false;
            } else { // Data VDEV (mirror, raidz, disk)
                // Count sibling DATA vdevs (also direct children of pool)
                let dataVdevCount = 0;
                const poolRootItem = poolEditTreeContainer.querySelector('li[data-item-type="pool"]');
                const topLevelChildrenUl = poolRootItem?.querySelector(':scope > ul.pool-edit-children');
                if(topLevelChildrenUl) {
                    topLevelChildrenUl.querySelectorAll(':scope > li[data-item-type="vdev"]').forEach(siblingLi => {
                        if (!['log', 'cache', 'spare'].includes(siblingLi.dataset.vdevType)) {
                            dataVdevCount++;
                        }
                    });
                }
                // Allow removal only if there's more than one data vdev
                if (dataVdevCount > 1) {
                    document.getElementById('remove-pool-vdev-button').disabled = false;
                }
            }
        }

        // --- Split Pool Button ---
        // Enabled ONLY if the POOL item itself is selected AND it looks fully mirrored.
        if (isPoolItem) {
            let isFullyMirrored = true;
            let hasDataVdev = false;
            const poolRootItem = selectedLi; // Since we checked isPoolItem
            const topLevelChildrenUl = poolRootItem.querySelector(':scope > ul.pool-edit-children');
            if(topLevelChildrenUl) {
                const topLevelVdevs = topLevelChildrenUl.querySelectorAll(':scope > li[data-item-type="vdev"]');
                if(topLevelVdevs.length === 0) { // No vdevs under pool?
                    isFullyMirrored = false;
                }
                topLevelVdevs.forEach(topVdevLi => {
                    const topVdevType = topVdevLi.dataset.vdevType;
                    if (!['log', 'cache', 'spare'].includes(topVdevType)) {
                        hasDataVdev = true;
                        // Count devices within this top-level VDEV
                        const devicesInVdev = topVdevLi.querySelectorAll(':scope > ul.pool-edit-children > li[data-item-type="device"]').length;
                        // Basic split requires mirror with >= 2 devices
                        if (topVdevType !== 'mirror' || devicesInVdev < 2) {
                            isFullyMirrored = false;
                            // NOTE: Could break loop here if strict
                        }
                    }
                });
            } else { // Pool has no children UL?
                isFullyMirrored = false;
            }

            if (hasDataVdev && isFullyMirrored) {
                document.getElementById('split-pool-button').disabled = false;
            }
        }
        // --- END REWRITE ---
}

// --- END OF SECTION 6 ---
// --- START OF SECTION 7 ---

// --- Property Editing ---
// Define editable properties for the web UI (similar to PySide6 version)
window.EDITABLE_PROPERTIES_WEB = {
    'mountpoint': { internalName: 'mountpoint', displayName: 'Mount Point', editor: 'lineedit' },
    'quota': { internalName: 'quota', displayName: 'Quota', editor: 'lineedit', placeholder: 'e.g., 100G, none', validation: 'sizeOrNone' },
    'reservation': { internalName: 'reservation', displayName: 'Reservation', editor: 'lineedit', placeholder: 'e.g., 5G, none', validation: 'sizeOrNone' },
    'recordsize': { internalName: 'recordsize', displayName: 'Record Size', editor: 'combobox', options: ['inherit', '512', ...Array.from({length: 11-7+1}, (_, i) => `${2**(i+7)}K`), '1M'] },
    'compression': { internalName: 'compression', displayName: 'Compression', editor: 'combobox', options: ['inherit', 'off', 'on', 'lz4', 'gzip', 'gzip-1', 'gzip-9', 'zle', 'lzjb', 'zstd', 'zstd-fast'] },
    'atime': { internalName: 'atime', displayName: 'Access Time (atime)', editor: 'combobox', options: ['inherit', 'on', 'off'] },
    'relatime': { internalName: 'relatime', displayName: 'Relative Access Time', editor: 'combobox', options: ['inherit', 'on', 'off'] },
    'readonly': { internalName: 'readonly', displayName: 'Read Only', editor: 'combobox', options: ['inherit', 'on', 'off'] },
    'dedup': { internalName: 'dedup', displayName: 'Deduplication', editor: 'combobox', options: ['inherit', 'on', 'off', 'verify', 'sha256', 'sha512', 'skein', 'edonr'], readOnlyFunc: (obj) => obj?.obj_type === 'snapshot' },
    'sharenfs': { internalName: 'sharenfs', displayName: 'NFS Share', editor: 'combobox', options: ['inherit', 'off', 'on'], readOnlyFunc: (obj) => obj?.obj_type === 'snapshot' },
    'sharesmb': { internalName: 'sharesmb', displayName: 'SMB Share', editor: 'combobox', options: ['inherit', 'off', 'on'], readOnlyFunc: (obj) => obj?.obj_type === 'snapshot' },
    'logbias': { internalName: 'logbias', displayName: 'Log Bias', editor: 'combobox', options: ['inherit', 'latency', 'throughput'], readOnlyFunc: (obj) => obj?.obj_type === 'snapshot' },
    'sync': { internalName: 'sync', displayName: 'Sync Policy', editor: 'combobox', options: ['inherit', 'standard', 'always', 'disabled'], readOnlyFunc: (obj) => obj?.obj_type === 'snapshot' },
    'volblocksize': { internalName: 'volblocksize', displayName: 'Volume Block Size', editor: 'combobox', options: ['inherit'] + Array.from({length: 17-9+1}, (_, i) => `${2**(i+9)}K`) + ['1M'], readOnlyFunc: (obj) => !(obj?.obj_type === 'volume') },
    'comment': { internalName: 'comment', displayName: 'Pool Comment', editor: 'lineedit', readOnlyFunc: (obj) => obj?.obj_type !== 'pool' },
    'cachefile': { internalName: 'cachefile', displayName: 'Cache File', editor: 'lineedit', readOnlyFunc: (obj) => obj?.obj_type !== 'pool' },
    'bootfs': { internalName: 'bootfs', displayName: 'Boot FS', editor: 'lineedit', readOnlyFunc: (obj) => obj?.obj_type !== 'pool' },
    'failmode': { internalName: 'failmode', displayName: 'Fail Mode', editor: 'combobox', options: ['wait', 'continue', 'panic'], readOnlyFunc: (obj) => obj?.obj_type !== 'pool' },
    'autotrim': { internalName: 'autotrim', displayName: 'Auto Trim', editor: 'combobox', options: ['on', 'off'], readOnlyFunc: (obj) => obj?.obj_type !== 'pool' },
    'autoreplace': { internalName: 'autoreplace', displayName: 'Auto Replace', editor: 'combobox', options: ['on', 'off'], readOnlyFunc: (obj) => obj?.obj_type !== 'pool' },
};

// Define which properties use zpool set/inherit (pool-level only)
const POOL_LEVEL_PROPERTIES = new Set([
    'comment', 'cachefile', 'bootfs', 'failmode', 'autoreplace', 'autotrim',
    'delegation', 'autoexpand', 'listsnapshots', 'readonly', 'multihost', 
    'compatibility'
]);

// --- Define AUTO_SNAPSHOT_PROPS here, right before use ---
const AUTO_SNAPSHOT_PROPS = [
    "com.sun:auto-snapshot",
    "com.sun:auto-snapshot:daily",
    "com.sun:auto-snapshot:frequent",
    "com.sun:auto-snapshot:hourly",
    "com.sun:auto-snapshot:monthly",
    "com.sun:auto-snapshot:weekly",
    "com.sun:auto-snapshot:yearly",
];

// --- Define Auto Snapshot Sort Order for WebUI ---
const AUTO_SNAPSHOT_SORT_ORDER_WEB = [
    "com.sun:auto-snapshot", // Master switch first
    "com.sun:auto-snapshot:frequent",
    "com.sun:auto-snapshot:hourly",
    "com.sun:auto-snapshot:daily",
    "com.sun:auto-snapshot:weekly",
    "com.sun:auto-snapshot:monthly",
    "com.sun:auto-snapshot:yearly",
];

// --- Add Auto Snapshot Properties to Web Editable List ---
AUTO_SNAPSHOT_PROPS.forEach(prop => {
    const suffix = prop.includes(':') ? prop.split(':').pop() : 'Default';
    // --- Make Master Switch Name More Obvious ---
    const is_master_switch = (prop === "com.sun:auto-snapshot");
    const displayName = is_master_switch ? "Auto Snapshot (Master Switch)" : `Auto Snapshot (${suffix.charAt(0).toUpperCase() + suffix.slice(1)})`;
    // --- End Master Switch Name Change ---
    window.EDITABLE_PROPERTIES_WEB[prop] = {
        internalName: prop,
        displayName: displayName,
        editor: 'combobox', // Use combobox for the dropdown
        options: ['true', 'false', '-'], // Values for the dropdown
        readOnlyFunc: (obj) => !(obj?.obj_type === 'dataset' || obj?.obj_type === 'volume') // Editable on datasets/volumes only
    };
});

function validateSizeOrNone(value) {
    if (value.toLowerCase() === 'none') return true;
    // Basic check: starts with digit, optional unit K, M, G, T, P etc.
    return /^\d+(\.\d+)?\s*[KMGTPEZY]?B?$/i.test(value);
}

function handleEditProperty(propName, currentValue, editInfo) {
    if (!currentSelection) return;

    let inputHtml = '';
    if (editInfo.editor === 'lineedit') {
        inputHtml = `<input type="text" id="prop-edit-input" class="form-control" value="${currentValue}" placeholder="${editInfo.placeholder || ''}">`;
    } else if (editInfo.editor === 'combobox' && editInfo.options) {
        // *** ADD CHECK: Ensure options is actually an array ***
        if (!Array.isArray(editInfo.options)) {
            console.error(`Configuration error: options for property '${propName}' is not an array.`, editInfo.options);
            showErrorAlert("Internal Error", `Cannot create editor for '${propName}' due to invalid configuration.`);
            return;
        }
        // *** END CHECK ***
        
        inputHtml = `<select id="prop-edit-input" class="form-select">`;
        editInfo.options.forEach(opt => { // Now safe to call forEach
            inputHtml += `<option value="${opt}" ${opt === currentValue ? 'selected' : ''}>${opt}</option>`;
        });
        inputHtml += `</select>`;
    } else {
        showErrorAlert("Edit Error", `Unsupported editor type for property '${propName}'.`);
        return;
    }

    showModal(`Edit Property: ${editInfo.displayName}`,
              `<p>Set '${editInfo.displayName}' for '${currentSelection.name}':</p>${inputHtml}`,
              () => { // onConfirm
                  const inputElement = document.getElementById('prop-edit-input');
                  const newValue = inputElement.value.trim();

                  // --- Handle inherit for properties with '-' option ---
                  if (editInfo.editor === 'combobox' && newValue === '-') {
                        // If '-' is selected, trigger inherit instead of set
                        actionModal.hide(); // Hide current modal
                        // Use a slight delay to ensure modal is hidden before potential confirmation dialog from inherit
                        setTimeout(() => handleInheritProperty(propName), 100); 
                        return; // Stop further processing in this handler
                  }
                  // --- END MODIFICATION ---

                  if (newValue === currentValue) {
                      updateStatus('Value not changed.', 'info');
                      actionModal.hide(); // Close modal even if no change
                      return; // No change
                  }

                  // Validation
                  if (editInfo.validation === 'sizeOrNone' && !validateSizeOrNone(newValue)) {
                      alert(`Invalid format for ${editInfo.displayName}. Use numbers, units (K, M, G, T...) or 'none'.`);
                      inputElement.focus(); // Keep focus
                      return; // Keep modal open
                  }

                  // Execute action
                  actionModal.hide(); // Hide modal before executing
                  
                  // Route to pool command only if it's a pool AND a pool-level property
                  const isPoolProperty = currentSelection.obj_type === 'pool' && POOL_LEVEL_PROPERTIES.has(propName);
                  const setAction = isPoolProperty ? 'set_pool_property' : 'set_dataset_property';
                  
                  executeAction(
                      setAction,
                      [currentSelection.name, propName, newValue],
                      {},
                      `Property '${propName}' set successfully.`
                  );
              }
    );
}

function handleInheritProperty(propName) {
    if (!currentSelection) return;
    
    // Pool properties cannot be inherited (zpool has no inherit command)
    const isPoolProperty = currentSelection.obj_type === 'pool' && POOL_LEVEL_PROPERTIES.has(propName);
    if (isPoolProperty) {
        showErrorAlert("Cannot Inherit", `Pool property '${propName}' cannot be inherited. Pool properties can only be set to specific values.`);
        return;
    }
    
    executeAction(
        'inherit_dataset_property',
        [currentSelection.name, propName],
        {},
        `Property '${propName}' set to inherit.`,
        true, // Require confirmation
        `Are you sure you want to reset property '${propName}' for '${currentSelection.name}' to its inherited value?`
    );
}

// --- Other Actions ---
function handleCreatePool() {
    let availableDevicesHtml = '<p class="text-muted">Loading available devices...</p>';
    let modalHtml = `
    <div class="mb-3">
    <label for="pool-name-input" class="form-label">Pool Name:</label>
    <input type="text" class="form-control" id="pool-name-input" placeholder="e.g., tank, mypool" required>
    <div class="invalid-feedback">Pool name is required and cannot contain spaces or '/'.</div>
    </div>
    <div class="form-check mb-3">
    <input class="form-check-input" type="checkbox" value="" id="pool-force-create-check">
    <label class="form-check-label" for="pool-force-create-check">
    Force Creation (-f) <small class="text-muted">(Use with caution)</small>
    </label>
    </div>
    <hr>
    <h6>Pool Layout</h6>
    <div class="row">
    <div class="col-md-5">
    <label class="form-label">Available Devices:</label>
    <ul id="pool-available-devices" class="list-group list-group-flush border rounded" style="max-height: 200px; overflow-y: auto;">${availableDevicesHtml}</ul>
    </div>
    <div class="col-md-1 d-flex flex-column align-items-center justify-content-center">
    <button type="button" id="pool-add-device-btn" class="btn btn-sm btn-outline-primary mb-2" title="Add Selected Device(s) to VDEV">>></button>
    <button type="button" id="pool-remove-device-btn" class="btn btn-sm btn-outline-danger mt-2" title="Remove Selected Device/VDEV"><<</button> <!-- Changed title -->
    </div>
    <div class="col-md-6">
    <label class="form-label">VDEVs in Pool:</label>
    <div id="pool-vdev-config" class="border rounded p-1 bg-light" style="min-height: 150px;">
    <ul class="list-unstyled mb-0" id="pool-vdev-list"></ul>
    </div>
    <div class="text-end mt-1">
    <button type="button" id="pool-add-vdev-btn" class="btn btn-sm btn-success"><i class="bi bi-plus-circle"></i> Add VDEV Type</button>
    </div>
    </div>
    </div>
    `;

    showModal('Create New Pool', modalHtml, handleCreatePoolConfirm, { size: 'xl', setupFunc: setupCreatePoolModal });
}

function setupCreatePoolModal() {
    const availableList = document.getElementById('pool-available-devices');
    const vdevList = document.getElementById('pool-vdev-list');
    // --- START FIX #1 (accessible map) ---
    // Use a property on the modal body itself to store the map, avoiding global window pollution
    const modalBody = document.getElementById('actionModalBody');
    if (!modalBody) {
        console.error("Modal body not found for map storage!");
        return; // Cannot proceed
    }
    modalBody.modalAvailableDevicesMap = {};
    const availableDevicesMap = modalBody.modalAvailableDevicesMap; // Local reference
    // --- END FIX #1 ---

    // Add event listeners for buttons inside the modal
    document.getElementById('pool-add-vdev-btn')?.addEventListener('click', () => addVdevTypeToPoolConfig(vdevList));
    document.getElementById('pool-add-device-btn')?.addEventListener('click', () => addDeviceToPoolVdev(availableList, vdevList, availableDevicesMap)); // Use map
    document.getElementById('pool-remove-device-btn')?.addEventListener('click', () => {
        const selectedVdev = getSelectedPoolVdev(vdevList);
        const selectedDevice = getSelectedPoolDeviceInVdev(vdevList);

        if (selectedDevice) {
            removeDeviceFromPoolVdev(availableList, vdevList, availableDevicesMap); // Use map
        } else if (selectedVdev) {
            removeVdevFromPoolConfig(selectedVdev, availableList, availableDevicesMap); // Use map
        } else {
            alert("Please select a VDEV or a device within a VDEV to remove.");
        }
    });

    // Fetch and populate available devices
    apiCall('/api/block_devices')
    .then(result => {
        availableList.innerHTML = ''; // Clear loading
        if (!result.data || result.data.length === 0) {
            availableList.innerHTML = '<li class="list-group-item text-muted">No suitable devices found.</li>';
            return;
        }
        result.data.forEach(dev => {
            availableDevicesMap[dev.name] = dev; // Populate map
            const li = document.createElement('li');
            // --- START FIX #3: Add specific class ---
            li.className = 'list-group-item list-group-item-action py-1 pool-device-item';
            // --- END FIX #3 ---
            li.textContent = dev.display_name || dev.name;
            li.dataset.path = dev.name;
            // --- START FIX #3: Add click handler for selection ---
            li.onclick = (e) => {
                // Simple toggle selection on click
                e.currentTarget.classList.toggle('active');
            };
            // --- END FIX #3 ---
            availableList.appendChild(li);
        });
        const items = Array.from(availableList.children);
        items.sort((a, b) => a.textContent.localeCompare(b.textContent));
        availableList.innerHTML = '';
        items.forEach(item => availableList.appendChild(item));
    })
    .catch(error => {
        availableList.innerHTML = `<li class="list-group-item text-danger">Error loading devices: ${error.message}</li>`;
    });
}
// --- END OF SECTION 7 ---
// --- START OF SECTION 8 ---
function addVdevTypeToPoolConfig(vdevList) {
    const vdevTypes = ['disk', 'mirror', 'raidz1', 'raidz2', 'raidz3', 'log', 'cache', 'spare'];
    const vdevType = prompt(`Select VDEV Type:\n(${vdevTypes.join(', ')})`, 'disk');
    if (vdevType && vdevTypes.includes(vdevType.toLowerCase())) {
        const type = vdevType.toLowerCase();
        const vdevId = `vdev-${type}-${Date.now()}`; // Unique ID for the element
        const li = document.createElement('li');
        // --- START FIX #3: Add specific class ---
        li.className = 'list-group-item py-1 pool-vdev-item mb-1';
        // --- END FIX #3 ---
        li.dataset.vdevType = type;
        li.dataset.vdevId = vdevId;
        li.innerHTML = `
        <div class="d-flex justify-content-between align-items-center">
        <span><strong>${type.toUpperCase()}</strong> VDEV</span>
        <button type="button" class="btn btn-sm btn-outline-danger py-0 px-1 remove-vdev-btn" title="Remove this VDEV">
            <i class="bi bi-trash3-fill"></i> <!-- Use trash icon -->
        </button>
        </div>
        <ul class="list-unstyled ps-3 mb-0 device-list-in-vdev"></ul>`;
        // --- START FIX #3: Add click handler for selection ---
        li.onclick = (e) => {
            // Select the VDEV item itself when clicking the header area, not the remove button
            if(e.target.classList.contains('pool-vdev-item') || e.target.closest('.d-flex')) {
                vdevList.querySelectorAll('.pool-vdev-item.active, .pool-vdev-device-item.active').forEach(el => el.classList.remove('active'));
                li.classList.add('active');
            }
        };
        // --- END FIX #3 ---
        // --- START FIX #1: Connect remove button ---
        li.querySelector('.remove-vdev-btn').onclick = (e) => {
            e.stopPropagation(); // Prevent selecting the VDEV when clicking remove
            const availableListEl = document.getElementById('pool-available-devices');
            // --- START FIX #1: Access map via modal body ---
            const modalBody = document.getElementById('actionModalBody');
            const map = modalBody?.modalAvailableDevicesMap || {}; // Use map stored on modal body
            // --- END FIX #1 ---
            removeVdevFromPoolConfig(li, availableListEl, map); // Pass the VDEV <li> itself and map
        };
        // --- END FIX #1 ---
        vdevList.appendChild(li);
    } else if(vdevType !== null) { // Avoid alert if user cancelled
        alert("Invalid VDEV type selected.");
    }
}

function getSelectedPoolVdev(vdevList) {
    return vdevList.querySelector('.pool-vdev-item.active');
}
function getSelectedPoolDeviceInVdev(vdevList) {
    return vdevList.querySelector('.pool-vdev-device-item.active');
}

function addDeviceToPoolVdev(availableList, vdevList, availableDevicesMap) {
    const selectedVdevLi = getSelectedPoolVdev(vdevList);
    if (!selectedVdevLi) {
        alert("Please select a VDEV in the pool layout first.");
        return;
    }
    const selectedAvailableItems = availableList.querySelectorAll('.pool-device-item.active');
    if (selectedAvailableItems.length === 0) {
        alert("Please select one or more available devices to add.");
        return;
    }

    const deviceListInVdev = selectedVdevLi.querySelector('.device-list-in-vdev');
    selectedAvailableItems.forEach(availItem => {
        const path = availItem.dataset.path;
        const devInfo = availableDevicesMap[path];
        const display = devInfo?.display_name || path;

        // Check if already added to *this* vdev
        if (deviceListInVdev.querySelector(`li[data-path="${CSS.escape(path)}"]`)) { // Use CSS.escape
            console.log(`Device ${path} already in this VDEV.`);
            return; // Skip if already present
        }

        const deviceLi = document.createElement('li');
        // --- START FIX #3: Add specific class ---
        deviceLi.className = 'list-group-item list-group-item-action py-1 pool-vdev-device-item';
        // --- END FIX #3 ---
        deviceLi.textContent = display;
        deviceLi.dataset.path = path;
        // --- START FIX #3: Add click handler for selection ---
        deviceLi.onclick = (e) => {
            e.stopPropagation(); // Prevent selecting the parent VDEV
            vdevList.querySelectorAll('.pool-vdev-item.active, .pool-vdev-device-item.active').forEach(el => el.classList.remove('active'));
            deviceLi.classList.add('active');
        };
        // --- END FIX #3 ---
        deviceListInVdev.appendChild(deviceLi);
        availItem.remove(); // Remove from available list
    });
}

function removeDeviceFromPoolVdev(availableList, vdevList, availableDevicesMap) {
    const selectedDeviceLi = getSelectedPoolDeviceInVdev(vdevList);
    if (!selectedDeviceLi) {
        // This might be called by the VDEV remove 'x' button, check if a VDEV is selected instead
        const selectedVdevLi = getSelectedPoolVdev(vdevList);
        if (selectedVdevLi) {
            console.log("Calling removeVdevFromPoolConfig because VDEV was selected for removal via '<' button.");
            removeVdevFromPoolConfig(selectedVdevLi, availableList, availableDevicesMap);
        } else {
            alert("Please select a device within a VDEV in the pool layout to remove.");
        }
        return;
    }

    const path = selectedDeviceLi.dataset.path;
    selectedDeviceLi.remove(); // Remove from VDEV list

    // Add back to available list
    const devInfo = availableDevicesMap ? availableDevicesMap[path] : { name: path }; // Defensive check for map
    const display = devInfo?.display_name || path;
    const availLi = document.createElement('li');
    availLi.className = 'list-group-item list-group-item-action py-1 pool-device-item';
    availLi.textContent = display;
    availLi.dataset.path = path;
    availLi.onclick = (e) => e.currentTarget.classList.toggle('active');
    availableList.appendChild(availLi);
    // Re-sort available list (simple alpha sort)
    const items = Array.from(availableList.children);
    items.sort((a, b) => a.textContent.localeCompare(b.textContent));
    availableList.innerHTML = ''; // Clear
    items.forEach(item => availableList.appendChild(item));
}

function removeVdevFromPoolConfig(vdevLiToRemove, availableList, availableDevicesMap) { // Added availableDevicesMap
    // Return all devices within this VDEV to the available list first
    const devicesInVdev = vdevLiToRemove.querySelectorAll('.pool-vdev-device-item');
    devicesInVdev.forEach(deviceLi => {
        const path = deviceLi.dataset.path;
        // --- START FIX #1: Check if map exists ---
        const devInfo = availableDevicesMap ? availableDevicesMap[path] : { name: path }; // Fallback if map missing
        // --- END FIX #1 ---
        const display = devInfo?.display_name || path;
        const availLi = document.createElement('li');
        availLi.className = 'list-group-item list-group-item-action py-1 pool-device-item';
        availLi.textContent = display;
        availLi.dataset.path = path;
        availLi.onclick = (e) => e.currentTarget.classList.toggle('active');
        availableList.appendChild(availLi);
    });
    // Re-sort available list
    const items = Array.from(availableList.children);
    items.sort((a, b) => a.textContent.localeCompare(b.textContent));
    availableList.innerHTML = ''; // Clear
    items.forEach(item => availableList.appendChild(item));

    // Remove the VDEV list item itself
    vdevLiToRemove.remove();
}

// --- END OF SECTION 8 ---
// --- START OF SECTION 9 ---

// --- START MOVED/FIXED FUNCTIONS for Create Dataset & Add Vdev ---

// --- Function Definition for Create Dataset Setup ---
function setupCreateDatasetModal() {
    // Show/hide volume size
    const typeSelect = document.getElementById('create-ds-type');
    const volSizeGroup = document.getElementById('create-ds-volsize-group');
    typeSelect.onchange = () => {
        volSizeGroup.style.display = typeSelect.value === 'volume' ? 'block' : 'none';
    };

    // Show/hide encryption options
    const encEnableCheck = document.getElementById('create-ds-enc-enable');
    const encOptionsDiv = document.getElementById('create-ds-enc-options');
    const encFormatSelect = document.getElementById('create-ds-enc-format');
    const passphraseGroup = document.getElementById('create-ds-enc-passphrase-group');
    const keylocGroup = document.getElementById('create-ds-enc-keyloc-group');

    encEnableCheck.onchange = () => {
        encOptionsDiv.style.display = encEnableCheck.checked ? 'block' : 'none';
        if (encEnableCheck.checked) {
            // Trigger change event to set initial visibility of sub-options
            const event = new Event('change');
            encFormatSelect.dispatchEvent(event);
        }
    };
    encFormatSelect.onchange = () => {
        const isPass = encFormatSelect.value === 'passphrase';
        passphraseGroup.style.display = isPass ? 'flex' : 'none'; // Use flex for row layout
        keylocGroup.style.display = isPass ? 'none' : 'flex';
    };
    // Initial state setup for encryption options when modal loads
    encOptionsDiv.style.display = encEnableCheck.checked ? 'block' : 'none';
    const isPassInitial = encFormatSelect.value === 'passphrase';
    passphraseGroup.style.display = (encEnableCheck.checked && isPassInitial) ? 'flex' : 'none';
    keylocGroup.style.display = (encEnableCheck.checked && !isPassInitial) ? 'flex' : 'none';
}

// --- Function Definition for Create Dataset Confirmation ---
function handleCreateDatasetConfirm() {
    const parentName = document.getElementById('create-ds-parent').value;
    const namePart = document.getElementById('create-ds-name').value.trim();
    const dsType = document.getElementById('create-ds-type').value;
    const isVolume = dsType === 'volume';
    const volSize = document.getElementById('create-ds-volsize').value.trim();

    if (!namePart || namePart.includes(' ') || namePart.includes('/') || namePart.includes('@')) {
        alert("Invalid dataset/volume name part."); return;
    }
    if (!/^[a-zA-Z0-9]/.test(namePart)) { alert("Name part must start with letter/number."); return; }
    if (/[^a-zA-Z0-9_\-:.%]/.test(namePart)) { alert("Name part contains invalid characters."); return; }


    if (isVolume && !volSize) {
        alert("Volume Size is required for volumes."); return;
    }
    if (isVolume && !validateSizeOrNone(volSize)) {
        alert("Invalid volume size format."); return;
    }


    const fullDsName = `${parentName}/${namePart}`;
    const options = {};
    let encPassphrase = null; // Initialize here

    // Collect optional props
    const mountpoint = document.getElementById('create-ds-mountpoint').value.trim();
    if (mountpoint && mountpoint.toLowerCase() !== 'inherit') options.mountpoint = mountpoint;
    const quota = document.getElementById('create-ds-quota').value.trim();
    if (quota && quota.toLowerCase() !== 'none') {
        if (!validateSizeOrNone(quota)) { alert("Invalid Quota format."); return; }
        options.quota = quota;
    }
    const compression = document.getElementById('create-ds-compression').value;
    if (compression !== 'inherit') options.compression = compression;
    // Add other properties...

    // Collect encryption options
    if (document.getElementById('create-ds-enc-enable').checked) {
        options.encryption = document.getElementById('create-ds-enc-alg').value;
        options.keyformat = document.getElementById('create-ds-enc-format').value;
        if (options.keyformat === 'passphrase') {
            const pass1 = document.getElementById('create-ds-enc-pass').value;
            const pass2 = document.getElementById('create-ds-enc-confirm').value;
            if (!pass1) { alert("Passphrase cannot be empty when encryption is enabled."); return; }
            if (pass1 !== pass2) { alert("Passphrases do not match."); return; }
            encPassphrase = pass1;
        } else {
            const keyloc = document.getElementById('create-ds-enc-keyloc').value.trim();
            if (!keyloc || !keyloc.startsWith('file:///')) { alert("Key Location (file URI) is required for hex/raw format."); return; }
                options.keylocation = keyloc;
        }
    }

    actionModal.hide();
    executeAction(
        'create_dataset', [],
        {
            full_dataset_name: fullDsName, is_volume: isVolume,
            volsize: isVolume ? volSize : null, options: options,
            passphrase: encPassphrase
        },
        `${isVolume ? 'Volume' : 'Dataset'} '${fullDsName}' creation initiated.`
    );
}

// --- Function Definition for Add Vdev Dialog Trigger ---
function handleAddVdevDialog() {
    if (!currentSelection || currentSelection.obj_type !== 'pool') return;
    const poolName = currentSelection.name;

    let availableDevicesHtml = '<p class="text-muted">Loading available devices...</p>';
    let modalHtml = `
    <h6>Add VDEVs to Pool '${poolName}'</h6>
    <div class="form-check mb-3">
    <input class="form-check-input" type="checkbox" value="" id="pool-force-add-check">
    <label class="form-check-label" for="pool-force-add-check">Force Addition (-f)</label>
    </div> <hr>
    <div class="row"> <div class="col-md-5">
    <label class="form-label">Available Devices:</label>
    <ul id="pool-available-devices" class="list-group list-group-flush border rounded" style="max-height: 200px; overflow-y: auto;">${availableDevicesHtml}</ul>
    </div> <div class="col-md-1 d-flex flex-column align-items-center justify-content-center">
    <button type="button" id="pool-add-device-btn" class="btn btn-sm btn-outline-primary mb-2" title="Add Selected Device(s) to VDEV">>></button>
    <button type="button" id="pool-remove-device-btn" class="btn btn-sm btn-outline-danger mt-2" title="Remove Selected Device/VDEV"><<</button>
    </div> <div class="col-md-6">
    <label class="form-label">VDEVs to Add:</label>
    <div id="pool-vdev-config" class="border rounded p-1 bg-light" style="min-height: 150px;">
    <ul class="list-unstyled mb-0" id="pool-vdev-list"></ul></div>
    <div class="text-end mt-1">
    <button type="button" id="pool-add-vdev-btn" class="btn btn-sm btn-success"><i class="bi bi-plus-circle"></i> Add VDEV Type</button>
    </div> </div> </div>`;

    showModal(`Add VDEVs to Pool '${poolName}'`, modalHtml, handleAddVdevConfirm, { size: 'xl', setupFunc: setupCreatePoolModal });
}

// --- Function Definition for Add Vdev Confirmation ---
function handleAddVdevConfirm() {
    if (!currentSelection || currentSelection.obj_type !== 'pool') {
        console.error("handleAddVdevConfirm called without a pool selected."); return;
    }
    const poolName = currentSelection.name;
    const forceAdd = document.getElementById('pool-force-add-check').checked;

    const vdevSpecs = [];
    const vdevItems = document.querySelectorAll('#pool-vdev-list > .pool-vdev-item');
    if (vdevItems.length === 0) { alert("No VDEVs defined to add."); return; }

    let layoutValid = true;
    vdevItems.forEach(vdevLi => {
        const vdevType = vdevLi.dataset.vdevType;
        const devices = [];
        vdevLi.querySelectorAll('.pool-vdev-device-item').forEach(devLi => { devices.push(devLi.dataset.path); });
        const minDevices = { 'mirror': 2, 'raidz1': 3, 'raidz2': 4, 'raidz3': 5 }[vdevType] || 1;
        if (devices.length < minDevices) {
            alert(`VDEV type '${vdevType}' requires ${minDevices} device(s), found ${devices.length}.`);
            layoutValid = false; return;
        }
        vdevSpecs.push({ type: vdevType, devices: devices });
    });

    if (!layoutValid) return;

    actionModal.hide();
    executeAction(
        'add_vdev', [], { pool_name: poolName, vdev_specs: vdevSpecs, force: forceAdd },
        `Adding VDEVs to pool '${poolName}' initiated.`
    );
}

// --- END MOVED/FIXED FUNCTIONS ---


// --- START OF SECTION 9 ---

// --- START MOVED/FIXED FUNCTIONS for Create Dataset & Add Vdev ---

// --- Function Definition for Create Dataset Setup ---
function setupCreateDatasetModal() {
    // Show/hide volume size
    const typeSelect = document.getElementById('create-ds-type');
    const volSizeGroup = document.getElementById('create-ds-volsize-group');
    typeSelect.onchange = () => {
        volSizeGroup.style.display = typeSelect.value === 'volume' ? 'block' : 'none';
    };

    // Show/hide encryption options
    const encEnableCheck = document.getElementById('create-ds-enc-enable');
    const encOptionsDiv = document.getElementById('create-ds-enc-options');
    const encFormatSelect = document.getElementById('create-ds-enc-format');
    const passphraseGroup = document.getElementById('create-ds-enc-passphrase-group');
    const keylocGroup = document.getElementById('create-ds-enc-keyloc-group');

    encEnableCheck.onchange = () => {
        encOptionsDiv.style.display = encEnableCheck.checked ? 'block' : 'none';
        if (encEnableCheck.checked) {
            // Trigger change event to set initial visibility of sub-options
            const event = new Event('change');
            encFormatSelect.dispatchEvent(event);
        }
    };
    encFormatSelect.onchange = () => {
        const isPass = encFormatSelect.value === 'passphrase';
        passphraseGroup.style.display = isPass ? 'flex' : 'none'; // Use flex for row layout
        keylocGroup.style.display = isPass ? 'none' : 'flex';
    };
    // Initial state setup for encryption options when modal loads
    encOptionsDiv.style.display = encEnableCheck.checked ? 'block' : 'none';
    const isPassInitial = encFormatSelect.value === 'passphrase';
    passphraseGroup.style.display = (encEnableCheck.checked && isPassInitial) ? 'flex' : 'none';
    keylocGroup.style.display = (encEnableCheck.checked && !isPassInitial) ? 'flex' : 'none';
}

// --- Function Definition for Create Dataset Confirmation ---
function handleCreateDatasetConfirm() {
    const parentName = document.getElementById('create-ds-parent').value;
    const namePart = document.getElementById('create-ds-name').value.trim();
    const dsType = document.getElementById('create-ds-type').value;
    const isVolume = dsType === 'volume';
    const volSize = document.getElementById('create-ds-volsize').value.trim();

    if (!namePart || namePart.includes(' ') || namePart.includes('/') || namePart.includes('@')) {
        alert("Invalid dataset/volume name part."); return;
    }
    if (!/^[a-zA-Z0-9]/.test(namePart)) { alert("Name part must start with letter/number."); return; }
    if (/[^a-zA-Z0-9_\-:.%]/.test(namePart)) { alert("Name part contains invalid characters."); return; }


    if (isVolume && !volSize) {
        alert("Volume Size is required for volumes."); return;
    }
    if (isVolume && !validateSizeOrNone(volSize)) {
        alert("Invalid volume size format."); return;
    }


    const fullDsName = `${parentName}/${namePart}`;
    const options = {};
    let encPassphrase = null; // Initialize here

    // Collect optional props
    const mountpoint = document.getElementById('create-ds-mountpoint').value.trim();
    if (mountpoint && mountpoint.toLowerCase() !== 'inherit') options.mountpoint = mountpoint;
    const quota = document.getElementById('create-ds-quota').value.trim();
    if (quota && quota.toLowerCase() !== 'none') {
        if (!validateSizeOrNone(quota)) { alert("Invalid Quota format."); return; }
        options.quota = quota;
    }
    const compression = document.getElementById('create-ds-compression').value;
    if (compression !== 'inherit') options.compression = compression;
    // Add other properties...

    // Collect encryption options
    if (document.getElementById('create-ds-enc-enable').checked) {
        options.encryption = document.getElementById('create-ds-enc-alg').value;
        options.keyformat = document.getElementById('create-ds-enc-format').value;
        if (options.keyformat === 'passphrase') {
            const pass1 = document.getElementById('create-ds-enc-pass').value;
            const pass2 = document.getElementById('create-ds-enc-confirm').value;
            if (!pass1) { alert("Passphrase cannot be empty when encryption is enabled."); return; }
            if (pass1 !== pass2) { alert("Passphrases do not match."); return; }
            encPassphrase = pass1;
        } else {
            const keyloc = document.getElementById('create-ds-enc-keyloc').value.trim();
            if (!keyloc || !keyloc.startsWith('file:///')) { alert("Key Location (file URI) is required for hex/raw format."); return; }
                options.keylocation = keyloc;
        }
    }

    actionModal.hide();
    executeAction(
        'create_dataset', [],
        {
            full_dataset_name: fullDsName, is_volume: isVolume,
            volsize: isVolume ? volSize : null, options: options,
            passphrase: encPassphrase
        },
        `${isVolume ? 'Volume' : 'Dataset'} '${fullDsName}' creation initiated.`
    );
}

// --- Function Definition for Add Vdev Dialog Trigger ---
function handleAddVdevDialog() {
    if (!currentSelection || currentSelection.obj_type !== 'pool') return;
    const poolName = currentSelection.name;

    let availableDevicesHtml = '<p class="text-muted">Loading available devices...</p>';
    let modalHtml = `
    <h6>Add VDEVs to Pool '${poolName}'</h6>
    <div class="form-check mb-3">
    <input class="form-check-input" type="checkbox" value="" id="pool-force-add-check">
    <label class="form-check-label" for="pool-force-add-check">Force Addition (-f)</label>
    </div> <hr>
    <div class="row"> <div class="col-md-5">
    <label class="form-label">Available Devices:</label>
    <ul id="pool-available-devices" class="list-group list-group-flush border rounded" style="max-height: 200px; overflow-y: auto;">${availableDevicesHtml}</ul>
    </div> <div class="col-md-1 d-flex flex-column align-items-center justify-content-center">
    <button type="button" id="pool-add-device-btn" class="btn btn-sm btn-outline-primary mb-2" title="Add Selected Device(s) to VDEV">>></button>
    <button type="button" id="pool-remove-device-btn" class="btn btn-sm btn-outline-danger mt-2" title="Remove Selected Device/VDEV"><<</button>
    </div> <div class="col-md-6">
    <label class="form-label">VDEVs to Add:</label>
    <div id="pool-vdev-config" class="border rounded p-1 bg-light" style="min-height: 150px;">
    <ul class="list-unstyled mb-0" id="pool-vdev-list"></ul></div>
    <div class="text-end mt-1">
    <button type="button" id="pool-add-vdev-btn" class="btn btn-sm btn-success"><i class="bi bi-plus-circle"></i> Add VDEV Type</button>
    </div> </div> </div>`;

    showModal(`Add VDEVs to Pool '${poolName}'`, modalHtml, handleAddVdevConfirm, { size: 'xl', setupFunc: setupCreatePoolModal });
}

// --- Function Definition for Add Vdev Confirmation ---
function handleAddVdevConfirm() {
    if (!currentSelection || currentSelection.obj_type !== 'pool') {
        console.error("handleAddVdevConfirm called without a pool selected."); return;
    }
    const poolName = currentSelection.name;
    const forceAdd = document.getElementById('pool-force-add-check').checked;

    const vdevSpecs = [];
    const vdevItems = document.querySelectorAll('#pool-vdev-list > .pool-vdev-item');
    if (vdevItems.length === 0) { alert("No VDEVs defined to add."); return; }

    let layoutValid = true;
    vdevItems.forEach(vdevLi => {
        const vdevType = vdevLi.dataset.vdevType;
        const devices = [];
        vdevLi.querySelectorAll('.pool-vdev-device-item').forEach(devLi => { devices.push(devLi.dataset.path); });
        const minDevices = { 'mirror': 2, 'raidz1': 3, 'raidz2': 4, 'raidz3': 5 }[vdevType] || 1;
        if (devices.length < minDevices) {
            alert(`VDEV type '${vdevType}' requires ${minDevices} device(s), found ${devices.length}.`);
            layoutValid = false; return;
        }
        vdevSpecs.push({ type: vdevType, devices: devices });
    });

    if (!layoutValid) return;

    actionModal.hide();
    executeAction(
        'add_vdev', [], { pool_name: poolName, vdev_specs: vdevSpecs, force: forceAdd },
        `Adding VDEVs to pool '${poolName}' initiated.`
    );
}

// --- END MOVED/FIXED FUNCTIONS ---


// --- Original Section 9 Functions Start Here ---

function handleCreatePoolConfirm() {
    const poolNameInput = document.getElementById('pool-name-input');
    const forceCheckbox = document.getElementById('pool-force-create-check');
    const poolName = poolNameInput.value.trim();
    const forceCreate = forceCheckbox.checked;

    if (!poolName || poolName.includes(' ') || poolName.includes('/')) {
        alert("Pool name is required and cannot contain spaces or '/'.");
        poolNameInput.classList.add('is-invalid');
        return;
    }
    if (!/^[a-zA-Z]/.test(poolName)) {
        alert("Pool name must start with a letter.");
        poolNameInput.classList.add('is-invalid');
        return;
    }
    if (/[^a-zA-Z0-9_\-:.%]/.test(poolName)) {
        alert("Pool name contains invalid characters. Allowed: A-Z a-z 0-9 _ - : . %");
        poolNameInput.classList.add('is-invalid');
        return;
    }
    const reserved = ['log', 'spare', 'cache', 'mirror', 'raidz', 'raidz1', 'raidz2', 'raidz3', 'replacing', 'initializing'];
    if (reserved.includes(poolName.toLowerCase())) {
        alert(`Pool name cannot be a reserved keyword ('${poolName}').`);
        poolNameInput.classList.add('is-invalid');
        return;
    }
    poolNameInput.classList.remove('is-invalid');

    const vdevSpecs = [];
    const vdevItems = document.querySelectorAll('#pool-vdev-list > .pool-vdev-item');
    if (vdevItems.length === 0) {
        alert("Pool layout is empty. Please add at least one VDEV with devices.");
        return;
    }

    let hasDataVdev = false;
    let layoutValid = true;
    vdevItems.forEach(vdevLi => {
        const vdevType = vdevLi.dataset.vdevType;
        const devices = [];
        vdevLi.querySelectorAll('.pool-vdev-device-item').forEach(devLi => {
            devices.push(devLi.dataset.path);
        });

        const minDevices = { 'mirror': 2, 'raidz1': 3, 'raidz2': 4, 'raidz3': 5 }[vdevType] || 1;
        if (devices.length < minDevices) {
            alert(`VDEV type '${vdevType}' requires at least ${minDevices} device(s). Found ${devices.length}.`);
            layoutValid = false;
            return;
        }

        vdevSpecs.push({ type: vdevType, devices: devices });
        if (!['log', 'cache', 'spare'].includes(vdevType)) {
            hasDataVdev = true;
        }
    });

    if (!layoutValid) return;

    if (!hasDataVdev) {
        alert("Pool must contain at least one data VDEV (disk, mirror, raidz).");
        return;
    }

    actionModal.hide();
    executeAction(
        'create_pool', [], { pool_name: poolName, vdev_specs: vdevSpecs, options: {}, force: forceCreate },
        `Pool '${poolName}' creation initiated.`
    );
}

function handleImportPool() {
    let modalHtml = `<p class="text-muted">Searching for importable pools...</p>
    <div id="importable-pools-list" class="list-group"></div> <hr>
    <div class="row g-3 align-items-center"> <div class="col-auto">
    <label for="import-new-name" class="col-form-label">Import Selected As:</label>
    </div> <div class="col-auto">
    <input type="text" id="import-new-name" class="form-control form-control-sm" placeholder="(optional)">
    </div> </div>
    <div class="form-check mt-2">
    <input class="form-check-input" type="checkbox" value="" id="import-force-check">
    <label class="form-check-label" for="import-force-check"> Force Import (-f) </label>
    </div>`;
    let modalFooterHtml = `
    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
    <button type="button" class="btn btn-primary" id="importModalConfirmSelectedButton" disabled>Import Selected</button>
    <button type="button" class="btn btn-warning" id="importModalConfirmAllButton" disabled>Import All</button>`;

    showModal('Import ZFS Pools', modalHtml, null, {
        footerHtml: modalFooterHtml,
        setupFunc: setupImportPoolModal,
        // Define the handler for the "Import All" button here for clarity
        onConfirmAll: () => {
            if (!confirm("Are you sure you want to attempt importing ALL listed pools?")) return;
            const force = document.getElementById('import-force-check').checked;
            actionModal.hide();
            executeAction(
                'import_pool', [],
                { pool_name_or_id: null, new_name: null, force: force },
                `Import of all pools initiated.`
            );
        }
    });
}

function setupImportPoolModal() {
    const listGroup = document.getElementById('importable-pools-list');
    const newNameInput = document.getElementById('import-new-name');
    const forceCheck = document.getElementById('import-force-check');
    const importSelectedBtn = document.getElementById('importModalConfirmSelectedButton');
    // Import All button is handled via options in showModal now

    newNameInput.disabled = true;

    importSelectedBtn.onclick = () => {
        const selectedItem = listGroup.querySelector('.list-group-item.active');
        if (!selectedItem) return;
        const poolId = selectedItem.dataset.poolId;
        const newName = newNameInput.value.trim() || null;
        const force = forceCheck.checked;

        if (newName && !/^[a-zA-Z][a-zA-Z0-9_\-:.%]*$/.test(newName)) {
            alert("Invalid new pool name format."); return;
        }
        if (newName && ['log', 'spare', 'cache', 'mirror', 'raidz', 'raidz1', 'raidz2', 'raidz3', 'replacing', 'initializing'].includes(newName.toLowerCase())) {
            alert(`New pool name cannot be a reserved keyword ('${newName}').`); return;
        }

        actionModal.hide();
        executeAction(
            'import_pool', [], { pool_name_or_id: poolId, new_name: newName, force: force },
            `Import of pool '${poolId}' initiated.`
        );
    };

    apiCall('/api/importable_pools')
    .then(result => {
        listGroup.innerHTML = '';
        const importAllBtn = document.getElementById('importModalConfirmAllButton'); // Find button again
        if (!result.data || result.data.length === 0) {
            listGroup.innerHTML = '<div class="list-group-item text-muted">No importable pools found.</div>';
            if (importAllBtn) importAllBtn.disabled = true;
            return;
        }

        result.data.forEach(pool => {
            const a = document.createElement('a');
            a.href = "#";
            a.className = 'list-group-item list-group-item-action flex-column align-items-start py-2';
            a.dataset.poolId = pool.id || pool.name;
            a.innerHTML = `
            <div class="d-flex w-100 justify-content-between">
            <h6 class="mb-1">${pool.name}</h6>
            <small class="${pool.state !== 'ONLINE' ? 'text-danger fw-bold': 'text-muted'}">${pool.state || '?'}</small>
            </div>
            <p class="mb-1"><small>ID: ${pool.id || 'N/A'}</small></p>
            ${pool.action ? `<small class="text-info">${pool.action}</small>`: ''}
            `;
            a.onclick = (e) => {
                e.preventDefault();
                listGroup.querySelectorAll('a.active').forEach(el => el.classList.remove('active'));
                a.classList.add('active');
                importSelectedBtn.disabled = false;
                newNameInput.disabled = false;
            };
            listGroup.appendChild(a);
        });
        if (importAllBtn) importAllBtn.disabled = false;
    })
    .catch(error => {
        listGroup.innerHTML = `<div class="list-group-item text-danger">Error finding pools: ${error.message}</div>`;
        importSelectedBtn.disabled = true;
        const importAllBtn = document.getElementById('importModalConfirmAllButton');
        if (importAllBtn) importAllBtn.disabled = true;
    });
}

function handleCreateSnapshot() {
    if (!currentSelection) return;
    const datasetName = currentSelection.name;
    const snapName = prompt(`Enter snapshot name for:\n${datasetName}\n(Result: ${datasetName}@<name>)`, "");
    if (snapName === null) return;
    const namePart = snapName.trim();
    if (!namePart) { alert("Snapshot name cannot be empty."); return; }
    if (/[@\/ ]/.test(namePart)) { alert("Snapshot name cannot contain '@', '/', or spaces."); return; }
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_\-:.%]*$/.test(namePart)) { alert("Snapshot name contains invalid characters."); return; }

    let recursive = false;
    if (currentSelection.children && currentSelection.children.some(c => c.obj_type === 'dataset' || c.obj_type === 'volume')) {
        recursive = confirm(`Create snapshots recursively for all child datasets/volumes under ${datasetName}?`);
    }

    executeAction(
        'create_snapshot', [datasetName, namePart, recursive], {},
        `Snapshot '${datasetName}@${namePart}' creation initiated.`
    );
}

function handleDeleteSnapshot() {
    const selectedSnapFullName = snapshotsTableBody.dataset.selectedSnapshot;
    if (!selectedSnapFullName) { alert("Please select a snapshot from the table first."); return; }
    executeAction(
        'destroy_snapshot', [selectedSnapFullName], {},
        `Snapshot '${selectedSnapFullName}' deletion initiated.`, true,
        `Are you sure you want to permanently delete snapshot:\n${selectedSnapFullName}?`
    );
}

function handleRollbackSnapshot() {
    const selectedSnapFullName = snapshotsTableBody.dataset.selectedSnapshot;
    if (!selectedSnapFullName) { alert("Please select a snapshot from the table first."); return; }
    const datasetName = selectedSnapFullName.split('@')[0];
    executeAction(
        'rollback_snapshot', [selectedSnapFullName], {},
        `Rollback to '${selectedSnapFullName}' initiated.`, true,
        `DANGER ZONE!\n\nRolling back dataset '${datasetName}' to snapshot:\n${selectedSnapFullName}\n\nThis will DESTROY ALL CHANGES made since the snapshot.\nTHIS CANNOT BE UNDONE.\n\nProceed?`
    );
}

function handleCloneSnapshot() {
    const selectedSnapFullName = snapshotsTableBody.dataset.selectedSnapshot;
    if (!selectedSnapFullName) { alert("Please select a snapshot from the table first."); return; }
    const sourceDatasetName = selectedSnapFullName.split('@')[0];
    const poolName = sourceDatasetName.split('/')[0];
    const defaultTarget = `${sourceDatasetName}-clone`;

    const targetName = prompt(`Enter the FULL PATH for the new dataset/volume cloned from:\n${selectedSnapFullName}`, defaultTarget);
    if (targetName === null) return;
    const targetPath = targetName.trim();
    if (!targetPath || targetPath.includes(' ') || !targetPath.includes('/') || targetPath.endsWith('/')) {
        alert(`Invalid target path. Must be like '${poolName}/myclone'.`); return;
    }
    if (targetPath === sourceDatasetName) { alert("Target cannot be the same as the source."); return; }
    if (!/^[a-zA-Z0-9]/.test(targetPath.split('/').pop())) { alert("Final component of target name must start with letter/number."); return; }
    if (/[^a-zA-Z0-9_\-:.%/]/.test(targetPath)) { alert("Target path contains invalid characters."); return; }

    executeAction(
        'clone_snapshot', [selectedSnapFullName, targetPath, {}], {},
        `Cloning '${selectedSnapFullName}' to '${targetPath}' initiated.`
    );
}

function handlePoolAction(actionName, requireConfirm = false, confirmMsg = null, extraArgs = [], extraKwargs = {}) {
    if (!currentSelection || currentSelection.obj_type !== 'pool') return;
    const poolName = currentSelection.name;
    executeAction(
        actionName, [poolName, ...extraArgs], extraKwargs,
        `Pool action '${actionName}' initiated for '${poolName}'.`, requireConfirm,
        confirmMsg || `Are you sure you want to perform '${actionName}' on pool '${poolName}'?`
    );
}

function handleDatasetAction(actionName, requireConfirm = false, confirmMsg = null, extraArgs = [], extraKwargs = {}) {
    if (!currentSelection || !['dataset', 'volume'].includes(currentSelection.obj_type)) return;
    const dsName = currentSelection.name;
    executeAction(
        actionName, [dsName, ...extraArgs], extraKwargs,
        `Dataset action '${actionName}' initiated for '${dsName}'.`, requireConfirm,
        confirmMsg || `Are you sure you want to perform '${actionName}' on '${dsName}'?`
    );
}

function handleRenameDataset() {
    if (!currentSelection || !['dataset', 'volume'].includes(currentSelection.obj_type)) return;
    const oldName = currentSelection.name;
    const typeStr = currentSelection.obj_type;
    const newName = prompt(`Enter the new FULL PATH for ${typeStr}:\n${oldName}`, oldName);
    if (newName === null || newName.trim() === "" || newName.trim() === oldName) return;
    const newPath = newName.trim();

    if (newPath.includes(' ') || !newPath.includes('/') || newPath.endsWith('/')) {
        alert(`Invalid target path format.`); return;
    }
    if (!/^[a-zA-Z0-9]/.test(newPath.split('/').pop())) { alert("Final component of new name must start with letter/number."); return; }
    if (/[^a-zA-Z0-9_\-:.%/]/.test(newPath)) { alert("New path contains invalid characters."); return; }

    let recursive = false;
    const force = confirm("Force unmount if dataset is busy? (Use with caution)");

    executeAction(
        'rename_dataset', [oldName, newPath], { recursive: recursive, force_unmount: force },
        `${typeStr.charAt(0).toUpperCase() + typeStr.slice(1)} '${oldName}' rename to '${newPath}' initiated.`, true,
                  `Rename ${typeStr} '${oldName}' to '${newPath}'? ${force ? '(Force unmount)' : ''}`
    );
}

// --- END OF SECTION 9 ---

// --- START OF SECTION 10 ---

// --- START MOVED/FIXED FUNCTIONS for Create Dataset ---

// --- Function Definition for Create Dataset Setup ---
function setupCreateDatasetModal() {
    // Show/hide volume size
    const typeSelect = document.getElementById('create-ds-type');
    const volSizeGroup = document.getElementById('create-ds-volsize-group');
    typeSelect.onchange = () => {
        volSizeGroup.style.display = typeSelect.value === 'volume' ? 'block' : 'none';
    };

    // Show/hide encryption options
    const encEnableCheck = document.getElementById('create-ds-enc-enable');
    const encOptionsDiv = document.getElementById('create-ds-enc-options');
    const encFormatSelect = document.getElementById('create-ds-enc-format');
    const passphraseGroup = document.getElementById('create-ds-enc-passphrase-group');
    const keylocGroup = document.getElementById('create-ds-enc-keyloc-group');

    encEnableCheck.onchange = () => {
        encOptionsDiv.style.display = encEnableCheck.checked ? 'block' : 'none';
        if (encEnableCheck.checked) {
            // Trigger change event to set initial visibility of sub-options
            const event = new Event('change');
            encFormatSelect.dispatchEvent(event);
        }
    };
    encFormatSelect.onchange = () => {
        const isPass = encFormatSelect.value === 'passphrase';
        passphraseGroup.style.display = isPass ? 'flex' : 'none'; // Use flex for row layout
        keylocGroup.style.display = isPass ? 'none' : 'flex';
    };
    // Initial state setup for encryption options when modal loads
    encOptionsDiv.style.display = encEnableCheck.checked ? 'block' : 'none';
    const isPassInitial = encFormatSelect.value === 'passphrase';
    passphraseGroup.style.display = (encEnableCheck.checked && isPassInitial) ? 'flex' : 'none';
    keylocGroup.style.display = (encEnableCheck.checked && !isPassInitial) ? 'flex' : 'none';
}

// --- Function Definition for Create Dataset Confirmation (Already Moved in Previous Section 11, but belongs logically here) ---
function handleCreateDatasetConfirm() {
    const parentName = document.getElementById('create-ds-parent').value;
    const namePart = document.getElementById('create-ds-name').value.trim();
    const dsType = document.getElementById('create-ds-type').value;
    const isVolume = dsType === 'volume';
    const volSize = document.getElementById('create-ds-volsize').value.trim();

    if (!namePart || namePart.includes(' ') || namePart.includes('/') || namePart.includes('@')) {
        alert("Invalid dataset/volume name part."); return;
    }
    if (!/^[a-zA-Z0-9]/.test(namePart)) { alert("Name part must start with letter/number."); return; }
    if (/[^a-zA-Z0-9_\-:.%]/.test(namePart)) { alert("Name part contains invalid characters."); return; }


    if (isVolume && !volSize) {
        alert("Volume Size is required for volumes."); return;
    }
    if (isVolume && !validateSizeOrNone(volSize)) {
        alert("Invalid volume size format."); return;
    }


    const fullDsName = `${parentName}/${namePart}`;
    const options = {};
    let encPassphrase = null; // Initialize here

    // Collect optional props
    const mountpoint = document.getElementById('create-ds-mountpoint').value.trim();
    if (mountpoint && mountpoint.toLowerCase() !== 'inherit') options.mountpoint = mountpoint; // Only add if not default 'inherit' placeholder
    const quota = document.getElementById('create-ds-quota').value.trim();
    if (quota && quota.toLowerCase() !== 'none') { // Only add if not default 'none' placeholder
        if (!validateSizeOrNone(quota)) { alert("Invalid Quota format."); return; }
        options.quota = quota;
    }
    const compression = document.getElementById('create-ds-compression').value;
    if (compression !== 'inherit') options.compression = compression;
    // Add other properties...

    // Collect encryption options
    if (document.getElementById('create-ds-enc-enable').checked) {
        options.encryption = document.getElementById('create-ds-enc-alg').value;
        options.keyformat = document.getElementById('create-ds-enc-format').value;
        if (options.keyformat === 'passphrase') {
            const pass1 = document.getElementById('create-ds-enc-pass').value; // Don't trim passphrase
            const pass2 = document.getElementById('create-ds-enc-confirm').value;
            if (!pass1) { alert("Passphrase cannot be empty when encryption is enabled."); return; }
            if (pass1 !== pass2) { alert("Passphrases do not match."); return; }
            encPassphrase = pass1;
            // No need for keylocation=prompt in options, it's implicit for backend
        } else { // hex or raw
            const keyloc = document.getElementById('create-ds-enc-keyloc').value.trim();
            if (!keyloc || !keyloc.startsWith('file:///')) { alert("Key Location (file URI) is required for hex/raw format."); return; }
                options.keylocation = keyloc;
        }
    }

    // Hide modal and execute
    actionModal.hide();
    executeAction(
        'create_dataset',
        [], // No direct args
        { // Kwargs for the backend function
            full_dataset_name: fullDsName,
            is_volume: isVolume,
            volsize: isVolume ? volSize : null,
            options: options,
            passphrase: encPassphrase // Pass passphrase here
        },
        `${isVolume ? 'Volume' : 'Dataset'} '${fullDsName}' creation initiated.`
    );
}

// --- END MOVED/FIXED FUNCTIONS for Create Dataset ---


// --- Action Functions - Continued ---

function handleCreateDataset() {
    if (!currentSelection || !['pool', 'dataset', 'volume'].includes(currentSelection.obj_type)) {
        console.error("handleCreateDataset called without valid selection:", currentSelection); // Add logging
        alert("Please select a pool or dataset first.");
        return;
    }
    const parentName = currentSelection.name;

    // Use the modal for a more complex form
    let modalHtml = `
    <input type="hidden" id="create-ds-parent" value="${parentName}">
    <div class="mb-3">
    <label for="create-ds-name" class="form-label">Name (under ${parentName}/):</label>
    <input type="text" class="form-control" id="create-ds-name" placeholder="e.g., mydata, images" required>
    </div>
    <div class="mb-3">
    <label for="create-ds-type" class="form-label">Type:</label>
    <select class="form-select" id="create-ds-type">
    <option value="dataset" selected>Dataset (Filesystem)</option>
    <option value="volume">Volume (Block Device)</option>
    </select>
    </div>
    <div class="mb-3" id="create-ds-volsize-group" style="display: none;">
    <label for="create-ds-volsize" class="form-label">Volume Size:</label>
    <input type="text" class="form-control" id="create-ds-volsize" placeholder="e.g., 10G, 500M">
    <div class="form-text">Required for volumes. Use K, M, G, T...</div>
    </div>
    <div class="accordion" id="createDsOptionsAccordion">
    <div class="accordion-item">
    <h2 class="accordion-header" id="headingProps">
    <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapseProps" aria-expanded="false" aria-controls="collapseProps">
    Optional Properties
    </button>
    </h2>
    <div id="collapseProps" class="accordion-collapse collapse" aria-labelledby="headingProps" data-bs-parent="#createDsOptionsAccordion">
    <div class="accordion-body">
    <!-- Add optional property fields here -->
    <div class="row mb-2">
    <label for="create-ds-mountpoint" class="col-sm-4 col-form-label col-form-label-sm">Mountpoint:</label>
    <div class="col-sm-8"><input type="text" class="form-control form-control-sm" id="create-ds-mountpoint" placeholder="inherit"></div>
    </div>
    <div class="row mb-2">
    <label for="create-ds-quota" class="col-sm-4 col-form-label col-form-label-sm">Quota:</label>
    <div class="col-sm-8"><input type="text" class="form-control form-control-sm" id="create-ds-quota" placeholder="none"></div>
    </div>
    <div class="row mb-2">
    <label for="create-ds-compression" class="col-sm-4 col-form-label col-form-label-sm">Compression:</label>
    <div class="col-sm-8">
    <select id="create-ds-compression" class="form-select form-select-sm">
    <option value="inherit" selected>inherit</option> <option value="off">off</option> <option value="on">on</option>
    <option value="lz4">lz4</option> <option value="gzip">gzip</option> <option value="gzip-9">gzip-9</option>
    <option value="zstd">zstd</option> <option value="zle">zle</option>
    </select>
    </div>
    </div>
    <!-- Add more properties (recordsize, etc.) as needed -->
    </div>
    </div>
    </div>
    <div class="accordion-item">
    <h2 class="accordion-header" id="headingEnc">
    <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapseEnc" aria-expanded="false" aria-controls="collapseEnc">
    Encryption Options
    </button>
    </h2>
    <div id="collapseEnc" class="accordion-collapse collapse" aria-labelledby="headingEnc" data-bs-parent="#createDsOptionsAccordion">
    <div class="accordion-body">
    <div class="mb-2 form-check">
    <input type="checkbox" class="form-check-input" id="create-ds-enc-enable">
    <label class="form-check-label" for="create-ds-enc-enable">Enable Encryption</label>
    </div>
    <div id="create-ds-enc-options" style="display:none;">
    <div class="row mb-2">
    <label for="create-ds-enc-alg" class="col-sm-4 col-form-label col-form-label-sm">Algorithm:</label>
    <div class="col-sm-8">
    <select id="create-ds-enc-alg" class="form-select form-select-sm">
    <option value="on" selected>on (default)</option>
    <option value="aes-256-gcm">aes-256-gcm</option> <option value="aes-192-gcm">aes-192-gcm</option> <option value="aes-128-gcm">aes-128-gcm</option>
    <option value="aes-256-ccm">aes-256-ccm</option> <option value="aes-192-ccm">aes-192-ccm</option> <option value="aes-128-ccm">aes-128-ccm</option>
    </select>
    </div>
    </div>
    <div class="row mb-2">
    <label for="create-ds-enc-format" class="col-sm-4 col-form-label col-form-label-sm">Key Format:</label>
    <div class="col-sm-8">
    <select id="create-ds-enc-format" class="form-select form-select-sm">
    <option value="passphrase" selected>Passphrase</option>
    <option value="hex">Hex Key File</option> <option value="raw">Raw Key File</option>
    </select>
    </div>
    </div>
    <div class="row mb-2" id="create-ds-enc-passphrase-group">
    <label for="create-ds-enc-pass" class="col-sm-4 col-form-label col-form-label-sm">Passphrase:</label>
    <div class="col-sm-8"><input type="password" class="form-control form-control-sm" id="create-ds-enc-pass"></div>
    <label for="create-ds-enc-confirm" class="col-sm-4 col-form-label col-form-label-sm mt-1">Confirm:</label>
    <div class="col-sm-8 mt-1"><input type="password" class="form-control form-control-sm" id="create-ds-enc-confirm"></div>
    </div>
    <div class="row mb-2" id="create-ds-enc-keyloc-group" style="display:none;">
    <label for="create-ds-enc-keyloc" class="col-sm-4 col-form-label col-form-label-sm">Key Location:</label>
    <div class="col-sm-8"><input type="text" class="form-control form-control-sm" id="create-ds-enc-keyloc" placeholder="file:///path/to/key"></div>
    <div class="offset-sm-4 col-sm-8"><small class="form-text">Must be an absolute path URI (file:///...)</small></div>
    </div>
    </div>
    </div>
    </div>
    </div>
    `;
    // Call showModal, passing the setup and confirm functions which are now defined *before* this point (in Section 9)
    showModal('Create Dataset/Volume', modalHtml, handleCreateDatasetConfirm, { setupFunc: setupCreateDatasetModal });
}


function handleDestroyDataset() {
    if (!currentSelection || !['dataset', 'volume'].includes(currentSelection.obj_type)) return;
    const dsName = currentSelection.name;
    const typeStr = currentSelection.obj_type;

    let recursive = false;
    let confirmMsg = `Are you sure you want to permanently destroy ${typeStr} '${dsName}'?`;

    const hasChildren = currentSelection.children?.length > 0;
    const hasSnapshots = currentSelection.snapshots?.length > 0;

    if (hasChildren || hasSnapshots) {
        if (confirm(`WARNING: ${typeStr} '${dsName}' contains child items and/or snapshots.\n\nDo you want to destroy it RECURSIVELY (including all children and snapshots)?`)) {
            recursive = true;
            confirmMsg = `DANGER ZONE! Are you sure you want to RECURSIVELY destroy ${typeStr} '${dsName}' and ALL its contents (children, snapshots)?\n\nTHIS CANNOT BE UNDONE.`;
        } else {
            recursive = false;
            confirmMsg = `Attempt to destroy ONLY ${typeStr} '${dsName}' (may fail if children/snapshots exist)?`;
        }
    }

    executeAction(
        'destroy_dataset',
        [dsName],
        { recursive: recursive },
        `${typeStr.charAt(0).toUpperCase() + typeStr.slice(1)} '${dsName}' destruction initiated.`,
                  true,
                  confirmMsg
    );
}

function handlePromoteDataset() {
    if (!currentSelection || !['dataset', 'volume'].includes(currentSelection.obj_type)) return;
    const dsName = currentSelection.name;
    const props = currentSelection.properties || {};
    const origin = props.origin;
    if (!origin || origin === '-') {
        alert(`'${dsName}' is not a clone and cannot be promoted.`);
        return;
    }
    executeAction(
        'promote_dataset',
        [dsName], {},
        `Promotion of clone '${dsName}' initiated.`,
        true,
        `Promote clone '${dsName}'? This breaks its dependency on the origin snapshot.`
    );
}

// Helper for actions requiring device selection
function promptAndExecuteDeviceSelect(title, message, onConfirm, allowMarkOnly = false) {
    let modalHtml = `<p>${message}</p><select id="device-select-input" class="form-select"><option value="" disabled selected>Loading devices...</option>`;
    if (allowMarkOnly) {
        modalHtml += `<option value=""><Mark for replacement only></option>`;
    }
    modalHtml += `</select>`;

    showModal(title, modalHtml,
              () => {
                  const selectedValue = document.getElementById('device-select-input').value;
                  if (selectedValue === "" && !allowMarkOnly) {
                      alert("Please select a device."); return;
                  }
                  if (selectedValue === null) return;

                  actionModal.hide();
                  onConfirm(selectedValue);
              },
              {
                  setupFunc: () => {
                      const selectEl = document.getElementById('device-select-input');
                      apiCall('/api/block_devices')
                      .then(result => {
                          selectEl.options.length = allowMarkOnly ? 2 : 1;
                          if (result.data?.length > 0) {
                              result.data.forEach(dev => {
                                  selectEl.add(new Option(dev.display_name || dev.name, dev.name));
                              });
                              selectEl.options[0].textContent = "Select a device...";
                              selectEl.options[0].disabled = true; // Keep placeholder disabled
                              if(!allowMarkOnly) selectEl.selectedIndex = 0;

                          } else {
                              selectEl.options[0].textContent = "No available devices found";
                              selectEl.options[0].disabled = true;
                          }
                      })
                      .catch(err => {
                          selectEl.options[0].textContent = "Error loading devices";
                          selectEl.options[0].disabled = true;
                          console.error("Device load error:", err);
                      });
                  }
              }
    );
}

// --- END OF SECTION 10 ---

// --- START OF SECTION 11 ---

// --- Action Functions - Pool Edit Router ---
function handlePoolEditAction(action, selectedLi) {
    //console.log(`handlePoolEditAction: action=${action}, selectedLi=`, selectedLi);
    if (!currentSelection || currentSelection.obj_type !== 'pool') {
        alert("Pool Edit Action Error: No pool selected."); return;
    }
    if (!selectedLi && action !== 'add_vdev') { // Allow add_vdev without selection
        alert("Pool Edit Action Error: No item selected in the pool layout for this action."); return;
    }

    const poolName = currentSelection.name;
    const devicePath = selectedLi?.dataset.devicePath;
    const vdevId = selectedLi?.dataset.name;
    const vdevType = selectedLi?.dataset.vdevType;

    switch(action) {
        case 'attach':
            if (!devicePath) { alert("Select the specific device or disk VDEV to attach to."); return; }
            promptAndExecuteDeviceSelect(
                "Select Device to Attach",
                `Select device to attach as mirror to:\n${devicePath}`,
                (newDevice) => {
                    executeAction('attach_device', [poolName, devicePath, newDevice], {},
                                  `Attach initiated for ${newDevice} to ${devicePath}.`, true,
                                  `Attach '${newDevice}' as mirror to '${devicePath}' in pool '${poolName}'?`);
                }
            );
            break;
        case 'detach':
            if (!devicePath) { alert("Select the device within a mirror to detach."); return; }
            const parentLi = selectedLi?.parentElement?.closest('li.pool-edit-item');
            if (parentLi?.dataset.vdevType !== 'mirror') {
                alert("Detach is only possible for devices within a mirror."); return;
            }
            executeAction('detach_device', [poolName, devicePath], {},
                          `Detach initiated for ${devicePath}.`, true,
                          `Detach device '${devicePath}' from its mirror in pool '${poolName}'?`);
            break;
        case 'replace':
            if (!devicePath) { alert("Select the specific device or disk VDEV to replace."); return; }
            promptAndExecuteDeviceSelect(
                "Select Replacement Device",
                `Select NEW device to replace:\n${devicePath}\n(Choose 'Mark Only' to replace later)`,
                                         (newDevice) => {
                                             const isMarkOnly = newDevice === "";
                                             executeAction('replace_device', [poolName, devicePath, newDevice], {},
                                                           `Replacement initiated for ${devicePath}.`, true,
                                                           `Replace device '${devicePath}' ${isMarkOnly ? '(mark only)' : `with '${newDevice}'`} in pool '${poolName}'?`);
                                         },
                                         true
            );
            break;
        case 'offline':
            if (!devicePath) { alert("Select the specific device or disk VDEV to take offline."); return; }
            const temporary = confirm(`Take device '${devicePath}' offline temporarily?\n(May come back online after reboot)`);
            executeAction('offline_device', [poolName, devicePath, temporary], {},
                          `Offline initiated for ${devicePath}.`, true,
                          `Take device '${devicePath}' offline ${temporary ? '(temporarily)' : ''} in pool '${poolName}'?`);
            break;
        case 'online':
            if (!devicePath) { alert("Select the specific device or disk VDEV to bring online."); return; }
            const expand = confirm(`Attempt to expand capacity if '${devicePath}' is larger than original?`);
            executeAction('online_device', [poolName, devicePath, expand], {},
                          `Online initiated for ${devicePath}.`, true,
                          `Bring device '${devicePath}' online ${expand ? 'and expand ' : ''}in pool '${poolName}'?`);
            break;
        case 'remove_vdev':
            if (!vdevId) { alert("Could not identify VDEV to remove."); return; }
            let idToRemove = vdevId;
            if (['log', 'cache', 'spare'].includes(vdevType)) {
                const firstDeviceLi = selectedLi.querySelector(':scope > ul.pool-edit-children > li[data-item-type="device"]');
                if (firstDeviceLi && firstDeviceLi.dataset.devicePath) {
                    idToRemove = firstDeviceLi.dataset.devicePath;
                    //console.log(`Identified actual device '${idToRemove}' for special VDEV '${vdevId}'`);
                } else {
                    idToRemove = selectedLi.dataset.name;
                    console.warn(`Could not find child device path for special VDEV '${vdevId}', attempting removal using name '${idToRemove}'`);
                }
            } else if (vdevType === 'disk' && devicePath) {
                idToRemove = devicePath;
            }
            executeAction('remove_vdev', [poolName, idToRemove], {},
                          `Removal initiated for ${idToRemove}.`, true,
                          `WARNING: Removing VDEVs can be dangerous!\nAre you sure you want to attempt remove '${idToRemove}' from pool '${poolName}'?`);
            break;
        case 'split':
            if (selectedLi?.dataset.itemType !== 'pool') {
                alert("Select the top-level pool item in the 'Edit Pool' tab to initiate split."); return;
            }
            const newPoolName = prompt(`Enter name for the new pool created by splitting '${poolName}':`);
            if (newPoolName === null) return; // User cancelled
            const newName = newPoolName.trim();
        if (!newName || newName === poolName || !/^[a-zA-Z][a-zA-Z0-9_\-:.%]*$/.test(newName) || ['log', 'spare', 'cache', 'mirror', 'raidz', 'raidz1', 'raidz2', 'raidz3', 'replacing', 'initializing'].includes(newName.toLowerCase())) {
            alert("Invalid or reserved new pool name."); return;
        }
        executeAction('split_pool', [poolName, newName, {}], {},
                      `Split initiated for ${poolName} into ${newName}.`, true,
                      `Split pool '${poolName}' into new pool '${newName}'?\n(Detaches second device of each top-level mirror)`);
        break;
        case 'add_vdev':
            handleAddVdevDialog(); // Call the moved function (defined in Section 9)
            break;
        default:
            console.warn("Unknown pool edit action:", action);
    }
}


// --- Encryption Actions ---
function handleLoadKey() {
    if (!currentSelection || !currentSelection.is_encrypted) return;
    const dsName = currentSelection.name;
    const keyLocation = currentSelection.properties?.keylocation || 'prompt';
    const keyFormat = currentSelection.properties?.keyformat || 'passphrase';

    let locationToSend = (keyLocation === 'prompt' || keyLocation === '-') ? null : keyLocation;

    if (keyLocation === 'prompt' && keyFormat === 'passphrase') {
        let modalHtml = `
        <p>Enter passphrase for:\n<b>${dsName}</b></p>
        <div class="mb-2">
        <label for="load-key-pass" class="form-label">Passphrase:</label>
        <input type="password" id="load-key-pass" class="form-control" required>
        </div>`;
        showModal("Load Encryption Key", modalHtml, () => {
            const passInput = document.getElementById('load-key-pass');
            const passphrase = passInput.value;
            if (passphrase === "") {
                alert("Passphrase cannot be empty.");
                passInput.focus();
                return;
            }
            locationToSend = null;
            actionModal.hide();
            executeAction(
                'load_key', [],
                { dataset_name: dsName, recursive: false, key_location: locationToSend, passphrase: passphrase },
                `Key load initiated for '${dsName}'.`
            );
        });
        return;
    } else if (locationToSend && !locationToSend.startsWith('file:///')) {
        alert(`Invalid key location '${keyLocation}'. Cannot load key.`); return;
    }

    executeAction(
        'load_key', [],
        { dataset_name: dsName, recursive: false, key_location: locationToSend, passphrase: null },
        `Key load initiated for '${dsName}'.`
    );
}

function handleUnloadKey() {
    if (!currentSelection || !currentSelection.is_encrypted) return;
    const dsName = currentSelection.name;
    if (currentSelection.is_mounted || currentSelection.properties?.mounted === 'yes') {
        alert(`Dataset '${dsName}' must be unmounted before its key can be unloaded.`);
        return;
    }
    let recursive = false;
    if (currentSelection.children?.some(c => c.is_encrypted)) {
        recursive = confirm(`Unload keys recursively for child datasets under '${dsName}'?`);
    }
    executeAction(
        'unload_key', [], { dataset_name: dsName, recursive: recursive },
        `Key unload initiated for '${dsName}'.`, true,
        `Unload encryption key${recursive ? ' recursively' : ''} for '${dsName}'?\nData will become inaccessible.`
    );
}

function handleChangeKey() {
    if (!currentSelection || !currentSelection.is_encrypted || currentSelection.properties?.keystatus !== 'available') {
        alert("Key must be loaded (available) to change it."); return;
    }
    const dsName = currentSelection.name;
    const keyFormat = currentSelection.properties?.keyformat || 'passphrase';

    if (keyFormat === 'passphrase') {
        let modalHtml = `
        <p>Set NEW passphrase for '${dsName}':</p>
        <div class="mb-2">
        <label for="change-key-new-pass" class="form-label">New Passphrase:</label>
        <input type="password" id="change-key-new-pass" class="form-control">
        </div>
        <div class="mb-2">
        <label for="change-key-confirm-pass" class="form-label">Confirm New Passphrase:</label>
        <input type="password" id="change-key-confirm-pass" class="form-control">
        </div>`;
        showModal("Change Passphrase", modalHtml, () => {
            const pass1 = document.getElementById('change-key-new-pass').value;
            const pass2 = document.getElementById('change-key-confirm-pass').value;
            if (!pass1) { alert("New passphrase cannot be empty."); return; }
            if (pass1 !== pass2) { alert("New passphrases do not match."); return; }
            const changeInfo = `${pass1}\n${pass1}\n`;
            actionModal.hide();
            executeAction(
                'change_key', [],
                { dataset_name: dsName, load_key: true, recursive: false, options: {keyformat: 'passphrase'}, passphrase_change_info: changeInfo },
                `Passphrase change initiated for '${dsName}'.`
            );
        });
    } else {
        alert("Changing key files via the web UI is not yet implemented. Use 'Change Key Location' instead if you only want to point to a different existing key file.");
    }
}

function handleChangeKeyLocation() {
    if (!currentSelection || !currentSelection.is_encrypted) return;
    const dsName = currentSelection.name;
    const currentLoc = currentSelection.properties?.keylocation || 'prompt';
    const newLoc = prompt(`Enter new key location for '${dsName}':\n(Current: ${currentLoc})\nUse 'prompt' or 'file:///path/to/key'`, currentLoc);
    if (newLoc === null || newLoc.trim() === "" || newLoc.trim() === currentLoc) return;
    const newLocation = newLoc.trim();
    if (newLocation !== 'prompt' && !newLocation.startsWith('file:///')) {
        alert("Invalid location format. Use 'prompt' or 'file:///...'"); return;
    }
    executeAction(
        'set_dataset_property',
        [dsName, 'keylocation', newLocation], {},
        `Key location change initiated for '${dsName}'.`, true,
        `Change key location property for '${dsName}' to:\n'${newLocation}'?`
    );
}

function handleShutdownDaemon() {
    executeAction(
        'shutdown_daemon', [], {},
        "Daemon shutdown requested.", true,
        "Stop the ZfDash background daemon process?\n(Requires authentication on next start)"
    );
}

// --- Utility Functions ---
function showModal(title, bodyHtml, onConfirm, options = {}) {
    if (!actionModal || !actionModalBody || !actionModalLabel || !actionModalFooter) {
        console.error("Modal elements not found!");
        alert("Modal Error - Check Console"); // Fallback
        return;
    }

    actionModalLabel.textContent = title;
    actionModalBody.innerHTML = bodyHtml;

    const modalDialog = modalElement.querySelector('.modal-dialog');
    if (modalDialog) {
        modalDialog.classList.remove('modal-lg', 'modal-xl', 'modal-sm');
        if (options.size) {
            modalDialog.classList.add(`modal-${options.size}`);
        } else {
            modalDialog.classList.add('modal-lg');
        }
    } else {
        console.error("Modal dialog element not found!");
        alert("Modal Error - Check Console"); // Fallback
        return;
    }

    const oldConfirmButton = document.getElementById('actionModalConfirmButton');
    if(oldConfirmButton) oldConfirmButton.replaceWith(oldConfirmButton.cloneNode(true));

    if (options.footerHtml) {
        actionModalFooter.innerHTML = options.footerHtml;
        const newConfirmButton = document.getElementById('actionModalConfirmButton');
        if (newConfirmButton && onConfirm) {
            newConfirmButton.addEventListener('click', onConfirm);
        }
        // Also handle potential other buttons in custom footer
        const newImportAllButton = document.getElementById('importModalConfirmAllButton');
        if (newImportAllButton && options.onConfirmAll) { // Check for specific handler
            newImportAllButton.addEventListener('click', options.onConfirmAll);
        }
    } else {
        actionModalFooter.innerHTML = `
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
            actionModalBody.innerHTML += `<div class="alert alert-danger mt-2">Error setting up modal: ${e.message}</div>`;
        }
    }

    actionModal.show();
}

function showErrorAlert(title, message) {
    alert(`${title}\n\n${message}`);
}


// --- Initial Load & Event Listeners ---
document.addEventListener('DOMContentLoaded', () => {

    // --- Authentication Related Listeners ---
    if (loginForm) loginForm.addEventListener('submit', handleLogin);
    if (logoutButton) logoutButton.addEventListener('click', handleLogout);
    if (changePasswordConfirmButton) changePasswordConfirmButton.addEventListener('click', handleChangePassword);
    // Clear change password modal messages when shown
    if (changePasswordModalElement) {
        changePasswordModalElement.addEventListener('show.bs.modal', () => {
            if (changePasswordError) changePasswordError.style.display = 'none';
            if (changePasswordSuccess) changePasswordSuccess.style.display = 'none';
            if (changePasswordForm) changePasswordForm.reset();
        });
    }
    // --- End Auth Listeners ---

    // --- Fix for encryption tab spacing ---
    const encryptionTab = document.getElementById('encryption-tab-button');
    if (encryptionTab) {
        encryptionTab.addEventListener('shown.bs.tab', function() {
            const encryptionPane = document.getElementById('encryption-tab-pane');
            if (encryptionPane) {
                // Position tab content directly below tabs
                const tabsNav = document.querySelector('.nav-tabs');
                if (tabsNav) {
                    // Apply positioning styles
                    Object.assign(encryptionPane.style, {
                        position: 'absolute',
                        top: tabsNav.offsetHeight + 'px',
                        left: '0',
                        right: '0',
                        zIndex: '10',
                        backgroundColor: '#fff',
                        borderTop: '0',
                        padding: '0',
                        margin: '0'
                    });
                }
                
                // Apply consistent styling to table elements
                encryptionPane.querySelectorAll('table, th, td').forEach(el => {
                    Object.assign(el.style, {
                        margin: '0',
                        border: '0',
                        padding: '2px 8px'
                    });
                });
                
                // Style headings for consistent spacing
                encryptionPane.querySelectorAll('h5').forEach(h => {
                    Object.assign(h.style, {
                        marginTop: '0',
                        paddingTop: '5px',
                        marginBottom: '5px'
                    });
                });
            }
        });
    }

    const buttonsToDisable = [
        'destroy-pool-button', 'export-pool-button', 'scrub-start-button', 'scrub-stop-button', 'clear-errors-button',
        'create-dataset-button', 'destroy-dataset-button', 'rename-dataset-button', 'mount-dataset-button', 'unmount-dataset-button', 'promote-dataset-button'
    ];
    buttonsToDisable.forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.classList.add('disabled');
    });
        // These are always enabled initially, auth state controls visibility/actual function
        document.getElementById('create-pool-button')?.classList.remove('disabled');
        document.getElementById('import-pool-button')?.classList.remove('disabled');

        // Check auth status first, which will trigger data load if authenticated
        checkAuthStatus();

        // Refresh button should only work if authenticated
        refreshButton.addEventListener('click', () => {
            if (isAuthenticated) {
                fetchAndRenderData();
            } else {
                console.log("Refresh skipped: Not authenticated.");
            }
        });

        // Global Action Buttons (Dropdowns)
        document.getElementById('create-pool-button').addEventListener('click', handleCreatePool);
        document.getElementById('import-pool-button').addEventListener('click', handleImportPool);
        document.getElementById('destroy-pool-button').addEventListener('click', () => handlePoolAction('destroy_pool', true, `DANGER ZONE!\n\nDestroy pool '${currentSelection?.name}' and ALL data?\nTHIS CANNOT BE UNDONE.`));
        document.getElementById('export-pool-button').addEventListener('click', () => { const force = confirm("Force export?"); handlePoolAction('export_pool', true, `Export pool '${currentSelection?.name}'?`, [], { force: force }); });
        document.getElementById('scrub-start-button').addEventListener('click', () => handlePoolAction('scrub_pool', false, null, [], { stop: false }));
        document.getElementById('scrub-stop-button').addEventListener('click', () => handlePoolAction('scrub_pool', false, null, [], { stop: true }));
        document.getElementById('clear-errors-button').addEventListener('click', () => handlePoolAction('clear_pool_errors', true, `Clear persistent errors for pool '${currentSelection?.name}'?`));

        // --- Dataset Button Listeners ---
        document.getElementById('create-dataset-button').addEventListener('click', handleCreateDataset); // Listener is correct
        document.getElementById('destroy-dataset-button').addEventListener('click', handleDestroyDataset);
        document.getElementById('rename-dataset-button').addEventListener('click', handleRenameDataset);
        document.getElementById('mount-dataset-button').addEventListener('click', () => handleDatasetAction('mount_dataset'));
        document.getElementById('unmount-dataset-button').addEventListener('click', () => handleDatasetAction('unmount_dataset'));
        document.getElementById('promote-dataset-button').addEventListener('click', handlePromoteDataset);

        // Snapshot Tab Buttons
        document.getElementById('create-snapshot-button').addEventListener('click', handleCreateSnapshot);
        document.getElementById('delete-snapshot-button').addEventListener('click', handleDeleteSnapshot);
        document.getElementById('rollback-snapshot-button').addEventListener('click', handleRollbackSnapshot);
        document.getElementById('clone-snapshot-button').addEventListener('click', handleCloneSnapshot);

        // Pool Edit Tab Buttons
        document.getElementById('attach-device-button').addEventListener('click', () => handlePoolEditAction('attach', poolEditTreeContainer.querySelector('.selected')));
        document.getElementById('detach-device-button').addEventListener('click', () => handlePoolEditAction('detach', poolEditTreeContainer.querySelector('.selected')));
        document.getElementById('replace-device-button').addEventListener('click', () => handlePoolEditAction('replace', poolEditTreeContainer.querySelector('.selected')));
        document.getElementById('offline-device-button').addEventListener('click', () => handlePoolEditAction('offline', poolEditTreeContainer.querySelector('.selected')));
        document.getElementById('online-device-button').addEventListener('click', () => handlePoolEditAction('online', poolEditTreeContainer.querySelector('.selected')));
        document.getElementById('add-pool-vdev-button').addEventListener('click', handleAddVdevDialog); // Calls moved function
        document.getElementById('remove-pool-vdev-button').addEventListener('click', () => handlePoolEditAction('remove_vdev', poolEditTreeContainer.querySelector('.selected')));
        document.getElementById('split-pool-button').addEventListener('click', () => handlePoolEditAction('split', poolEditTreeContainer.querySelector('.selected')));

        // Encryption Tab Buttons
        document.getElementById('load-key-button').addEventListener('click', handleLoadKey);
        document.getElementById('unload-key-button').addEventListener('click', handleUnloadKey);
        document.getElementById('change-key-button').addEventListener('click', handleChangeKey);
        document.getElementById('change-key-location-button').addEventListener('click', handleChangeKeyLocation);

        // Shutdown Button (Listener already added, visibility controlled by auth state)
        document.getElementById('shutdown-daemon-button').addEventListener('click', handleShutdownDaemon);

});

// --- END OF FILE src/static/js/app.js ---
// --- END OF SECTION 11 ---
// --- END OF FILE src/static/js/app.js ---
