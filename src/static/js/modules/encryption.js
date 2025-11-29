/**
 * encryption.js - Encryption Management Module
 * 
 * Handles encryption info rendering and key management actions.
 */

import * as state from './state.js';
import { executeActionWithRefresh } from './api.js';
import { showModal, hideModal } from './ui.js';

/**
 * Render encryption information for an encrypted dataset
 * @param {object|null} obj - ZFS object or null to disable
 * @param {boolean} disableOnly - If true, just disable buttons without rendering info
 */
export function renderEncryptionInfo(obj, disableOnly = false) {
    if (disableOnly || !obj) {
        document.getElementById('load-key-button').disabled = true;
        document.getElementById('unload-key-button').disabled = true;
        document.getElementById('change-key-button').disabled = true;
        document.getElementById('change-key-location-button').disabled = true;
        return;
    }

    const props = obj.properties || {};
    const isEncrypted = props.encryption && props.encryption !== 'off' && props.encryption !== '-';
    const keyStatus = props.keystatus || (isEncrypted ? 'unavailable' : 'N/A');
    const isAvailable = keyStatus === 'available';
    const isMounted = obj.is_mounted;

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
    const unloadEnabled = isEncrypted && isAvailable;
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
}

/**
 * Handle load key action
 */
export function handleLoadKey() {
    if (!state.currentSelection || !state.currentSelection.is_encrypted) return;
    
    const dsName = state.currentSelection.name;
    const keyLocation = state.currentSelection.properties?.keylocation || 'prompt';
    const keyFormat = state.currentSelection.properties?.keyformat || 'passphrase';

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
            hideModal();
            executeActionWithRefresh(
                'load_key',
                [],
                { dataset_name: dsName, recursive: false, key_location: locationToSend, passphrase: passphrase },
                `Key load initiated for '${dsName}'.`
            );
        });
        return;
    } else if (locationToSend && !locationToSend.startsWith('file:///')) {
        alert(`Invalid key location '${keyLocation}'. Cannot load key.`);
        return;
    }

    executeActionWithRefresh(
        'load_key',
        [],
        { dataset_name: dsName, recursive: false, key_location: locationToSend, passphrase: null },
        `Key load initiated for '${dsName}'.`
    );
}

/**
 * Handle unload key action
 */
export function handleUnloadKey() {
    if (!state.currentSelection || !state.currentSelection.is_encrypted) return;
    
    const dsName = state.currentSelection.name;
    if (state.currentSelection.is_mounted || state.currentSelection.properties?.mounted === 'yes') {
        alert(`Dataset '${dsName}' must be unmounted before its key can be unloaded.`);
        return;
    }
    
    let recursive = false;
    if (state.currentSelection.children?.some(c => c.is_encrypted)) {
        recursive = confirm(`Unload keys recursively for child datasets under '${dsName}'?`);
    }
    
    executeActionWithRefresh(
        'unload_key',
        [],
        { dataset_name: dsName, recursive: recursive },
        `Key unload initiated for '${dsName}'.`,
        true,
        `Unload encryption key${recursive ? ' recursively' : ''} for '${dsName}'?\nData will become inaccessible.`
    );
}

/**
 * Handle change key action
 */
export function handleChangeKey() {
    if (!state.currentSelection || !state.currentSelection.is_encrypted || state.currentSelection.properties?.keystatus !== 'available') {
        alert("Key must be loaded (available) to change it.");
        return;
    }
    
    const dsName = state.currentSelection.name;
    const keyFormat = state.currentSelection.properties?.keyformat || 'passphrase';

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
            if (!pass1) {
                alert("New passphrase cannot be empty.");
                return;
            }
            if (pass1 !== pass2) {
                alert("New passphrases do not match.");
                return;
            }
            const changeInfo = `${pass1}\n${pass1}\n`;
            hideModal();
            executeActionWithRefresh(
                'change_key',
                [],
                { dataset_name: dsName, load_key: true, recursive: false, options: {keyformat: 'passphrase'}, passphrase_change_info: changeInfo },
                `Passphrase change initiated for '${dsName}'.`
            );
        });
    } else {
        alert("Changing key files via the web UI is not yet implemented. Use 'Change Key Location' instead if you only want to point to a different existing key file.");
    }
}

/**
 * Handle change key location action
 */
export function handleChangeKeyLocation() {
    if (!state.currentSelection || !state.currentSelection.is_encrypted) return;
    
    const dsName = state.currentSelection.name;
    const currentLoc = state.currentSelection.properties?.keylocation || 'prompt';
    const newLoc = prompt(`Enter new key location for '${dsName}':\n(Current: ${currentLoc})\nUse 'prompt' or 'file:///path/to/key'`, currentLoc);
    
    if (newLoc === null || newLoc.trim() === "" || newLoc.trim() === currentLoc) return;
    
    const newLocation = newLoc.trim();
    if (newLocation !== 'prompt' && !newLocation.startsWith('file:///')) {
        alert("Invalid location format. Use 'prompt' or 'file:///...'");
        return;
    }
    
    executeActionWithRefresh(
        'set_dataset_property',
        [dsName, 'keylocation', newLocation],
        {},
        `Key location change initiated for '${dsName}'.`,
        true,
        `Change key location property for '${dsName}' to:\n'${newLocation}'?`
    );
}
