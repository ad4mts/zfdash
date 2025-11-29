/**
 * snapshots.js - Snapshot Management Module
 * 
 * Handles snapshot rendering and actions.
 */

import { formatSize } from './utils.js';
import { executeActionWithRefresh } from './api.js';
import * as state from './state.js';
import dom from './dom-elements.js';

/**
 * Render snapshots table
 * @param {Array} snapshots - Array of snapshot objects
 */
export function renderSnapshots(snapshots) {
    if (!dom.snapshotsTableBody) return;
    
    dom.snapshotsTableBody.innerHTML = '';
    
    // Reset button state
    document.getElementById('delete-snapshot-button').disabled = true;
    document.getElementById('rollback-snapshot-button').disabled = true;
    document.getElementById('clone-snapshot-button').disabled = true;
    dom.snapshotsTableBody.dataset.selectedSnapshot = "";

    if (!snapshots || snapshots.length === 0) {
        dom.snapshotsTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">No snapshots available.</td></tr>`;
        return;
    }

    // Sort by creation time
    snapshots.sort((a, b) => (a.properties?.creation || '').localeCompare(b.properties?.creation || ''));

    snapshots.forEach(snap => {
        const fullSnapName = snap.properties?.full_snapshot_name || `${snap.dataset_name}@${snap.name}`;
        const row = dom.snapshotsTableBody.insertRow();
        row.innerHTML = `
            <td><span title="${fullSnapName}">@${snap.name}</span></td>
            <td class="text-end">${formatSize(snap.used)}</td>
            <td class="text-end">${formatSize(snap.referenced)}</td>
            <td>${snap.creation_time || snap.properties?.creation || '-'}</td>
        `;
        
        row.style.cursor = 'pointer';
        row.onclick = () => {
            // Remove selected class from other rows
            dom.snapshotsTableBody.querySelectorAll('tr.table-active').forEach(r => r.classList.remove('table-active'));
            row.classList.add('table-active');
            
            // Enable action buttons
            document.getElementById('delete-snapshot-button').disabled = false;
            document.getElementById('rollback-snapshot-button').disabled = false;
            document.getElementById('clone-snapshot-button').disabled = false;
            
            // Store selected snapshot name
            dom.snapshotsTableBody.dataset.selectedSnapshot = fullSnapName;
        };
    });
}

/**
 * Handle create snapshot action
 */
export function handleCreateSnapshot() {
    if (!state.currentSelection) return;
    
    const datasetName = state.currentSelection.name;
    const snapName = prompt(`Enter snapshot name for:\n${datasetName}\n(Result: ${datasetName}@<name>)`, "");
    
    if (snapName === null) return;
    
    const namePart = snapName.trim();
    if (!namePart) {
        alert("Snapshot name cannot be empty.");
        return;
    }
    if (/[@\/ ]/.test(namePart)) {
        alert("Snapshot name cannot contain '@', '/', or spaces.");
        return;
    }
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_\-:.%]*$/.test(namePart)) {
        alert("Snapshot name contains invalid characters.");
        return;
    }

    let recursive = false;
    if (state.currentSelection.children && state.currentSelection.children.some(c => c.obj_type === 'dataset' || c.obj_type === 'volume')) {
        recursive = confirm(`Create snapshots recursively for all child datasets/volumes under ${datasetName}?`);
    }

    executeActionWithRefresh(
        'create_snapshot',
        [datasetName, namePart, recursive],
        {},
        `Snapshot '${datasetName}@${namePart}' creation initiated.`
    );
}

/**
 * Handle delete snapshot action
 */
export function handleDeleteSnapshot() {
    const selectedSnapFullName = dom.snapshotsTableBody?.dataset.selectedSnapshot;
    if (!selectedSnapFullName) {
        alert("Please select a snapshot from the table first.");
        return;
    }
    
    executeActionWithRefresh(
        'destroy_snapshot',
        [selectedSnapFullName],
        {},
        `Snapshot '${selectedSnapFullName}' deletion initiated.`,
        true,
        `Are you sure you want to permanently delete snapshot:\n${selectedSnapFullName}?`
    );
}

/**
 * Handle rollback snapshot action
 */
export function handleRollbackSnapshot() {
    const selectedSnapFullName = dom.snapshotsTableBody?.dataset.selectedSnapshot;
    if (!selectedSnapFullName) {
        alert("Please select a snapshot from the table first.");
        return;
    }
    
    const datasetName = selectedSnapFullName.split('@')[0];
    
    executeActionWithRefresh(
        'rollback_snapshot',
        [selectedSnapFullName],
        {},
        `Rollback to '${selectedSnapFullName}' initiated.`,
        true,
        `DANGER ZONE!\n\nRolling back dataset '${datasetName}' to snapshot:\n${selectedSnapFullName}\n\nThis will DESTROY ALL CHANGES made since the snapshot.\nTHIS CANNOT BE UNDONE.\n\nProceed?`
    );
}

/**
 * Handle clone snapshot action
 */
export function handleCloneSnapshot() {
    const selectedSnapFullName = dom.snapshotsTableBody?.dataset.selectedSnapshot;
    if (!selectedSnapFullName) {
        alert("Please select a snapshot from the table first.");
        return;
    }
    
    const sourceDatasetName = selectedSnapFullName.split('@')[0];
    const poolName = sourceDatasetName.split('/')[0];
    const defaultTarget = `${sourceDatasetName}-clone`;

    const targetName = prompt(`Enter the FULL PATH for the new dataset/volume cloned from:\n${selectedSnapFullName}`, defaultTarget);
    if (targetName === null) return;
    
    const targetPath = targetName.trim();
    if (!targetPath || targetPath.includes(' ') || !targetPath.includes('/') || targetPath.endsWith('/')) {
        alert(`Invalid target path. Must be like '${poolName}/myclone'.`);
        return;
    }
    if (targetPath === sourceDatasetName) {
        alert("Target cannot be the same as the source.");
        return;
    }
    if (!/^[a-zA-Z0-9]/.test(targetPath.split('/').pop())) {
        alert("Final component of target name must start with letter/number.");
        return;
    }
    if (/[^a-zA-Z0-9_\-:.%/]/.test(targetPath)) {
        alert("Target path contains invalid characters.");
        return;
    }

    executeActionWithRefresh(
        'clone_snapshot',
        [selectedSnapFullName, targetPath, {}],
        {},
        `Cloning '${selectedSnapFullName}' to '${targetPath}' initiated.`
    );
}
