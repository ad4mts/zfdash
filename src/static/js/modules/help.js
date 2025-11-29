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
 * Handle Check for Updates button click - shows modal dialog
 */
async function handleCheckForUpdates() {
    const data = await fetchVersionInfo();
    const version = data ? data.version : 'unknown';
    const repository = data ? data.repository : 'https://github.com/ad4mts/zfdash';
    
    // Update modal content
    const versionEl = document.getElementById('updates-current-version');
    const releasesLink = document.getElementById('updates-releases-link');
    
    if (versionEl) versionEl.textContent = `v${version}`;
    if (releasesLink) releasesLink.href = `${repository}/releases`;
    
    // Show the modal
    const modal = new bootstrap.Modal(document.getElementById('checkUpdatesModal'));
    modal.show();
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
