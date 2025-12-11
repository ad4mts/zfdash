/**
 * help.js - Help Menu Functionality and Help Strings System
 * 
 * Handles About dialog, Check for Updates, and provides help content for the UI.
 */

import { showWarning } from './notifications.js';

// Cached help strings
let helpStrings = null;

// ============================================================================
// HELP STRINGS API
// ============================================================================

/**
 * Fetch help strings from the backend.
 * @returns {Promise<object>} - The help strings object
 */
export async function loadHelpStrings() {
    if (helpStrings) {
        return helpStrings;
    }

    try {
        const response = await fetch('/api/help_strings');
        if (!response.ok) {
            console.warn('Could not load help strings:', response.status);
            return {};
        }
        const data = await response.json();
        if (data.status === 'success' && data.help) {
            helpStrings = data.help;
            return helpStrings;
        }
    } catch (error) {
        console.warn('Error loading help strings:', error);
    }
    return {};
}

/**
 * Get help info for a VDEV type.
 * @param {string} vdevType - The VDEV type (e.g., 'mirror', 'special')
 * @returns {object} - Help info object with name, short, warning, tip, etc.
 */
export function getVdevHelp(vdevType) {
    if (!helpStrings || !helpStrings.vdev_types) {
        return {};
    }
    return helpStrings.vdev_types[vdevType.toLowerCase()] || {};
}

/**
 * Get empty state info for a UI context.
 * @param {string} context - Context name (e.g., 'create_pool_vdev_tree')
 * @returns {object} - Empty state info with title, message, steps
 */
export function getEmptyState(context) {
    if (!helpStrings || !helpStrings.empty_states) {
        return {};
    }
    return helpStrings.empty_states[context] || {};
}

/**
 * Get warning info for an action.
 * @param {string} action - Action name (e.g., 'destroy_pool')
 * @returns {object} - Warning info
 */
export function getWarning(action) {
    if (!helpStrings || !helpStrings.warnings) {
        return {};
    }
    return helpStrings.warnings[action] || {};
}

/**
 * Get a tooltip for a UI element.
 * @param {string} element - Element name
 * @returns {string} - Tooltip text
 */
export function getTooltip(element) {
    if (!helpStrings || !helpStrings.tooltips) {
        return '';
    }
    return helpStrings.tooltips[element] || '';
}

/**
 * Get a helpful tip.
 * @param {string} topic - Topic name
 * @returns {string} - Tip text
 */
export function getTip(topic) {
    if (!helpStrings || !helpStrings.tips) {
        return '';
    }
    return helpStrings.tips[topic] || '';
}

/**
 * Render VDEV type info into an HTML element.
 * @param {string} vdevType - The VDEV type
 * @param {HTMLElement} container - The container element to render into
 */
export function renderVdevTypeInfo(vdevType, container) {
    const info = getVdevHelp(vdevType);
    if (!info || !container) return;

    container.innerHTML = '';
    container.style.display = 'block';

    // Name and short description
    const nameSpan = document.createElement('strong');
    nameSpan.textContent = info.name || vdevType;
    container.appendChild(nameSpan);

    if (info.short) {
        const desc = document.createElement('span');
        desc.textContent = `: ${info.short}`;
        container.appendChild(desc);
    }

    // Warning (red)
    if (info.warning) {
        const warning = document.createElement('div');
        warning.className = 'text-danger small mt-1';
        warning.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-1"></i>${escapeHtml(info.warning)}`;
        container.appendChild(warning);
        // Note: Warning is displayed inline - no toast to avoid modal interference
    }

    // Tip (green)
    if (info.tip) {
        const tip = document.createElement('div');
        tip.className = 'text-success small mt-1';
        tip.innerHTML = `<i class="bi bi-lightbulb-fill me-1"></i>${escapeHtml(info.tip)}`;
        container.appendChild(tip);
    }

    // Recommended alternative
    if (info.recommended_alternative) {
        const alt = document.createElement('div');
        alt.className = 'text-info small mt-1';
        alt.innerHTML = `<i class="bi bi-arrow-right-circle me-1"></i>Consider using: <strong>${escapeHtml(info.recommended_alternative)}</strong>`;
        container.appendChild(alt);
    }

    // Set appropriate background class
    if (info.warning) {
        container.className = 'alert alert-warning small py-2 px-3 mt-2';
    } else if (info.tip) {
        container.className = 'alert alert-success small py-2 px-3 mt-2';
    } else {
        container.className = 'alert alert-info small py-2 px-3 mt-2';
    }
}

/**
 * Render empty state guidance into an HTML element.
 * @param {string} context - The empty state context
 * @param {HTMLElement} container - The container element
 */
export function renderEmptyState(context, container) {
    const info = getEmptyState(context);
    if (!info || !container) return;

    container.innerHTML = `
        <div class="text-center text-muted py-4">
            <i class="bi bi-diagram-3 fs-1"></i>
            <h5 class="mt-3">${escapeHtml(info.title || 'No items')}</h5>
            <p class="small">${escapeHtml(info.message || '')}</p>
            ${info.steps ? `
                <ol class="text-start small mx-auto" style="max-width: 300px;">
                    ${info.steps.map(step => `<li>${escapeHtml(step)}</li>`).join('')}
                </ol>
            ` : ''}
        </div>
    `;
}

/**
 * Hide VDEV type info container.
 * @param {HTMLElement} container - The container element
 */
export function hideVdevTypeInfo(container) {
    if (container) {
        container.style.display = 'none';
        container.innerHTML = '';
    }
}

// ============================================================================
// EXISTING HELP MENU FUNCTIONALITY
// ============================================================================

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

    // Load help strings on init
    loadHelpStrings().catch(e => console.warn('Could not preload help strings:', e));
}

// Export help strings for use in other modules
export { helpStrings };

// --- END OF FILE src/static/js/modules/help.js ---

