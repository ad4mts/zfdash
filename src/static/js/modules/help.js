/**
 * help.js - Help Menu Functionality
 * 
 * Handles About dialog and Check for Updates functionality.
 */

/**
 * Fetch version info from the backend API
 * @returns {Promise<Object>} Version information object
 */
async function fetchVersionInfo() {
    try {
        const response = await fetch('/api/version');
        const data = await response.json();
        if (data.status === 'success') {
            return data;
        }
        throw new Error('Invalid response status');
    } catch (error) {
        console.error('Failed to fetch version info:', error);
        return null;
    }
}

/**
 * Populate the About modal with version information
 */
async function populateAboutModal() {
    const data = await fetchVersionInfo();
    
    if (data) {
        const appNameEl = document.getElementById('about-app-name');
        const versionEl = document.getElementById('about-version');
        const descriptionEl = document.getElementById('about-description');
        const authorEl = document.getElementById('about-author');
        const pythonVersionEl = document.getElementById('about-python-version');
        const licenseEl = document.getElementById('about-license');
        const repoLink = document.getElementById('about-repository');
        const copyrightEl = document.getElementById('about-copyright');
        
        if (appNameEl) appNameEl.textContent = data.app_name || 'ZfDash';
        if (versionEl) versionEl.textContent = `Version: ${data.version || 'unknown'}`;
        if (descriptionEl) descriptionEl.textContent = data.description || '';
        if (authorEl) authorEl.textContent = data.author || '-';
        if (pythonVersionEl) pythonVersionEl.textContent = data.python_version || '-';
        if (licenseEl) licenseEl.textContent = data.license || '-';
        if (repoLink && data.repository) {
            repoLink.href = data.repository;
            repoLink.textContent = data.repository;
        }
        if (copyrightEl) copyrightEl.textContent = data.copyright || '';
    } else {
        const versionEl = document.getElementById('about-version');
        if (versionEl) versionEl.textContent = 'Version: unavailable';
    }
}

/**
 * Fetch update check info from the backend API
 * @returns {Promise<Object>} Update check result object
 */
async function checkForUpdates() {
    try {
        const response = await fetch('/api/check_updates');
        return await response.json();
    } catch (error) {
        console.error('Failed to check for updates:', error);
        return {
            success: false,
            error: 'Network error: Could not reach the server'
        };
    }
}

/**
 * Hide all update state divs
 */
function hideAllUpdateStates() {
    const states = ['updates-loading', 'updates-error', 'updates-uptodate', 'updates-available'];
    states.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
}

/**
 * Show a specific update state div
 */
function showUpdateState(stateId) {
    hideAllUpdateStates();
    const el = document.getElementById(stateId);
    if (el) el.style.display = 'block';
}

/**
 * Populate update instructions from the API response
 * @param {Object} instructions - Instructions object from API
 */
function populateUpdateInstructions(instructions) {
    const titleEl = document.getElementById('updates-deployment-title');
    const sourceEl = document.getElementById('updates-instructions-source');
    const stepsList = document.getElementById('updates-steps-list');
    const notesContainer = document.getElementById('updates-notes-container');
    const notesList = document.getElementById('updates-notes-list');
    
    if (!instructions || !instructions.success) {
        // Fallback if instructions fetch failed
        if (titleEl) titleEl.textContent = 'Update Instructions';
        if (sourceEl) sourceEl.textContent = '(could not fetch latest instructions)';
        if (stepsList) {
            stepsList.innerHTML = '<li>Visit the GitHub releases page for update instructions.</li>';
        }
        return;
    }
    
    // Set title and source
    if (titleEl) titleEl.textContent = instructions.title || 'Update Instructions';
    if (sourceEl) {
        const sourceText = instructions.source === 'remote' ? '(Source: latest from GitHub)' : '(Source: local cache ⚠️)';
        sourceEl.textContent = sourceText;
    }
    
    // Populate steps
    if (stepsList && instructions.steps) {
        stepsList.innerHTML = '';
        instructions.steps.forEach(step => {
            const li = document.createElement('li');
            li.className = 'mb-2';
            
            let content = `<strong>${escapeHtml(step.title)}:</strong>`;
            if (step.command) {
                content += `<pre class="bg-dark text-light p-2 rounded mt-1 mb-0" style="white-space: pre-wrap; font-size: 0.85em;"><code>${escapeHtml(step.command)}</code></pre>`;
            } else if (step.description) {
                content += ` <span class="text-muted">${escapeHtml(step.description)}</span>`;
            }
            
            li.innerHTML = content;
            stepsList.appendChild(li);
        });
    }
    
    // Populate notes
    if (notesContainer && notesList && instructions.notes && instructions.notes.length > 0) {
        notesList.innerHTML = '';
        instructions.notes.forEach(note => {
            const li = document.createElement('li');
            li.textContent = note;
            notesList.appendChild(li);
        });
        notesContainer.style.display = 'block';
    } else if (notesContainer) {
        notesContainer.style.display = 'none';
    }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Handle Check for Updates button click - shows modal dialog with real update check
 */
async function handleCheckForUpdates() {
    // Show the modal first with loading state
    showUpdateState('updates-loading');
    const modal = new bootstrap.Modal(document.getElementById('checkUpdatesModal'));
    modal.show();
    
    // Perform the actual update check
    const data = await checkForUpdates();
    
    if (!data.success) {
        // Error state
        showUpdateState('updates-error');
        const errorMsg = document.getElementById('updates-error-message');
        const errorLink = document.getElementById('updates-error-releases-link');
        if (errorMsg) errorMsg.textContent = data.error || 'Unknown error';
        if (errorLink) errorLink.href = data.releases_url || 'https://github.com/ad4mts/zfdash/releases';
        return;
    }
    
    if (data.update_available) {
        // Update available state
        showUpdateState('updates-available');
        
        // Update version badges
        const currentBadge = document.getElementById('updates-current-badge');
        const latestBadge = document.getElementById('updates-latest-badge');
        if (currentBadge) currentBadge.textContent = `Current: v${data.current_version}`;
        if (latestBadge) latestBadge.textContent = `Latest: v${data.latest_version}`;
        
        // Update releases link
        const releasesLink = document.getElementById('updates-releases-link');
        if (releasesLink) releasesLink.href = data.release_url || data.releases_url || 'https://github.com/ad4mts/zfdash/releases';
        
        // Populate instructions dynamically from API response
        populateUpdateInstructions(data.instructions);
    } else {
        // Up to date state
        showUpdateState('updates-uptodate');
        const currentVersionOk = document.getElementById('updates-current-version-ok');
        const latestVersionOk = document.getElementById('updates-latest-version-ok');
        if (currentVersionOk) currentVersionOk.textContent = `v${data.current_version}`;
        if (latestVersionOk) latestVersionOk.textContent = `v${data.latest_version}`;
    }
}

/**
 * Initialize Help menu event listeners
 */
export function initHelpMenu() {
    // About modal - fetch version info when shown
    const aboutModalElement = document.getElementById('aboutModal');
    if (aboutModalElement) {
        aboutModalElement.addEventListener('show.bs.modal', populateAboutModal);
    }

    // Check for Updates button
    const checkUpdatesButton = document.getElementById('check-updates-button');
    if (checkUpdatesButton) {
        checkUpdatesButton.addEventListener('click', handleCheckForUpdates);
    }
}

// --- END OF FILE src/static/js/modules/help.js ---
