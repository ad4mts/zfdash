/**
 * backup-page.js - Backup Page Controller
 * 
 * Handles the backup page UI:
 * - Loads and displays ZFS tree for source selection
 * - Manages backup form submission
 * - Coordinates with backup API
 */

import { apiCall } from './api.js';
import * as vault from './vault-ui.js';
import * as connectionIndicator from './connection-indicator.js';
import { BackupTreeView } from './backup-tree.js';

// Module state
let selectedSource = null;
let connectionInfo = null;  // Stores current connection mode and agent info
let backupTree = null;      // Main tree view instance

// Debounce timers for auto-incremental detection
let incrementalDebounceTimers = {};

/**
 * Debounce helper - delays function execution until pause in calls
 */
function debounce(key, fn, delay = 500) {
    if (incrementalDebounceTimers[key]) {
        clearTimeout(incrementalDebounceTimers[key]);
    }
    incrementalDebounceTimers[key] = setTimeout(fn, delay);
}

/**
 * Unified auto-incremental base detection for all tab types
 * @param {Object} config Configuration object
 * @param {string} config.tabType - 'agent', 'a2a', 'local', 'ssh'
 * @param {string} config.dropdownId - ID of the dropdown element
 * @param {string} config.statusId - ID of the status badge (optional)
 * @param {function} config.getSourceDataset - Function returning source dataset name
 * @param {function} config.getDestConfig - Function returning destination config for API
 */
async function findIncrementalBaseFor(config) {
    const { tabType, dropdownId, statusId, getSourceDataset, getDestConfig } = config;

    const dropdown = document.getElementById(dropdownId);
    const statusBadge = statusId ? document.getElementById(statusId) : null;

    if (!dropdown) return;

    // Get source dataset
    const sourceDataset = getSourceDataset();
    if (!sourceDataset) {
        dropdown.innerHTML = '<option value="">-- Select source first --</option>';
        if (statusBadge) statusBadge.style.display = 'none';
        return;
    }

    // Get destination config
    const destConfig = getDestConfig();
    if (!destConfig) {
        dropdown.innerHTML = '<option value="">-- Fill in destination first --</option>';
        if (statusBadge) statusBadge.style.display = 'none';
        return;
    }

    dropdown.innerHTML = '<option value="">-- Checking... --</option>';

    try {
        const requestData = {
            source_dataset: sourceDataset,
            dest_type: destConfig.type,
            dest_dataset: destConfig.dataset
        };

        // Add source agent if remote source (A2A)
        if (destConfig.sourceAgent) {
            requestData.source_agent = destConfig.sourceAgent;
        }

        // Add destination-specific config
        if (destConfig.type === 'agent' && destConfig.agent) {
            requestData.dest_agent = destConfig.agent;
        } else if (destConfig.type === 'ssh' && destConfig.ssh) {
            requestData.dest_ssh = destConfig.ssh;
        }

        const result = await apiCall('/api/backup/find-incremental-base', 'POST', requestData);

        dropdown.innerHTML = '';

        if (result.incremental_base) {
            const autoOption = document.createElement('option');
            autoOption.value = result.incremental_base;
            autoOption.textContent = `${result.incremental_base} (auto-detected)`;
            autoOption.selected = true;
            dropdown.appendChild(autoOption);

            if (statusBadge) {
                statusBadge.style.display = 'inline-block';
                statusBadge.className = 'badge bg-success';
                statusBadge.innerHTML = '<i class="bi bi-check-circle"></i> Auto-detected';
            }
        } else {
            const noMatch = document.createElement('option');
            noMatch.value = '';
            noMatch.textContent = '-- No common snapshot (full backup) --';
            dropdown.appendChild(noMatch);

            if (statusBadge) {
                statusBadge.style.display = 'inline-block';
                statusBadge.className = 'badge bg-warning';
                statusBadge.innerHTML = '<i class="bi bi-exclamation-triangle"></i> Full backup';
            }
        }

        // Add all source snapshots as fallback options
        if (result.all_source_snapshots) {
            result.all_source_snapshots.forEach(snap => {
                if (snap !== result.incremental_base) {
                    const option = document.createElement('option');
                    option.value = snap;
                    option.textContent = snap;
                    dropdown.appendChild(option);
                }
            });
        }
    } catch (error) {
        dropdown.innerHTML = '<option value="">-- Detection failed --</option>';
        if (statusBadge) {
            statusBadge.style.display = 'inline-block';
            statusBadge.className = 'badge bg-danger';
            statusBadge.innerHTML = '<i class="bi bi-x-circle"></i> Error';
        }
        console.warn(`Incremental detection failed for ${tabType}:`, error);
    }
}

/**
 * Initialize the backup page
 */
async function init() {
    console.log('Backup page initializing...');

    // Initialize connection indicator with callback to refresh tree on switch
    connectionIndicator.init(async () => {
        await loadTree();
        await updateConnectionInfo();
    });

    // Fetch connection info first
    await updateConnectionInfo();

    // Update connection indicator (includes Quick Switch menu)
    connectionIndicator.updateConnectionIndicator();

    // Load ZFS tree
    await loadTree();

    // Check for ?source= URL parameter (redirect from snapshot tab)
    const urlParams = new URLSearchParams(window.location.search);
    const sourceParam = urlParams.get('source');
    if (sourceParam && backupTree) {
        backupTree.selectByName(sourceParam);
        // Clean the URL to prevent re-selection on refresh
        history.replaceState(null, '', window.location.pathname);
    }

    // Setup form handlers
    setupFormHandlers();

    // Setup layout toggles (sidebar visibility)
    setupLayoutToggles();
}

/**
 * Setup layout toggles for sidebar visibility
 */
function setupLayoutToggles() {
    const mainTreePanel = document.getElementById('main-tree-panel');
    const mainBackupPanel = document.getElementById('main-backup-panel');
    const a2aTab = document.getElementById('a2a-tab');

    // Bootstrap tab event listener
    const tabEl = document.querySelectorAll('button[data-bs-toggle="tab"]');
    tabEl.forEach(tab => {
        tab.addEventListener('shown.bs.tab', (event) => {
            if (event.target.id === 'a2a-tab') {
                // Hide sidebar for Agent-to-Agent tab
                if (mainTreePanel) mainTreePanel.style.display = 'none';
                // Reset wrapper styles if needed
            } else {
                // Show sidebar for other tabs
                if (mainTreePanel) mainTreePanel.style.display = 'flex';
            }
        });
    });
}

/**
 * Fetch and update connection status (local vs remote agent)
 */
async function updateConnectionInfo() {
    try {
        const response = await fetch('/api/cc/list');
        if (!response.ok) return;

        const data = await response.json();
        if (!data.success) return;

        const isLocal = data.current_mode === 'local';
        const activeAlias = data.active_alias;

        // Find the active agent details if remote
        let activeAgent = null;
        if (!isLocal && activeAlias && data.connections) {
            activeAgent = data.connections.find(c => c.alias === activeAlias && c.active);
        }

        // Store connection info for source banner
        connectionInfo = {
            isLocal,
            activeAlias,
            activeAgent
        };

        // Update navbar indicator via shared module (includes Quick Switch menu)
        connectionIndicator.updateConnectionIndicator();

    } catch (error) {
        console.warn('Failed to fetch connection info:', error);
        connectionInfo = { isLocal: true, activeAlias: null, activeAgent: null };
    }
}

/**
 * Load ZFS datasets/snapshots into tree using BackupTreeView
 */
async function loadTree() {
    const treeContainer = document.getElementById('backup-tree');
    const loadingIndicator = document.getElementById('tree-loading');
    const searchInput = document.getElementById('backup-tree-search');
    const showDatasetsCheckbox = document.getElementById('backup-tree-show-datasets');

    // Create tree instance if not exists
    if (!backupTree) {
        backupTree = new BackupTreeView(treeContainer, {
            onSelect: handleTreeSelectionForAllTabs
        });

        // Wire up search input
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                backupTree.setFilter(e.target.value);
            });
        }

        // Wire up show datasets checkbox
        if (showDatasetsCheckbox) {
            showDatasetsCheckbox.addEventListener('change', (e) => {
                backupTree.setShowDatasets(e.target.checked);
            });
        }
    }

    try {
        const result = await apiCall('/api/data');
        const pools = result.data || [];

        // Store pools for incremental dropdown population (used by all tabs)
        allPools = pools;

        // Clear loading indicator
        if (loadingIndicator) loadingIndicator.style.display = 'none';

        // Render tree
        backupTree.render(pools);

    } catch (error) {
        console.error('Failed to load tree:', error);
        treeContainer.innerHTML = `
            <div class="text-center text-danger py-4">
                <i class="bi bi-exclamation-triangle display-4"></i>
                <p class="mt-2 mb-0 small">Failed to load datasets</p>
                <p class="small text-muted">${error.message}</p>
            </div>
        `;
    }
}

/**
 * Handle tree item selection (callback from BackupTreeView)
 */
function handleTreeSelection(item) {
    if (!item) return;

    selectedSource = { name: item.name, type: item.type };

    // Update UI
    const sourceText = document.getElementById('selected-source-text');
    const sourceAlert = document.getElementById('selected-source-alert');
    const originBadge = document.getElementById('source-origin-badge');
    const submitBtn = document.getElementById('start-backup-btn');

    sourceText.textContent = `${item.type}: ${item.name}`;
    sourceAlert.className = 'alert alert-primary mb-3';

    // Show origin badge
    if (originBadge && connectionInfo) {
        if (connectionInfo.isLocal) {
            originBadge.textContent = 'from Local Host';
            originBadge.className = 'ms-2 badge bg-success';
        } else if (connectionInfo.activeAgent) {
            originBadge.textContent = `from ${connectionInfo.activeAlias}`;
            originBadge.className = 'ms-2 badge bg-info';
        } else {
            originBadge.textContent = 'from Unknown';
            originBadge.className = 'ms-2 badge bg-warning';
        }
        originBadge.style.display = 'inline';
    }

    // Enable submit button
    submitBtn.disabled = false;

    // Auto-suggest destination dataset name
    const destDataset = document.getElementById('dest-dataset');
    if (!destDataset.value) {
        const baseName = item.name.split('@')[0];
        destDataset.value = baseName;
    }

    // Trigger incremental base detection if enabled
    triggerAgentIncrementalDetection();
}

/**
 * Setup form event handlers
 */
function setupFormHandlers() {
    const form = document.getElementById('backup-form');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await startBackup();
    });

    // Also setup the destination agent dropdown handler
    onAgentSelect('dest-agent', 'dest-port', 'dest-use-tls',
        'dest-password', 'dest-password-saved', 'dest-save-group');

    // Setup incremental checkbox toggle
    const incrementalCheck = document.getElementById('dest-incremental');
    const incrementalOptions = document.getElementById('dest-incremental-options');
    if (incrementalCheck && incrementalOptions) {
        incrementalCheck.addEventListener('change', (e) => {
            incrementalOptions.style.display = e.target.checked ? 'block' : 'none';
            if (e.target.checked) {
                triggerAgentIncrementalDetection();
            }
        });
    }

    // Reactive auto-detect on destination changes (debounced)
    const destAgent = document.getElementById('dest-agent');
    const destDataset = document.getElementById('dest-dataset');
    const destPassword = document.getElementById('dest-password');
    const destPort = document.getElementById('dest-port');

    [destAgent, destDataset, destPassword, destPort].forEach(el => {
        if (el) {
            el.addEventListener('change', triggerAgentIncrementalDetection);
            el.addEventListener('blur', triggerAgentIncrementalDetection);
        }
    });
}

/**
 * Trigger incremental base detection for Backup to Agent tab (debounced)
 */
function triggerAgentIncrementalDetection() {
    if (!document.getElementById('dest-incremental')?.checked) return;

    debounce('agent', () => {
        findIncrementalBaseFor({
            tabType: 'agent',
            dropdownId: 'dest-incremental-base',
            statusId: 'dest-incremental-status',
            getSourceDataset: () => selectedSource?.name?.split('@')[0],
            getDestConfig: () => {
                const destHost = document.getElementById('dest-agent')?.value?.trim();
                const destPort = parseInt(document.getElementById('dest-port')?.value || '5555');
                const destPassword = document.getElementById('dest-password')?.value;
                const destDataset = document.getElementById('dest-dataset')?.value?.trim();
                const useTls = document.getElementById('dest-use-tls')?.checked ?? true;

                if (!destHost || !destPassword || !destDataset) return null;

                return {
                    type: 'agent',
                    dataset: destDataset,
                    agent: { host: destHost, port: destPort, password: destPassword, use_tls: useTls }
                };
            }
        });
    });
}

/**
 * Trigger incremental base detection for Local Replication tab (debounced)
 */
function triggerLocalIncrementalDetection() {
    if (!document.getElementById('local-incremental')?.checked) return;

    debounce('local', () => {
        findIncrementalBaseFor({
            tabType: 'local',
            dropdownId: 'local-incremental-base',
            statusId: 'local-incremental-status',
            getSourceDataset: () => localSelectedSource?.name?.split('@')[0],
            getDestConfig: () => {
                const destDataset = document.getElementById('local-dest-dataset')?.value?.trim();
                if (!destDataset) return null;

                return {
                    type: 'local',
                    dataset: destDataset
                };
            }
        });
    });
}

/**
 * Trigger incremental base detection for SSH Backup tab (debounced)
 */
function triggerSSHIncrementalDetection() {
    if (!document.getElementById('ssh-incremental')?.checked) return;

    debounce('ssh', () => {
        findIncrementalBaseFor({
            tabType: 'ssh',
            dropdownId: 'ssh-incremental-base',
            statusId: 'ssh-incremental-status',
            getSourceDataset: () => sshSelectedSource?.name?.split('@')[0],
            getDestConfig: () => {
                const host = document.getElementById('ssh-host')?.value?.trim();
                const port = parseInt(document.getElementById('ssh-port')?.value || '22');
                const user = document.getElementById('ssh-user')?.value?.trim();
                const password = document.getElementById('ssh-password')?.value;
                const destDataset = document.getElementById('ssh-dest-dataset')?.value?.trim();

                if (!host || !user || !destDataset) return null;

                return {
                    type: 'ssh',
                    dataset: destDataset,
                    ssh: { host, port, user, password }
                };
            }
        });
    });
}

/**
 * Start backup operation
 */
async function startBackup() {
    if (!selectedSource) {
        alert('Please select a source dataset or snapshot');
        return;
    }

    const destSelect = document.getElementById('dest-agent');
    const destHost = destSelect ? destSelect.value.trim() : '';
    const destPort = parseInt(document.getElementById('dest-port').value, 10);
    const destPassword = document.getElementById('dest-password').value;
    const destDataset = document.getElementById('dest-dataset').value.trim();
    const useTls = document.getElementById('dest-use-tls').checked;

    // Validate
    if (!destHost || !destPassword || !destDataset) {
        alert('Please fill in all required fields');
        return;
    }

    // Show progress UI
    const progressCard = document.getElementById('backup-progress-card');
    const resultAlert = document.getElementById('backup-result-alert');
    const submitBtn = document.getElementById('start-backup-btn');

    progressCard.style.display = 'block';
    resultAlert.style.display = 'none';
    submitBtn.disabled = true;

    document.getElementById('backup-status-text').textContent = 'Connecting to destination agent...';

    // Save password to vault if checkbox checked
    const saveCheckbox = document.getElementById('dest-save-password');
    const selectedOption = destSelect?.options[destSelect.selectedIndex];
    const alias = selectedOption?.dataset?.alias;
    if (saveCheckbox?.checked && alias) {
        await vault.savePassword(alias, destPassword);
    }

    try {
        // Get incremental base if enabled
        const incrementalEnabled = document.getElementById('dest-incremental')?.checked;
        const incrementalBase = incrementalEnabled ?
            document.getElementById('dest-incremental-base')?.value || null : null;

        const result = await apiCall('/api/backup/send-to-agent', 'POST', {
            source_dataset: selectedSource.name,
            dest_host: destHost,
            dest_port: destPort,
            dest_password: destPassword,
            dest_dataset: destDataset,
            incremental_base: incrementalBase,
            use_tls: useTls
        });

        // Success
        progressCard.style.display = 'none';
        resultAlert.className = 'alert alert-success mt-3';
        resultAlert.style.display = 'block';

        const bytes = result.data?.bytes_transferred || 0;
        const bytesFormatted = formatBytes(bytes);
        resultAlert.innerHTML = `
            <i class="bi bi-check-circle me-2"></i>
            <strong>Backup completed!</strong> Transferred ${bytesFormatted} to ${destHost}
        `;

    } catch (error) {
        // Error
        progressCard.style.display = 'none';
        resultAlert.className = 'alert alert-danger mt-3';
        resultAlert.style.display = 'block';
        resultAlert.innerHTML = `
            <i class="bi bi-exclamation-triangle me-2"></i>
            <strong>Backup failed:</strong> ${error.message || error}
        `;
    } finally {
        submitBtn.disabled = false;
    }
}

/**
 * Format bytes to human readable
 */
function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// ============== Jobs Tab Functions ==============

let jobsRefreshInterval = null;

/**
 * Load and display backup jobs list
 */
async function loadJobsList() {
    const tbody = document.getElementById('jobs-tbody');
    const loadingRow = document.getElementById('jobs-loading-row');
    const emptyState = document.getElementById('jobs-empty-state');
    const countBadge = document.getElementById('jobs-count-badge');

    try {
        const result = await apiCall('/api/backup/jobs');
        const jobs = result.data || {};
        const jobsArray = Object.values(jobs);

        // Hide loading row
        if (loadingRow) loadingRow.style.display = 'none';

        if (jobsArray.length === 0) {
            // Show empty state
            tbody.innerHTML = '';
            emptyState.style.display = 'block';
            countBadge.style.display = 'none';
        } else {
            // Render jobs
            emptyState.style.display = 'none';
            renderJobs(tbody, jobsArray);

            // Update badge count (active jobs only)
            const activeJobs = jobsArray.filter(j =>
                !['complete', 'failed', 'cancelled'].includes(j.state)
            );
            if (activeJobs.length > 0) {
                countBadge.textContent = activeJobs.length;
                countBadge.style.display = 'inline';
            } else {
                countBadge.style.display = 'none';
            }
        }
    } catch (error) {
        console.error('Failed to load jobs:', error);
        if (loadingRow) loadingRow.style.display = 'none';
        tbody.innerHTML = `
            <tr>
                <td colspan="8" class="text-center text-danger py-4">
                    <i class="bi bi-exclamation-triangle me-2"></i>
                    Failed to load jobs: ${error.message}
                </td>
            </tr>
        `;
    }
}

/**
 * Render jobs into the table
 */
function renderJobs(tbody, jobs) {
    // Sort: active jobs first, then by created_at descending
    jobs.sort((a, b) => {
        const aActive = !['complete', 'failed', 'cancelled'].includes(a.state);
        const bActive = !['complete', 'failed', 'cancelled'].includes(b.state);
        if (aActive !== bActive) return bActive - aActive;
        return (b.created_at || 0) - (a.created_at || 0);
    });

    tbody.innerHTML = jobs.map(job => {
        const statusBadge = getStatusBadge(job.state, job.needs_token_fetch);
        const progress = job.progress_percent !== null
            ? `${Math.round(job.progress_percent)}%`
            : (job.bytes_transferred ? formatBytes(job.bytes_transferred) : '-');

        // Action buttons based on state
        let actions = '';
        if (job.state === 'failed' && job.direction === 'send') {
            if (job.needs_token_fetch) {
                // Needs manual token fetch first
                actions = `
                    <button class="btn btn-sm btn-outline-warning" 
                            onclick="fetchResumeToken('${job.job_id}', '${job.remote_host || ''}', ${job.remote_port || 5555})" 
                            title="Fetch Resume Token">
                        <i class="bi bi-arrow-down-circle"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-secondary" onclick="deleteJob('${job.job_id}')" title="Delete">
                        <i class="bi bi-trash"></i>
                    </button>
                `;
            } else if (job.has_resume_token) {
                // Has valid resume token - can resume
                actions = `
                    <button class="btn btn-sm btn-outline-primary" onclick="resumeJob('${job.job_id}')" title="Resume">
                        <i class="bi bi-play-fill"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-secondary" onclick="deleteJob('${job.job_id}')" title="Delete">
                        <i class="bi bi-trash"></i>
                    </button>
                `;
            } else {
                // Failed but no token available
                actions = `
                    <button class="btn btn-sm btn-outline-secondary" onclick="deleteJob('${job.job_id}')" title="Delete">
                        <i class="bi bi-trash"></i>
                    </button>
                `;
            }
        } else if (job.state === 'failed' && job.direction === 'receive') {
            // Receive jobs can't be resumed from here
            actions = `
                <span class="text-muted small" title="Resume from sender">
                    <i class="bi bi-info-circle"></i>
                </span>
                <button class="btn btn-sm btn-outline-secondary" onclick="deleteJob('${job.job_id}')" title="Delete">
                    <i class="bi bi-trash"></i>
                </button>
            `;
        } else if (['pending', 'connecting', 'streaming'].includes(job.state)) {
            actions = `
                <button class="btn btn-sm btn-outline-danger" onclick="cancelJob('${job.job_id}')" title="Cancel">
                    <i class="bi bi-x-lg"></i>
                </button>
            `;
        } else {
            actions = `
                <button class="btn btn-sm btn-outline-secondary" onclick="deleteJob('${job.job_id}')" title="Delete">
                    <i class="bi bi-trash"></i>
                </button>
            `;
        }

        const directionIcon = job.direction === 'send'
            ? '<i class="bi bi-cloud-upload text-primary"></i>'
            : '<i class="bi bi-cloud-download text-info"></i>';

        // Remote agent info
        const remoteAgent = job.remote_host
            ? `${job.remote_host}${job.remote_port ? ':' + job.remote_port : ''}`
            : '-';

        return `
            <tr data-job-id="${job.job_id}">
                <td><code>${job.job_id}</code></td>
                <td>${directionIcon} ${job.direction}</td>
                <td class="text-truncate" style="max-width: 150px;" title="${job.source_dataset}">${job.source_dataset}</td>
                <td class="text-truncate" style="max-width: 150px;" title="${job.dest_dataset}">${job.dest_dataset}</td>
                <td class="text-truncate" style="max-width: 120px;" title="${remoteAgent}">${remoteAgent}</td>
                <td>${statusBadge}</td>
                <td>${progress}</td>
                <td>${actions}</td>
            </tr>
        `;
    }).join('');
}

/**
 * Get Bootstrap badge for job status
 */
function getStatusBadge(state, needsTokenFetch = false) {
    // Special case: failed job needing token fetch
    if (state === 'failed' && needsTokenFetch) {
        return '<span class="badge bg-warning text-dark" title="Token fetch failed - click button to retry"><i class="bi bi-exclamation-triangle me-1"></i>Needs Token</span>';
    }

    const badges = {
        'pending': '<span class="badge bg-secondary">Pending</span>',
        'connecting': '<span class="badge bg-info">Connecting</span>',
        'streaming': '<span class="badge bg-primary"><span class="spinner-border spinner-border-sm me-1" style="width: 0.7em; height: 0.7em;"></span>Streaming</span>',
        'complete': '<span class="badge bg-success">Complete</span>',
        'failed': '<span class="badge bg-danger">Failed</span>',
        'cancelled': '<span class="badge bg-warning text-dark">Cancelled</span>'
    };
    return badges[state] || `<span class="badge bg-secondary">${state}</span>`;
}

/**
 * Cancel a running backup job
 */
async function cancelJob(jobId) {
    if (!confirm(`Cancel backup job ${jobId}?`)) return;

    try {
        await apiCall('/api/backup/cancel', 'POST', { job_id: jobId });
        await loadJobsList();
    } catch (error) {
        alert(`Failed to cancel job: ${error.message}`);
    }
}

/**
 * Delete a completed job from history
 */
async function deleteJob(jobId) {
    try {
        await apiCall('/api/backup/delete', 'POST', { job_id: jobId });
        await loadJobsList();
    } catch (error) {
        alert(`Failed to delete job: ${error.message}`);
    }
}

/**
 * Resume a failed backup job
 */
async function resumeJob(jobId) {
    // Prompt for destination password (required for resume)
    const password = prompt(`Enter destination agent password to resume job ${jobId}:`);
    if (!password) {
        return; // User cancelled
    }

    try {
        const result = await apiCall('/api/backup/resume', 'POST', {
            job_id: jobId,
            dest_password: password
        });

        alert(`Resume successful! Transferred ${formatBytes(result.data?.bytes_transferred || 0)}`);
        await loadJobsList();
    } catch (error) {
        alert(`Failed to resume job: ${error.message}`);
    }
}

/**
 * Fetch resume token for a failed job (when automatic fetch failed)
 */
async function fetchResumeToken(jobId, defaultHost, defaultPort) {
    // Need to collect connection details from user
    const host = prompt(`Enter destination host to fetch resume token:`, defaultHost || '');
    if (!host) return;

    const portStr = prompt(`Enter destination port:`, String(defaultPort || 5555));
    if (!portStr) return;
    const port = parseInt(portStr, 10);
    if (isNaN(port)) {
        alert('Invalid port number');
        return;
    }

    const password = prompt(`Enter destination agent password:`);
    if (!password) return;

    try {
        await apiCall('/api/backup/fetch-token', 'POST', {
            job_id: jobId,
            dest_host: host,
            dest_port: port,
            dest_password: password
        });

        alert(`Resume token fetched successfully! You can now resume the backup.`);
        await loadJobsList();
    } catch (error) {
        alert(`Failed to fetch token: ${error.message}`);
    }
}

/**
 * Setup jobs tab event handlers
 */
function setupJobsTab() {
    // Refresh button
    const refreshBtn = document.getElementById('refresh-jobs-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadJobsList);
    }

    // Clear completed button
    const clearBtn = document.getElementById('clear-completed-btn');
    if (clearBtn) {
        clearBtn.addEventListener('click', async () => {
            try {
                await apiCall('/api/backup/clear-completed', 'POST');
                await loadJobsList();
            } catch (error) {
                alert(`Failed to clear completed jobs: ${error.message}`);
            }
        });
    }

    // Auto-refresh when jobs tab is shown
    const jobsTab = document.getElementById('jobs-tab');
    if (jobsTab) {
        jobsTab.addEventListener('shown.bs.tab', () => {
            loadJobsList();
            // Start auto-refresh every 5 seconds
            jobsRefreshInterval = setInterval(loadJobsList, 5000);
        });
        jobsTab.addEventListener('hidden.bs.tab', () => {
            // Stop auto-refresh when leaving tab
            if (jobsRefreshInterval) {
                clearInterval(jobsRefreshInterval);
                jobsRefreshInterval = null;
            }
        });
    }
}

// ============== Agent-to-Agent Tab Functions ==============

let a2aSelectedSource = null;
let a2aAgentsList = [];

/**
 * Load available agents from control center
 */
async function loadAgentsList() {
    try {
        const response = await fetch('/api/cc/list');
        if (!response.ok) return;

        const data = await response.json();
        if (!data.success) return;

        a2aAgentsList = data.connections || [];
        populateAgentDropdowns();
    } catch (error) {
        console.warn('Failed to load agents list:', error);
    }
}

/**
 * Populate sender/receiver agent dropdowns (including dest-agent in To Agent tab)
 */
function populateAgentDropdowns() {
    const senderSelect = document.getElementById('a2a-sender-agent');
    const receiverSelect = document.getElementById('a2a-receiver-agent');
    const destSelect = document.getElementById('dest-agent');

    // Clear existing options (keep first placeholder)
    if (senderSelect) senderSelect.innerHTML = '<option value="">-- Select or enter host --</option>';
    if (receiverSelect) receiverSelect.innerHTML = '<option value="">-- Select or enter host --</option>';
    if (destSelect) destSelect.innerHTML = '<option value="">-- Select or enter host --</option>';

    // Add configured agents
    a2aAgentsList.forEach(agent => {
        const option = document.createElement('option');
        option.value = agent.host;
        option.dataset.port = agent.port;
        option.dataset.alias = agent.alias;
        option.dataset.tls = agent.use_tls;
        option.textContent = `${agent.alias} (${agent.host}:${agent.port})`;

        if (senderSelect) senderSelect.appendChild(option.cloneNode(true));
        if (receiverSelect) receiverSelect.appendChild(option.cloneNode(true));
        if (destSelect) destSelect.appendChild(option.cloneNode(true));
    });

    // Add manual entry option
    const manualOption = '<option value="__manual__">Enter manually...</option>';
    if (senderSelect) senderSelect.insertAdjacentHTML('beforeend', manualOption);
    if (receiverSelect) receiverSelect.insertAdjacentHTML('beforeend', manualOption);
    if (destSelect) destSelect.insertAdjacentHTML('beforeend', manualOption);
}

/**
 * Handle agent dropdown change - auto-fill port, TLS, and password from vault
 */
function onAgentSelect(selectId, portId, tlsId, passwordId, savedIndicatorId, saveGroupId) {
    const select = document.getElementById(selectId);
    const portInput = document.getElementById(portId);
    const tlsInput = document.getElementById(tlsId);
    const passwordInput = document.getElementById(passwordId);
    const savedIndicator = document.getElementById(savedIndicatorId);
    const saveGroup = document.getElementById(saveGroupId);

    if (!select) return;

    select.addEventListener('change', async () => {
        const selected = select.options[select.selectedIndex];

        // Always clear password and hide saved indicator when selection changes
        if (passwordInput) {
            passwordInput.value = '';
            passwordInput.dataset.fromVault = 'false';
        }
        if (savedIndicator) savedIndicator.style.display = 'none';
        if (saveGroup) saveGroup.style.display = 'block';

        if (selected.value === '__manual__') {
            // Let user type in host
            const host = prompt('Enter host address:');
            if (host) {
                select.value = '';
                select.insertAdjacentHTML('afterbegin', `<option value="${host}" selected>${host}</option>`);
            } else {
                select.value = '';
            }
            // Manual entries can't have saved passwords, so leave cleared
            return;
        }

        if (selected.dataset.port) {
            portInput.value = selected.dataset.port;
        }
        if (selected.dataset.tls !== undefined) {
            tlsInput.checked = selected.dataset.tls === 'true';
        }

        // Auto-fill password from vault if agent has alias
        const alias = selected.dataset.alias;
        if (alias && passwordInput) {
            const savedPassword = await vault.getPassword(alias);
            if (savedPassword) {
                passwordInput.value = savedPassword;
                passwordInput.dataset.fromVault = 'true';
                if (savedIndicator) savedIndicator.style.display = 'inline-block';
                // Keep save checkbox visible so user can update a changed password
            }
        }
    });
}

// Remote tree instance for A2A modal
let remoteTree = null;

/**
 * Load ZFS tree from sender agent into Modal using BackupTreeView
 */
async function loadRemoteTree() {
    const senderHost = document.getElementById('a2a-sender-agent').value;
    const senderPort = document.getElementById('a2a-sender-port').value;
    const senderPassword = document.getElementById('a2a-sender-password').value;
    const senderTls = document.getElementById('a2a-sender-tls').checked;

    // Modal elements
    const modalEl = document.getElementById('remoteTreeModal');
    const modal = new bootstrap.Modal(modalEl);
    const container = document.getElementById('remote-tree-container');
    const statusEl = document.getElementById('remote-tree-status');
    const selectBtn = document.getElementById('remote-tree-select-btn');
    const searchInput = document.getElementById('remote-tree-search');
    const showDatasetsCheckbox = document.getElementById('remote-tree-show-datasets');

    if (!senderHost) {
        alert('Please select or enter a sender agent host');
        return;
    }
    if (!senderPassword) {
        alert('Please enter the sender agent password');
        return;
    }

    // Show modal
    modal.show();
    selectBtn.disabled = true;
    statusEl.textContent = `Connecting to ${senderHost}...`;

    // Show loading in container
    container.innerHTML = `
        <div class="text-center py-5">
            <div class="spinner-border text-primary mb-3"></div>
            <p class="text-muted">Loading datasets from ${senderHost}...</p>
        </div>
    `;

    // Clear search and checkbox state
    if (searchInput) searchInput.value = '';
    if (showDatasetsCheckbox) showDatasetsCheckbox.checked = false;

    try {
        const result = await apiCall('/api/backup/agent-tree', 'POST', {
            host: senderHost,
            port: parseInt(senderPort),
            password: senderPassword,
            use_tls: senderTls
        });

        const pools = result.data || [];

        // Create tree instance for modal
        remoteTree = new BackupTreeView(container, {
            onSelect: (item) => {
                // Enable select button when item selected
                selectBtn.disabled = false;
            }
        });

        // Wire up search input
        if (searchInput) {
            searchInput.oninput = (e) => remoteTree.setFilter(e.target.value);
        }

        // Wire up show datasets checkbox
        if (showDatasetsCheckbox) {
            showDatasetsCheckbox.onchange = (e) => remoteTree.setShowDatasets(e.target.checked);
        }

        // Render tree
        remoteTree.render(pools);
        statusEl.textContent = 'Select a source dataset';

        // Setup select button handler
        selectBtn.onclick = () => {
            const selection = remoteTree.getSelection();
            if (selection) {
                applyRemoteSelection(selection);
                modal.hide();
            }
        };

    } catch (error) {
        container.innerHTML = `
            <div class="text-center py-5 text-danger">
                <i class="bi bi-exclamation-triangle display-4"></i>
                <p class="mt-3">Failed to load datasets</p>
                <code class="text-muted small">${error.message}</code>
            </div>
        `;
        statusEl.textContent = 'Error loading datasets';
    }
}

/**
 * Apply the selected remote item to the UI
 * @param {Object} item - Selected item {name, type}
 */
function applyRemoteSelection(item) {
    const name = item.name;
    const type = item.type;

    a2aSelectedSource = { name, type };

    // Update UI elements
    const displayEl = document.getElementById('a2a-source-display');
    const statusBadge = document.getElementById('a2a-status-badge');
    const startBtn = document.getElementById('a2a-start-backup-btn');

    // Update display
    displayEl.innerHTML = `
        <i class="bi bi-check-circle-fill text-success me-2"></i>
        <strong>${type}</strong>: ${name}
    `;
    displayEl.classList.remove('bg-light', 'text-muted');
    displayEl.classList.add('bg-white', 'text-primary', 'border-primary');

    // Update status badge
    if (statusBadge) {
        statusBadge.innerHTML = '<span class="badge bg-success">Selected</span>';
    }

    // Enable backup button if receiver is also selected (simplified check)
    startBtn.disabled = false;

    // Auto-fill destination
    const destInput = document.getElementById('a2a-dest-dataset');
    if (destInput && !destInput.value) {
        destInput.value = name.split('@')[0];
    }
}

/**
 * Start Agent-to-Agent backup
 */
async function startA2ABackup() {
    if (!a2aSelectedSource) {
        alert('Please select a source dataset or snapshot');
        return;
    }

    const senderHost = document.getElementById('a2a-sender-agent').value;
    const senderPort = parseInt(document.getElementById('a2a-sender-port').value);
    const senderPassword = document.getElementById('a2a-sender-password').value;
    const senderTls = document.getElementById('a2a-sender-tls').checked;

    const receiverHost = document.getElementById('a2a-receiver-agent').value;
    const receiverPort = parseInt(document.getElementById('a2a-receiver-port').value);
    const receiverPassword = document.getElementById('a2a-receiver-password').value;
    const receiverTls = document.getElementById('a2a-receiver-tls').checked;
    const destDataset = document.getElementById('a2a-dest-dataset').value.trim();

    // Validation
    if (!senderHost || !senderPassword) {
        alert('Please fill in sender agent details');
        return;
    }
    if (!receiverHost || !receiverPassword || !destDataset) {
        alert('Please fill in receiver agent details and destination dataset');
        return;
    }

    // Show progress
    const progressEl = document.getElementById('a2a-progress');
    const resultEl = document.getElementById('a2a-result');
    const startBtn = document.getElementById('a2a-start-backup-btn');

    progressEl.style.display = 'block';
    resultEl.style.display = 'none';
    startBtn.disabled = true;
    document.getElementById('a2a-progress-text').textContent = 'Connecting to sender agent...';

    // Save passwords to vault if checked (immediately on click)
    const senderSelect = document.getElementById('a2a-sender-agent');
    const receiverSelect = document.getElementById('a2a-receiver-agent');
    const senderAlias = senderSelect?.options[senderSelect.selectedIndex]?.dataset?.alias;
    const receiverAlias = receiverSelect?.options[receiverSelect.selectedIndex]?.dataset?.alias;

    const wantToSaveSender = document.getElementById('a2a-sender-save')?.checked && senderAlias;
    const wantToSaveReceiver = document.getElementById('a2a-receiver-save')?.checked && receiverAlias;

    if (wantToSaveSender || wantToSaveReceiver) {
        if (wantToSaveSender) {
            await vault.savePassword(senderAlias, senderPassword);
        }
        if (wantToSaveReceiver) {
            await vault.savePassword(receiverAlias, receiverPassword);
        }
    }

    try {
        // Get incremental base if enabled
        const a2aIncrementalEnabled = document.getElementById('a2a-incremental')?.checked;
        const a2aIncrementalBase = a2aIncrementalEnabled ?
            document.getElementById('a2a-incremental-base')?.value || null : null;

        const result = await apiCall('/api/backup/agent-to-agent', 'POST', {
            sender_host: senderHost,
            sender_port: senderPort,
            sender_password: senderPassword,
            sender_tls: senderTls,
            source_dataset: a2aSelectedSource.name,
            dest_host: receiverHost,
            dest_port: receiverPort,
            dest_password: receiverPassword,
            dest_tls: receiverTls,
            dest_dataset: destDataset,
            incremental_base: a2aIncrementalBase
        });

        // Success
        progressEl.style.display = 'none';
        resultEl.className = 'alert alert-success small py-2';
        resultEl.style.display = 'block';

        const bytes = result.data?.bytes_transferred || 0;
        resultEl.innerHTML = `
            <i class="bi bi-check-circle me-1"></i>
            <strong>Backup complete!</strong> Transferred ${formatBytes(bytes)}
        `;

    } catch (error) {
        progressEl.style.display = 'none';
        resultEl.className = 'alert alert-danger small py-2';
        resultEl.style.display = 'block';
        resultEl.innerHTML = `
            <i class="bi bi-exclamation-triangle me-1"></i>
            <strong>Backup failed:</strong> ${error.message}
        `;
    } finally {
        startBtn.disabled = false;
    }
}

/**
 * Setup Agent-to-Agent tab
 */
function setupA2ATab() {
    // Load agents list
    loadAgentsList();

    // Setup dropdown change handlers with password field IDs for vault integration
    onAgentSelect('a2a-sender-agent', 'a2a-sender-port', 'a2a-sender-tls',
        'a2a-sender-password', 'a2a-sender-saved', 'a2a-sender-save-group');
    onAgentSelect('a2a-receiver-agent', 'a2a-receiver-port', 'a2a-receiver-tls',
        'a2a-receiver-password', 'a2a-receiver-saved', 'a2a-receiver-save-group');

    // Load tree (Browse) button
    const browseBtn = document.getElementById('a2a-browse-btn');
    if (browseBtn) {
        browseBtn.addEventListener('click', loadRemoteTree);
    }

    // Start backup button
    const startBtn = document.getElementById('a2a-start-backup-btn');
    if (startBtn) {
        startBtn.addEventListener('click', startA2ABackup);
    }

    // Setup incremental checkbox toggle
    const a2aIncrementalCheck = document.getElementById('a2a-incremental');
    const a2aIncrementalOptions = document.getElementById('a2a-incremental-options');
    if (a2aIncrementalCheck && a2aIncrementalOptions) {
        a2aIncrementalCheck.addEventListener('change', (e) => {
            a2aIncrementalOptions.style.display = e.target.checked ? 'block' : 'none';
            if (e.target.checked) {
                findA2AIncrementalBase();
            }
        });
    }
}

/**
 * Find incremental base for A2A backup (both agents remote)
 */
async function findA2AIncrementalBase() {
    const dropdown = document.getElementById('a2a-incremental-base');
    if (!dropdown) return;

    // Get sender info
    const senderHost = document.getElementById('a2a-sender-agent')?.value?.trim();
    const senderPort = parseInt(document.getElementById('a2a-sender-port')?.value || '5555');
    const senderPassword = document.getElementById('a2a-sender-password')?.value;
    const senderTls = document.getElementById('a2a-sender-tls')?.checked ?? true;

    // Get receiver info
    const receiverHost = document.getElementById('a2a-receiver-agent')?.value?.trim();
    const receiverPort = parseInt(document.getElementById('a2a-receiver-port')?.value || '5555');
    const receiverPassword = document.getElementById('a2a-receiver-password')?.value;
    const receiverTls = document.getElementById('a2a-receiver-tls')?.checked ?? true;

    const sourceDataset = a2aSelectedSource?.name?.split('@')[0];
    const destDataset = document.getElementById('a2a-dest-dataset')?.value?.trim();

    if (!senderHost || !senderPassword || !receiverHost || !receiverPassword || !sourceDataset || !destDataset) {
        dropdown.innerHTML = '<option value="">-- Fill in all fields first --</option>';
        return;
    }

    dropdown.innerHTML = '<option value="">-- Checking... --</option>';

    try {
        const result = await apiCall('/api/backup/find-incremental-base', 'POST', {
            source_dataset: sourceDataset,
            source_agent: {
                host: senderHost,
                port: senderPort,
                password: senderPassword,
                use_tls: senderTls
            },
            dest_type: 'agent',
            dest_dataset: destDataset,
            dest_agent: {
                host: receiverHost,
                port: receiverPort,
                password: receiverPassword,
                use_tls: receiverTls
            }
        });

        dropdown.innerHTML = '';

        if (result.incremental_base) {
            const autoOption = document.createElement('option');
            autoOption.value = result.incremental_base;
            autoOption.textContent = `${result.incremental_base} (auto-detected)`;
            autoOption.selected = true;
            dropdown.appendChild(autoOption);
        } else {
            const noMatch = document.createElement('option');
            noMatch.value = '';
            noMatch.textContent = '-- No common snapshot (full backup) --';
            dropdown.appendChild(noMatch);
        }

        if (result.all_source_snapshots) {
            result.all_source_snapshots.forEach(snap => {
                if (snap !== result.incremental_base) {
                    const option = document.createElement('option');
                    option.value = snap;
                    option.textContent = snap;
                    dropdown.appendChild(option);
                }
            });
        }
    } catch (error) {
        dropdown.innerHTML = '<option value="">-- Detection failed --</option>';
        console.warn('A2A incremental detection failed:', error);
    }
}

// ============== Local Replication Tab Functions ==============

let localSourceTree = null;
let localDestTree = null;
let localSelectedSource = null;
let allPools = []; // Store pools for snapshot dropdown

/**
 * Setup Local Replication tab
 */
function setupLocalTab() {
    const sourceContainer = document.getElementById('local-source-tree');
    const destContainer = document.getElementById('local-dest-tree');
    const sourceSearch = document.getElementById('local-source-search');
    const destSearch = document.getElementById('local-dest-search');
    const sourceShowDatasets = document.getElementById('local-source-show-datasets');
    const destShowDatasets = document.getElementById('local-dest-show-datasets');
    const startBtn = document.getElementById('local-start-btn');
    const incrementalCheck = document.getElementById('local-incremental');
    const incrementalOptions = document.getElementById('local-incremental-options');

    // Create source tree
    localSourceTree = new BackupTreeView(sourceContainer, {
        onSelect: handleLocalSourceSelection
    });

    // Create destination tree
    localDestTree = new BackupTreeView(destContainer, {
        onSelect: handleLocalDestSelection,
        selectableTypes: ['pool', 'dataset'] // Only pools/datasets as destinations
    });

    // Wire up search inputs
    if (sourceSearch) {
        sourceSearch.addEventListener('input', (e) => localSourceTree.setFilter(e.target.value));
    }
    if (destSearch) {
        destSearch.addEventListener('input', (e) => localDestTree.setFilter(e.target.value));
    }

    // Wire up show datasets checkboxes
    if (sourceShowDatasets) {
        sourceShowDatasets.addEventListener('change', (e) => localSourceTree.setShowDatasets(e.target.checked));
    }
    if (destShowDatasets) {
        destShowDatasets.addEventListener('change', (e) => localDestTree.setShowDatasets(e.target.checked));
    }

    // Setup incremental checkbox toggle
    if (incrementalCheck) {
        incrementalCheck.addEventListener('change', (e) => {
            incrementalOptions.style.display = e.target.checked ? 'block' : 'none';
            if (e.target.checked) {
                triggerLocalIncrementalDetection();
            }
        });
    }

    // Reactive auto-detect on destination change
    const destDataset = document.getElementById('local-dest-dataset');
    if (destDataset) {
        destDataset.addEventListener('change', triggerLocalIncrementalDetection);
        destDataset.addEventListener('blur', triggerLocalIncrementalDetection);
    }

    // Start button handler
    if (startBtn) {
        startBtn.addEventListener('click', startLocalBackup);
    }

    // Tab shown handler - load trees when tab is shown
    const localTab = document.getElementById('local-tab');
    if (localTab) {
        localTab.addEventListener('shown.bs.tab', loadLocalTrees);
    }
}

/**
 * Load trees for local backup tab
 */
async function loadLocalTrees() {
    try {
        const result = await apiCall('/api/data');
        allPools = result.data || [];

        // Render both trees
        localSourceTree.render(allPools);
        localDestTree.render(allPools);
        localDestTree.setShowDatasets(true); // Show datasets by default for destination

    } catch (error) {
        console.error('Failed to load local trees:', error);
    }
}

/**
 * Handle local source selection
 */
function handleLocalSourceSelection(item) {
    localSelectedSource = { name: item.name, type: item.type };

    // Update UI
    const selectionEl = document.getElementById('local-source-selection');
    selectionEl.innerHTML = `<strong>${item.type}</strong>: ${item.name}`;

    // Enable start button if destination is also set
    updateLocalStartButton();

    // Trigger incremental base detection if enabled
    triggerLocalIncrementalDetection();
}

/**
 * Handle local destination selection
 */
function handleLocalDestSelection(item) {
    const destInput = document.getElementById('local-dest-dataset');
    destInput.value = item.name;
    updateLocalStartButton();

    // Trigger incremental base detection if enabled
    triggerLocalIncrementalDetection();
}

/**
 * Populate incremental base snapshot dropdown
 */
function populateIncrementalDropdown(dropdownId, selectedSnapshot) {
    const dropdown = document.getElementById(dropdownId);
    if (!dropdown) return;

    dropdown.innerHTML = '<option value="">-- Select base snapshot --</option>';

    // Get dataset name from selected snapshot
    const datasetName = selectedSnapshot.split('@')[0];

    // Find all snapshots for this dataset
    const snapshots = [];
    allPools.forEach(pool => {
        const findSnapshots = (node) => {
            // Check node's own snapshots array
            if (node.snapshots) {
                node.snapshots.forEach(s => {
                    // Get full snapshot name - try properties.full_snapshot_name first, 
                    // otherwise construct from dataset_name + @ + name
                    const fullName = s.properties?.full_snapshot_name ||
                        (s.dataset_name ? `${s.dataset_name}@${s.name}` : s.name);

                    if (fullName !== selectedSnapshot && fullName.startsWith(datasetName + '@')) {
                        if (!snapshots.includes(fullName)) {
                            snapshots.push(fullName);
                        }
                    }
                });
            }
            // Recurse into children
            if (node.children) {
                node.children.forEach(findSnapshots);
            }
        };
        findSnapshots(pool);
    });

    // Sort snapshots (newest first based on name - typically has timestamp)
    snapshots.sort().reverse();

    // Add to dropdown
    snapshots.forEach(snap => {
        const option = document.createElement('option');
        option.value = snap;
        option.textContent = snap;
        dropdown.appendChild(option);
    });
}

/**
 * Update local start button enabled state
 */
function updateLocalStartButton() {
    const startBtn = document.getElementById('local-start-btn');
    const destDataset = document.getElementById('local-dest-dataset').value.trim();
    startBtn.disabled = !localSelectedSource || !destDataset;
}

/**
 * Start local replication
 */
async function startLocalBackup() {
    if (!localSelectedSource) {
        alert('Please select a source snapshot');
        return;
    }

    const destDataset = document.getElementById('local-dest-dataset').value.trim();
    if (!destDataset) {
        alert('Please enter a destination dataset');
        return;
    }

    const incremental = document.getElementById('local-incremental').checked;
    const incrementalBase = incremental ? document.getElementById('local-incremental-base').value : null;
    const forceRollback = document.getElementById('local-force-rollback').checked;

    // Show progress
    const progressEl = document.getElementById('local-progress');
    const resultEl = document.getElementById('local-result');
    const startBtn = document.getElementById('local-start-btn');

    progressEl.style.display = 'block';
    resultEl.style.display = 'none';
    startBtn.disabled = true;
    document.getElementById('local-progress-text').textContent = 'Starting local replication...';

    try {
        const result = await apiCall('/api/backup/local', 'POST', {
            source_snapshot: localSelectedSource.name,
            dest_dataset: destDataset,
            incremental_base: incrementalBase,
            force_rollback: forceRollback
        });

        progressEl.style.display = 'none';
        resultEl.className = 'alert alert-success';
        resultEl.style.display = 'block';

        const bytes = result.data?.bytes_transferred || 0;
        resultEl.innerHTML = `
            <i class="bi bi-check-circle me-2"></i>
            <strong>Replication complete!</strong> Transferred ${formatBytes(bytes)}
        `;

    } catch (error) {
        progressEl.style.display = 'none';
        resultEl.className = 'alert alert-danger';
        resultEl.style.display = 'block';
        resultEl.innerHTML = `
            <i class="bi bi-exclamation-triangle me-2"></i>
            <strong>Replication failed:</strong> ${error.message}
        `;
    } finally {
        startBtn.disabled = false;
    }
}

// ============== Export to File Tab Functions ==============

let fileSelectedSource = null;

/**
 * Setup Export to File tab
 */
function setupFileTab() {
    const incrementalCheck = document.getElementById('file-incremental');
    const incrementalOptions = document.getElementById('file-incremental-options');
    const exportBtn = document.getElementById('file-export-btn');

    // Setup incremental checkbox toggle
    if (incrementalCheck) {
        incrementalCheck.addEventListener('change', (e) => {
            incrementalOptions.style.display = e.target.checked ? 'block' : 'none';
        });
    }

    // Export button handler
    if (exportBtn) {
        exportBtn.addEventListener('click', startFileExport);
    }

    // Update file source when main tree selection changes
    // (File tab uses the main left tree for source selection)
}

/**
 * Update file tab source display when tree selection changes
 */
function updateFileSource(item) {
    fileSelectedSource = item;

    const sourceText = document.getElementById('file-source-text');
    const sourceAlert = document.getElementById('file-source-alert');
    const exportBtn = document.getElementById('file-export-btn');

    if (item) {
        sourceText.innerHTML = `<strong>${item.type}</strong>: ${item.name}`;
        sourceAlert.className = 'alert alert-primary mb-4';

        // Populate incremental dropdown
        populateIncrementalDropdown('file-incremental-base', item.name);

        // Auto-suggest file path
        const filePathInput = document.getElementById('file-output-path');
        if (!filePathInput.value) {
            const baseName = item.name.replace('@', '-').replace(/\//g, '-');
            filePathInput.value = `/tmp/${baseName}.zfs`;
        }

        // Enable export button if path is also set
        updateFileExportButton();
    }
}

/**
 * Update file export button state
 */
function updateFileExportButton() {
    const exportBtn = document.getElementById('file-export-btn');
    const filePath = document.getElementById('file-output-path').value.trim();
    exportBtn.disabled = !fileSelectedSource || !filePath;
}

/**
 * Start file export
 */
async function startFileExport() {
    if (!fileSelectedSource) {
        alert('Please select a source snapshot from the tree');
        return;
    }

    const filePath = document.getElementById('file-output-path').value.trim();
    if (!filePath) {
        alert('Please enter an output file path');
        return;
    }

    const compression = document.getElementById('file-compression').value;
    const incremental = document.getElementById('file-incremental').checked;
    const incrementalBase = incremental ? document.getElementById('file-incremental-base').value : null;

    // Show progress
    const progressEl = document.getElementById('file-progress');
    const resultEl = document.getElementById('file-result');
    const exportBtn = document.getElementById('file-export-btn');

    progressEl.style.display = 'block';
    resultEl.style.display = 'none';
    exportBtn.disabled = true;
    document.getElementById('file-progress-text').textContent = 'Exporting snapshot to file...';

    try {
        const result = await apiCall('/api/backup/export-file', 'POST', {
            source_snapshot: fileSelectedSource.name,
            file_path: filePath,
            compression: compression,
            incremental_base: incrementalBase
        });

        progressEl.style.display = 'none';
        resultEl.className = 'alert alert-success';
        resultEl.style.display = 'block';

        const bytes = result.data?.bytes_written || 0;
        resultEl.innerHTML = `
            <i class="bi bi-check-circle me-2"></i>
            <strong>Export complete!</strong> Written ${formatBytes(bytes)} to ${filePath}
        `;

    } catch (error) {
        progressEl.style.display = 'none';
        resultEl.className = 'alert alert-danger';
        resultEl.style.display = 'block';
        resultEl.innerHTML = `
            <i class="bi bi-exclamation-triangle me-2"></i>
            <strong>Export failed:</strong> ${error.message}
        `;
    } finally {
        exportBtn.disabled = false;
    }
}

// ============== SSH Backup Tab Functions ==============

let sshSelectedSource = null;

/**
 * Setup SSH Backup tab
 */
function setupSSHTab() {
    const incrementalCheck = document.getElementById('ssh-incremental');
    const incrementalOptions = document.getElementById('ssh-incremental-options');
    const startBtn = document.getElementById('ssh-start-btn');

    // Setup incremental checkbox toggle
    if (incrementalCheck) {
        incrementalCheck.addEventListener('change', (e) => {
            incrementalOptions.style.display = e.target.checked ? 'block' : 'none';
            if (e.target.checked) {
                triggerSSHIncrementalDetection();
            }
        });
    }

    // Setup auth method toggle
    const authRadios = document.querySelectorAll('input[name="ssh-auth-method"]');
    authRadios.forEach(radio => {
        radio.addEventListener('change', updateSSHAuthFields);
    });

    // Start button handler
    if (startBtn) {
        startBtn.addEventListener('click', startSSHBackup);
    }

    // Add input event listeners to update button state and trigger detection
    ['ssh-host', 'ssh-user', 'ssh-password', 'ssh-dest-dataset', 'ssh-key-path'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', updateSSHStartButton);
            el.addEventListener('blur', triggerSSHIncrementalDetection);
            el.addEventListener('change', triggerSSHIncrementalDetection);
        }
    });
}

/**
 * Update SSH auth fields visibility based on selected method
 */
function updateSSHAuthFields() {
    const authMethod = document.querySelector('input[name="ssh-auth-method"]:checked')?.value || 'password';
    const passwordFields = document.getElementById('ssh-password-fields');
    const keyFields = document.getElementById('ssh-key-fields');

    // Toggle visibility based on auth method
    passwordFields.style.display = authMethod === 'password' ? 'block' : 'none';
    keyFields.style.display = authMethod === 'key' ? 'block' : 'none';

    updateSSHStartButton();
}

/**
 * Update SSH tab source display when tree selection changes
 */
function updateSSHSource(item) {
    sshSelectedSource = item;

    const sourceText = document.getElementById('ssh-source-text');
    const sourceAlert = document.getElementById('ssh-source-alert');

    if (item) {
        sourceText.innerHTML = `<strong>${item.type}</strong>: ${item.name}`;
        sourceAlert.className = 'alert alert-primary mb-4';

        // Auto-suggest destination
        const destInput = document.getElementById('ssh-dest-dataset');
        if (!destInput.value) {
            destInput.value = item.name.split('@')[0];
        }

        updateSSHStartButton();

        // Trigger incremental base detection if enabled
        triggerSSHIncrementalDetection();
    }
}

/**
 * Update SSH start button state
 */
function updateSSHStartButton() {
    const startBtn = document.getElementById('ssh-start-btn');
    const host = document.getElementById('ssh-host').value.trim();
    const user = document.getElementById('ssh-user').value.trim();
    const destDataset = document.getElementById('ssh-dest-dataset').value.trim();
    const authMethod = document.querySelector('input[name="ssh-auth-method"]:checked')?.value || 'auto';

    // Base validation
    let valid = sshSelectedSource && host && user && destDataset;

    // Password required only for password auth
    if (authMethod === 'password') {
        const password = document.getElementById('ssh-password').value;
        valid = valid && password;
    }

    startBtn.disabled = !valid;
}

/**
 * Start SSH backup
 */
async function startSSHBackup() {
    if (!sshSelectedSource) {
        alert('Please select a source snapshot from the tree');
        return;
    }

    const host = document.getElementById('ssh-host').value.trim();
    const port = parseInt(document.getElementById('ssh-port').value) || 22;
    const user = document.getElementById('ssh-user').value.trim();
    const destDataset = document.getElementById('ssh-dest-dataset').value.trim();
    const incremental = document.getElementById('ssh-incremental').checked;
    const incrementalBase = incremental ? document.getElementById('ssh-incremental-base').value : null;
    const forceRollback = document.getElementById('ssh-force-rollback').checked;

    // Auth method and related fields
    const authMethod = document.querySelector('input[name="ssh-auth-method"]:checked')?.value || 'auto';
    const password = document.getElementById('ssh-password').value;
    const keyPath = document.getElementById('ssh-key-path')?.value?.trim() || null;
    const keyPassphrase = document.getElementById('ssh-key-passphrase')?.value || null;

    // Validate based on auth method
    if (!host || !user || !destDataset) {
        alert('Please fill in all SSH connection fields');
        return;
    }
    if (authMethod === 'password' && !password) {
        alert('Password is required for password authentication');
        return;
    }

    // Show progress
    const progressEl = document.getElementById('ssh-progress');
    const resultEl = document.getElementById('ssh-result');
    const startBtn = document.getElementById('ssh-start-btn');

    progressEl.style.display = 'block';
    resultEl.style.display = 'none';
    startBtn.disabled = true;
    document.getElementById('ssh-progress-text').textContent = `Connecting to ${user}@${host}...`;

    try {
        const result = await apiCall('/api/backup/send-ssh', 'POST', {
            source_snapshot: sshSelectedSource.name,
            ssh_host: host,
            ssh_port: port,
            ssh_user: user,
            dest_dataset: destDataset,
            auth_method: authMethod,
            ssh_password: authMethod === 'password' ? password : null,
            ssh_key_path: authMethod === 'key' ? keyPath : null,
            ssh_key_passphrase: authMethod === 'key' ? keyPassphrase : null,
            incremental_base: incrementalBase,
            force_rollback: forceRollback
        });

        progressEl.style.display = 'none';
        resultEl.className = 'alert alert-success';
        resultEl.style.display = 'block';

        const bytes = result.data?.bytes_transferred || 0;
        resultEl.innerHTML = `
            <i class="bi bi-check-circle me-2"></i>
            <strong>SSH backup complete!</strong> Transferred ${formatBytes(bytes)} to ${host}
        `;

    } catch (error) {
        progressEl.style.display = 'none';
        resultEl.className = 'alert alert-danger';
        resultEl.style.display = 'block';
        resultEl.innerHTML = `
            <i class="bi bi-exclamation-triangle me-2"></i>
            <strong>SSH backup failed:</strong> ${error.message}
        `;
    } finally {
        startBtn.disabled = false;
    }
}

/**
 * Extended tree selection handler - updates all tabs that use the main tree
 */
function handleTreeSelectionForAllTabs(item) {
    // Original handler for Agent tab
    handleTreeSelection(item);

    // Update File tab
    updateFileSource(item);

    // Update SSH tab
    updateSSHSource(item);
}

// Make functions available globally for onclick handlers
window.cancelJob = cancelJob;
window.deleteJob = deleteJob;
window.resumeJob = resumeJob;
window.fetchResumeToken = fetchResumeToken;

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    init();
    setupJobsTab();
    setupA2ATab();
    setupLocalTab();
    setupFileTab();
    setupSSHTab();

    // Listen for file path input changes
    const filePathInput = document.getElementById('file-output-path');
    if (filePathInput) {
        filePathInput.addEventListener('input', updateFileExportButton);
    }

    // Listen for local dest input changes
    const localDestInput = document.getElementById('local-dest-dataset');
    if (localDestInput) {
        localDestInput.addEventListener('input', updateLocalStartButton);
    }
});

