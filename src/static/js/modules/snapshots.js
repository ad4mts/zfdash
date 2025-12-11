/**
 * snapshots.js - Snapshot Management Module
 * 
 * Handles snapshot rendering and actions.
 */

import { formatSize } from './utils.js';
import { executeActionWithRefresh } from './api.js';
import * as state from './state.js';
import dom from './dom-elements.js';
import { showConfirmModal, showInputModal } from './ui.js';
import { showError, showWarning } from './notifications.js';

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
export async function handleCreateSnapshot() {
    if (!state.currentSelection) return;

    const datasetName = state.currentSelection.name;
    const snapName = await showInputModal(
        "Create Snapshot",
        `Enter snapshot name for:<br><strong>${datasetName}</strong><br><small class="text-muted">Result: ${datasetName}@&lt;name&gt;</small>`,
        "",
        "snapshot-name",
        "Create", "btn-primary"
    );

    if (snapName === null) return;

    const namePart = snapName.trim();
    if (!namePart) {
        showError("Snapshot name cannot be empty.");
        return;
    }
    if (/[@\/ ]/.test(namePart)) {
        showError("Snapshot name cannot contain '@', '/', or spaces.");
        return;
    }
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_\-:.%]*$/.test(namePart)) {
        showError("Snapshot name contains invalid characters.");
        return;
    }

    let recursive = false;
    if (state.currentSelection.children && state.currentSelection.children.some(c => c.obj_type === 'dataset' || c.obj_type === 'volume')) {
        recursive = await showConfirmModal(
            "Recursive Snapshot",
            `Create snapshots <strong>recursively</strong> for all child datasets/volumes under <strong>${datasetName}</strong>?`,
            "Yes, Recursive", "btn-info"
        );
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
        showWarning("Please select a snapshot from the table first.");
        return;
    }

    executeActionWithRefresh(
        'destroy_snapshot',
        [selectedSnapFullName],
        {},
        `Snapshot '${selectedSnapFullName}' deletion initiated.`,
        true,
        `Are you sure you want to permanently delete snapshot:<br><strong>${selectedSnapFullName}</strong>?`
    );
}

/**
 * Handle rollback snapshot action
 */
export function handleRollbackSnapshot() {
    const selectedSnapFullName = dom.snapshotsTableBody?.dataset.selectedSnapshot;
    if (!selectedSnapFullName) {
        showWarning("Please select a snapshot from the table first.");
        return;
    }

    const datasetName = selectedSnapFullName.split('@')[0];

    executeActionWithRefresh(
        'rollback_snapshot',
        [selectedSnapFullName],
        {},
        `Rollback to '${selectedSnapFullName}' initiated.`,
        true,
        `<span class="text-danger"><strong>DANGER ZONE!</strong></span><br><br>Rolling back dataset '<strong>${datasetName}</strong>' to snapshot:<br><strong>${selectedSnapFullName}</strong><br><br>This will <strong>DESTROY ALL CHANGES</strong> made since the snapshot.<br><strong>THIS CANNOT BE UNDONE.</strong><br><br>Proceed?`
    );
}

/**
 * Handle clone snapshot action
 */
export async function handleCloneSnapshot() {
    const selectedSnapFullName = dom.snapshotsTableBody?.dataset.selectedSnapshot;
    if (!selectedSnapFullName) {
        showWarning("Please select a snapshot from the table first.");
        return;
    }

    const sourceDatasetName = selectedSnapFullName.split('@')[0];
    const poolName = sourceDatasetName.split('/')[0];
    // Default: poolname/clone or poolname/nested/path_clone
    const defaultTarget = sourceDatasetName.includes('/')
        ? `${sourceDatasetName}_clone`
        : `${sourceDatasetName}/clone`;

    const targetName = await showInputModal(
        "Clone Snapshot",
        `Enter the <strong>full path</strong> for the new dataset/volume cloned from:<br><strong>${selectedSnapFullName}</strong>`,
        defaultTarget,
        "pool/path/to/clone",
        "Clone", "btn-primary"
    );
    if (targetName === null) return;

    const targetPath = targetName.trim();
    if (!targetPath || targetPath.includes(' ') || targetPath.endsWith('/')) {
        showError(`Invalid target path. Cannot be empty, contain spaces, or end with '/'.`);
        return;
    }
    // Must contain a '/' and start with the same pool name
    if (!targetPath.includes('/')) {
        showError(`Target must include a path (e.g., '${poolName}/myname').`);
        return;
    }
    const targetPoolName = targetPath.split('/')[0];
    if (targetPoolName !== poolName) {
        showError(`Target must be in the same pool '${poolName}'.`);
        return;
    }
    if (targetPath === sourceDatasetName) {
        showError("Target cannot be the same as the source.");
        return;
    }
    if (!/^[a-zA-Z0-9]/.test(targetPath.split('/').pop())) {
        showError("Final component of target name must start with letter/number.");
        return;
    }
    if (/[^a-zA-Z0-9_\-:.%/]/.test(targetPath)) {
        showError("Target path contains invalid characters.");
        return;
    }

    executeActionWithRefresh(
        'clone_snapshot',
        [selectedSnapFullName, targetPath, {}],
        {},
        `Cloning '${selectedSnapFullName}' to '${targetPath}' initiated.`
    );
}
