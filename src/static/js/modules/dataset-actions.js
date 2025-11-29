/**
 * dataset-actions.js - Dataset Action Handlers Module
 * 
 * Handles dataset creation, destruction, mounting, and other dataset-level actions.
 */

import * as state from './state.js';
import { executeActionWithRefresh } from './api.js';
import { showModal, hideModal, showErrorAlert } from './ui.js';
import { validateSizeOrNone } from './utils.js';

/**
 * Handle create dataset action
 */
export function handleCreateDataset() {
    if (!state.currentSelection || !['pool', 'dataset', 'volume'].includes(state.currentSelection.obj_type)) {
        console.error("handleCreateDataset called without valid selection:", state.currentSelection);
        alert("Please select a pool or dataset first.");
        return;
    }
    const parentName = state.currentSelection.name;

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
                                    <option value="inherit" selected>inherit</option>
                                    <option value="off">off</option>
                                    <option value="on">on</option>
                                    <option value="lz4">lz4</option>
                                    <option value="gzip">gzip</option>
                                    <option value="gzip-9">gzip-9</option>
                                    <option value="zstd">zstd</option>
                                    <option value="zle">zle</option>
                                </select>
                            </div>
                        </div>
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
                                        <option value="aes-256-gcm">aes-256-gcm</option>
                                        <option value="aes-192-gcm">aes-192-gcm</option>
                                        <option value="aes-128-gcm">aes-128-gcm</option>
                                        <option value="aes-256-ccm">aes-256-ccm</option>
                                        <option value="aes-192-ccm">aes-192-ccm</option>
                                        <option value="aes-128-ccm">aes-128-ccm</option>
                                    </select>
                                </div>
                            </div>
                            <div class="row mb-2">
                                <label for="create-ds-enc-format" class="col-sm-4 col-form-label col-form-label-sm">Key Format:</label>
                                <div class="col-sm-8">
                                    <select id="create-ds-enc-format" class="form-select form-select-sm">
                                        <option value="passphrase" selected>Passphrase</option>
                                        <option value="hex">Hex Key File</option>
                                        <option value="raw">Raw Key File</option>
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
        </div>
    `;

    showModal('Create Dataset/Volume', modalHtml, handleCreateDatasetConfirm, { setupFunc: setupCreateDatasetModal });
}

/**
 * Setup create dataset modal
 */
export function setupCreateDatasetModal() {
    const typeSelect = document.getElementById('create-ds-type');
    const volSizeGroup = document.getElementById('create-ds-volsize-group');
    typeSelect.onchange = () => {
        volSizeGroup.style.display = typeSelect.value === 'volume' ? 'block' : 'none';
    };

    const encEnableCheck = document.getElementById('create-ds-enc-enable');
    const encOptionsDiv = document.getElementById('create-ds-enc-options');
    const encFormatSelect = document.getElementById('create-ds-enc-format');
    const passphraseGroup = document.getElementById('create-ds-enc-passphrase-group');
    const keylocGroup = document.getElementById('create-ds-enc-keyloc-group');

    encEnableCheck.onchange = () => {
        encOptionsDiv.style.display = encEnableCheck.checked ? 'block' : 'none';
        if (encEnableCheck.checked) {
            const event = new Event('change');
            encFormatSelect.dispatchEvent(event);
        }
    };
    encFormatSelect.onchange = () => {
        const isPass = encFormatSelect.value === 'passphrase';
        passphraseGroup.style.display = isPass ? 'flex' : 'none';
        keylocGroup.style.display = isPass ? 'none' : 'flex';
    };
    
    // Initial state
    encOptionsDiv.style.display = encEnableCheck.checked ? 'block' : 'none';
    const isPassInitial = encFormatSelect.value === 'passphrase';
    passphraseGroup.style.display = (encEnableCheck.checked && isPassInitial) ? 'flex' : 'none';
    keylocGroup.style.display = (encEnableCheck.checked && !isPassInitial) ? 'flex' : 'none';
}

/**
 * Handle create dataset confirmation
 */
function handleCreateDatasetConfirm() {
    const parentName = document.getElementById('create-ds-parent').value;
    const namePart = document.getElementById('create-ds-name').value.trim();
    const dsType = document.getElementById('create-ds-type').value;
    const isVolume = dsType === 'volume';
    const volSize = document.getElementById('create-ds-volsize').value.trim();

    if (!namePart || namePart.includes(' ') || namePart.includes('/') || namePart.includes('@')) {
        alert("Invalid dataset/volume name part.");
        return;
    }
    if (!/^[a-zA-Z0-9]/.test(namePart)) {
        alert("Name part must start with letter/number.");
        return;
    }
    if (/[^a-zA-Z0-9_\-:.%]/.test(namePart)) {
        alert("Name part contains invalid characters.");
        return;
    }

    if (isVolume && !volSize) {
        alert("Volume Size is required for volumes.");
        return;
    }
    if (isVolume && !validateSizeOrNone(volSize)) {
        alert("Invalid volume size format.");
        return;
    }

    const fullDsName = `${parentName}/${namePart}`;
    const options = {};
    let encPassphrase = null;

    // Collect optional props
    const mountpoint = document.getElementById('create-ds-mountpoint').value.trim();
    if (mountpoint && mountpoint.toLowerCase() !== 'inherit') options.mountpoint = mountpoint;
    const quota = document.getElementById('create-ds-quota').value.trim();
    if (quota && quota.toLowerCase() !== 'none') {
        if (!validateSizeOrNone(quota)) {
            alert("Invalid Quota format.");
            return;
        }
        options.quota = quota;
    }
    const compression = document.getElementById('create-ds-compression').value;
    if (compression !== 'inherit') options.compression = compression;

    // Collect encryption options
    if (document.getElementById('create-ds-enc-enable').checked) {
        options.encryption = document.getElementById('create-ds-enc-alg').value;
        options.keyformat = document.getElementById('create-ds-enc-format').value;
        if (options.keyformat === 'passphrase') {
            const pass1 = document.getElementById('create-ds-enc-pass').value;
            const pass2 = document.getElementById('create-ds-enc-confirm').value;
            if (!pass1) {
                alert("Passphrase cannot be empty when encryption is enabled.");
                return;
            }
            if (pass1 !== pass2) {
                alert("Passphrases do not match.");
                return;
            }
            encPassphrase = pass1;
        } else {
            const keyloc = document.getElementById('create-ds-enc-keyloc').value.trim();
            if (!keyloc || !keyloc.startsWith('file:///')) {
                alert("Key Location (file URI) is required for hex/raw format.");
                return;
            }
            options.keylocation = keyloc;
        }
    }

    hideModal();
    executeActionWithRefresh(
        'create_dataset',
        [],
        {
            full_dataset_name: fullDsName,
            is_volume: isVolume,
            volsize: isVolume ? volSize : null,
            options: options,
            passphrase: encPassphrase
        },
        `${isVolume ? 'Volume' : 'Dataset'} '${fullDsName}' creation initiated.`
    );
}

/**
 * Handle destroy dataset action
 */
export function handleDestroyDataset() {
    if (!state.currentSelection || !['dataset', 'volume'].includes(state.currentSelection.obj_type)) return;
    
    const dsName = state.currentSelection.name;
    const typeStr = state.currentSelection.obj_type;

    let recursive = false;
    let confirmMsg = `Are you sure you want to permanently destroy ${typeStr} '${dsName}'?`;

    const hasChildren = state.currentSelection.children?.length > 0;
    const hasSnapshots = state.currentSelection.snapshots?.length > 0;

    if (hasChildren || hasSnapshots) {
        if (confirm(`WARNING: ${typeStr} '${dsName}' contains child items and/or snapshots.\n\nDo you want to destroy it RECURSIVELY (including all children and snapshots)?`)) {
            recursive = true;
            confirmMsg = `DANGER ZONE! Are you sure you want to RECURSIVELY destroy ${typeStr} '${dsName}' and ALL its contents (children, snapshots)?\n\nTHIS CANNOT BE UNDONE.`;
        } else {
            recursive = false;
            confirmMsg = `Attempt to destroy ONLY ${typeStr} '${dsName}' (may fail if children/snapshots exist)?`;
        }
    }

    executeActionWithRefresh(
        'destroy_dataset',
        [dsName],
        { recursive: recursive },
        `${typeStr.charAt(0).toUpperCase() + typeStr.slice(1)} '${dsName}' destruction initiated.`,
        true,
        confirmMsg
    );
}

/**
 * Handle rename dataset action
 */
export function handleRenameDataset() {
    if (!state.currentSelection || !['dataset', 'volume'].includes(state.currentSelection.obj_type)) return;
    
    const oldName = state.currentSelection.name;
    const typeStr = state.currentSelection.obj_type;
    const newName = prompt(`Enter the new FULL PATH for ${typeStr}:\n${oldName}`, oldName);
    
    if (newName === null || newName.trim() === "" || newName.trim() === oldName) return;
    
    const newPath = newName.trim();

    if (newPath.includes(' ') || !newPath.includes('/') || newPath.endsWith('/')) {
        alert(`Invalid target path format.`);
        return;
    }
    if (!/^[a-zA-Z0-9]/.test(newPath.split('/').pop())) {
        alert("Final component of new name must start with letter/number.");
        return;
    }
    if (/[^a-zA-Z0-9_\-:.%/]/.test(newPath)) {
        alert("New path contains invalid characters.");
        return;
    }

    let recursive = false;
    const force = confirm("Force unmount if dataset is busy? (Use with caution)");

    executeActionWithRefresh(
        'rename_dataset',
        [oldName, newPath],
        { recursive: recursive, force_unmount: force },
        `${typeStr.charAt(0).toUpperCase() + typeStr.slice(1)} '${oldName}' rename to '${newPath}' initiated.`,
        true,
        `Rename ${typeStr} '${oldName}' to '${newPath}'? ${force ? '(Force unmount)' : ''}`
    );
}

/**
 * Handle promote dataset action
 */
export function handlePromoteDataset() {
    if (!state.currentSelection || !['dataset', 'volume'].includes(state.currentSelection.obj_type)) return;
    
    const dsName = state.currentSelection.name;
    const props = state.currentSelection.properties || {};
    const origin = props.origin;
    
    if (!origin || origin === '-') {
        alert(`'${dsName}' is not a clone and cannot be promoted.`);
        return;
    }
    
    executeActionWithRefresh(
        'promote_dataset',
        [dsName],
        {},
        `Promotion of clone '${dsName}' initiated.`,
        true,
        `Promote clone '${dsName}'? This breaks its dependency on the origin snapshot.`
    );
}

/**
 * Handle dataset action (generic)
 */
export function handleDatasetAction(actionName, requireConfirm = false, confirmMsg = null, extraArgs = [], extraKwargs = {}) {
    if (!state.currentSelection || !['dataset', 'volume'].includes(state.currentSelection.obj_type)) return;
    
    const dsName = state.currentSelection.name;
    executeActionWithRefresh(
        actionName,
        [dsName, ...extraArgs],
        extraKwargs,
        `Dataset action '${actionName}' initiated for '${dsName}'.`,
        requireConfirm,
        confirmMsg || `Are you sure you want to perform '${actionName}' on '${dsName}'?`
    );
}
