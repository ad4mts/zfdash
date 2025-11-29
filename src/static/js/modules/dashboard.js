/**
 * dashboard.js - Dashboard Rendering Module
 * 
 * Handles rendering of the dashboard tab with overview information.
 */

import { formatSize, createInfoRow, countDatasetsInPool, countSnapshotsInPool } from './utils.js';

/**
 * Render dashboard content for a selected object
 * @param {object|null} obj - Selected ZFS object or null to clear
 */
export function renderDashboard(obj) {
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

/**
 * Render storage progress bar
 * @param {string} prefix - Element ID prefix ('primary' or 'secondary')
 * @param {number} used - Used bytes
 * @param {number} total - Total bytes
 * @param {string} label - Bar label
 */
export function renderStorageBar(prefix, used, total, label) {
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

/**
 * Clear storage bar to default state
 * @param {string} prefix - Element ID prefix
 */
export function clearStorageBar(prefix) {
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

/**
 * Render pool dashboard info cards
 * @param {object} pool - Pool object
 * @param {HTMLElement} generalInfo - General info container
 * @param {HTMLElement} configInfo - Config info container
 * @param {HTMLElement} statsInfo - Stats info container
 */
function renderPoolDashboardInfo(pool, generalInfo, configInfo, statsInfo) {
    const props = pool.properties || {};
    const health = (pool.health || 'UNKNOWN').toUpperCase();
    const healthClass = health === 'ONLINE' ? 'success' : (health === 'DEGRADED' ? 'warning' : 'danger');

    if (generalInfo) {
        generalInfo.innerHTML = 
            createInfoRow('Name:', pool.name) +
            createInfoRow('Health:', health, healthClass) +
            createInfoRow('GUID:', pool.guid || '-') +
            createInfoRow('Version:', props.version || '-') +
            createInfoRow('Altroot:', props.altroot || '-');
    }

    if (configInfo) {
        configInfo.innerHTML = 
            createInfoRow('Deduplication:', pool.dedup || 'off') +
            createInfoRow('Fragmentation:', pool.frag || '-') +
            createInfoRow('Capacity:', pool.cap || '-') +
            createInfoRow('Autotrim:', props.autotrim || '-') +
            createInfoRow('Autoexpand:', props.autoexpand || '-') +
            createInfoRow('Failmode:', props.failmode || '-');
    }

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

/**
 * Render dataset dashboard info cards
 * @param {object} dataset - Dataset object
 * @param {HTMLElement} generalInfo - General info container
 * @param {HTMLElement} configInfo - Config info container
 * @param {HTMLElement} statsInfo - Stats info container
 */
function renderDatasetDashboardInfo(dataset, generalInfo, configInfo, statsInfo) {
    const props = dataset.properties || {};

    if (generalInfo) {
        generalInfo.innerHTML = 
            createInfoRow('Name:', dataset.name) +
            createInfoRow('Pool:', dataset.pool_name || '-') +
            createInfoRow('Type:', (dataset.obj_type || 'dataset').charAt(0).toUpperCase() + (dataset.obj_type || 'dataset').slice(1)) +
            createInfoRow('Mountpoint:', dataset.mountpoint || '-') +
            createInfoRow('Mounted:', dataset.is_mounted ? 'Yes' : 'No', dataset.is_mounted ? 'success' : 'muted');
    }

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

/**
 * Render snapshot dashboard info cards
 * @param {object} snapshot - Snapshot object
 * @param {HTMLElement} generalInfo - General info container
 * @param {HTMLElement} configInfo - Config info container
 * @param {HTMLElement} statsInfo - Stats info container
 */
function renderSnapshotDashboardInfo(snapshot, generalInfo, configInfo, statsInfo) {
    const props = snapshot.properties || {};

    const snapName = snapshot.name.includes('@') ? snapshot.name.split('@')[1] : snapshot.name;
    const parentDs = snapshot.name.includes('@') ? snapshot.name.split('@')[0] : '-';

    if (generalInfo) {
        generalInfo.innerHTML = 
            createInfoRow('Snapshot:', snapName) +
            createInfoRow('Dataset:', parentDs) +
            createInfoRow('Pool:', snapshot.pool_name || '-') +
            createInfoRow('Created:', snapshot.creation_time || '-');
    }

    if (configInfo) {
        configInfo.innerHTML = 
            createInfoRow('Clones:', props.clones || '-') +
            createInfoRow('Defer Destroy:', props.defer_destroy || '-') +
            createInfoRow('Hold Tags:', props.userrefs || '-');
    }

    if (statsInfo) {
        statsInfo.innerHTML = 
            createInfoRow('Used:', formatSize(snapshot.used)) +
            createInfoRow('Referenced:', formatSize(snapshot.referenced));
    }
}

/**
 * Render system info card
 * @param {HTMLElement} systemInfo - System info container
 * @param {object|null} obj - Selected object for context
 */
function renderSystemInfo(systemInfo, obj = null) {
    if (!systemInfo) return;

    let html = createInfoRow('Application:', 'ZfDash Web UI');

    if (obj && obj.obj_type === 'pool' && obj.properties) {
        const zfsVersion = obj.properties.version;
        if (zfsVersion && zfsVersion !== '-') {
            html += createInfoRow('ZFS Version:', zfsVersion);
        }
    }

    systemInfo.innerHTML = html;
}
