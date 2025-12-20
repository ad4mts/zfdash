/**
 * Vault UI Module - Shared credential vault operations
 * 
 * Provides unified vault interaction for Control Center and Backup pages.
 */

// Vault state
let vaultStatus = null;

/**
 * Get vault status from backend
 * @returns {Promise<{available: boolean, initialized: boolean, unlocked: boolean}>}
 */
export async function getVaultStatus() {
    try {
        const response = await fetch('/api/vault/status');
        const data = await response.json();
        if (data.success) {
            vaultStatus = data.data;
            return vaultStatus;
        }
        return { available: false, initialized: false, unlocked: false };
    } catch (error) {
        console.warn('Failed to get vault status:', error);
        return { available: false, initialized: false, unlocked: false };
    }
}

/**
 * Ensure vault is unlocked, showing modal if needed
 * @returns {Promise<boolean>} true if vault is unlocked
 */
export async function ensureUnlocked() {
    const status = await getVaultStatus();

    if (!status.available) {
        console.warn('Vault not available (cryptography library missing)');
        return false;
    }

    if (status.unlocked) {
        return true;
    }

    if (!status.initialized) {
        // Show create vault modal
        return await showVaultCreateModal();
    }

    // Show unlock modal
    return await showVaultUnlockModal();
}

/**
 * Get saved password for agent
 * @param {string} alias - Agent alias
 * @returns {Promise<string|null>} Password or null
 */
export async function getPassword(alias) {
    try {
        const response = await fetch(`/api/vault/password/${encodeURIComponent(alias)}`);
        const data = await response.json();

        // Vault locked - try to unlock and retry
        if (data.needs_unlock) {
            const unlocked = await ensureUnlocked();
            if (unlocked) {
                return await getPassword(alias);  // Retry
            }
            return null;
        }

        if (data.success && data.data?.has_password) {
            return data.data.password;
        }
        return null;
    } catch (error) {
        // Silent fail - vault operations are optional
        return null;
    }
}

/**
 * Save password for agent
 * @param {string} alias - Agent alias
 * @param {string} password - Password to save
 * @returns {Promise<boolean>} Success
 */
export async function savePassword(alias, password) {
    try {
        const response = await fetch('/api/vault/password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_alias: alias, password })
        });
        const data = await response.json();

        // Vault locked - try to unlock and retry
        if (data.needs_unlock) {
            const unlocked = await ensureUnlocked();
            if (unlocked) {
                return await savePassword(alias, password);  // Retry
            }
            return false;
        }

        return data.success;
    } catch (error) {
        // Silent fail - vault operations are optional
        return false;
    }
}

/**
 * Auto-fill password field from vault
 * @param {string} inputId - Password input element ID
 * @param {string} alias - Agent alias
 * @param {string} indicatorId - Optional indicator element ID to show when filled
 * @returns {Promise<boolean>} True if password was filled
 */
export async function autoFillPassword(inputId, alias, indicatorId = null) {
    const input = document.getElementById(inputId);
    if (!input) return false;

    const password = await getPassword(alias);
    if (password) {
        input.value = password;
        input.dataset.fromVault = 'true';

        if (indicatorId) {
            const indicator = document.getElementById(indicatorId);
            if (indicator) {
                indicator.style.display = 'inline-block';
                indicator.title = 'Password loaded from vault';
            }
        }
        return true;
    }

    input.dataset.fromVault = 'false';
    if (indicatorId) {
        const indicator = document.getElementById(indicatorId);
        if (indicator) indicator.style.display = 'none';
    }
    return false;
}

/**
 * Create vault unlock modal and inject into page if not present
 */
function ensureModalsExist() {
    if (document.getElementById('vaultUnlockModal')) return;

    const modalHtml = `
    <!-- Vault Unlock Modal -->
    <div class="modal fade" id="vaultUnlockModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered modal-sm">
            <div class="modal-content">
                <div class="modal-header bg-warning">
                    <h5 class="modal-title"><i class="bi bi-lock me-2"></i>Unlock Vault</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <p class="small text-muted mb-3">Enter your master password (Web UI Password) to unlock the vault and access saved credentials.</p>
                    <div class="mb-3">
                        <input type="password" class="form-control" id="vault-unlock-password" 
                               placeholder="Master password" autofocus>
                    </div>
                    <div class="alert alert-danger small py-2" id="vault-unlock-error" style="display: none;"></div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancel</button>
                    <button type="button" class="btn btn-warning btn-sm" id="vault-unlock-btn">
                        <i class="bi bi-unlock"></i> Unlock
                    </button>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Vault Create Modal -->
    <div class="modal fade" id="vaultCreateModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered modal-sm">
            <div class="modal-content">
                <div class="modal-header bg-primary text-white">
                    <h5 class="modal-title"><i class="bi bi-safe me-2"></i>Create Vault</h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <p class="small text-muted mb-3">Create a secure vault to save agent passwords.</p>
                    <div class="mb-3">
                        <label class="form-label small">Master Password</label>
                        <input type="password" class="form-control form-control-sm" id="vault-create-password" 
                               placeholder="Min 8 characters">
                    </div>
                    <div class="mb-3">
                        <label class="form-label small">Confirm Password</label>
                        <input type="password" class="form-control form-control-sm" id="vault-create-confirm" 
                               placeholder="Confirm password">
                    </div>
                    <div class="alert alert-danger small py-2" id="vault-create-error" style="display: none;"></div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancel</button>
                    <button type="button" class="btn btn-primary btn-sm" id="vault-create-btn">
                        <i class="bi bi-plus-lg"></i> Create Vault
                    </button>
                </div>
            </div>
        </div>
    </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

/**
 * Show vault unlock modal
 * @returns {Promise<boolean>} True if unlocked successfully
 */
function showVaultUnlockModal() {
    return new Promise((resolve) => {
        ensureModalsExist();

        const modal = new bootstrap.Modal(document.getElementById('vaultUnlockModal'));
        const passwordInput = document.getElementById('vault-unlock-password');
        const errorDiv = document.getElementById('vault-unlock-error');
        const unlockBtn = document.getElementById('vault-unlock-btn');

        passwordInput.value = '';
        errorDiv.style.display = 'none';

        const handleUnlock = async () => {
            const password = passwordInput.value;
            if (!password) {
                errorDiv.textContent = 'Please enter password';
                errorDiv.style.display = 'block';
                return;
            }

            unlockBtn.disabled = true;
            unlockBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

            try {
                const response = await fetch('/api/vault/unlock', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ master_password: password })
                });
                const data = await response.json();

                if (data.success) {
                    modal.hide();
                    resolve(true);
                } else {
                    errorDiv.textContent = data.error || 'Invalid password';
                    errorDiv.style.display = 'block';
                }
            } catch (error) {
                errorDiv.textContent = 'Connection error';
                errorDiv.style.display = 'block';
            } finally {
                unlockBtn.disabled = false;
                unlockBtn.innerHTML = '<i class="bi bi-unlock"></i> Unlock';
            }
        };

        // Cleanup previous handlers
        unlockBtn.replaceWith(unlockBtn.cloneNode(true));
        document.getElementById('vault-unlock-btn').addEventListener('click', handleUnlock);

        passwordInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') handleUnlock();
        });

        modal.show();

        document.getElementById('vaultUnlockModal').addEventListener('hidden.bs.modal', () => {
            resolve(false);
        }, { once: true });
    });
}

/**
 * Show vault create modal
 * @returns {Promise<boolean>} True if created successfully
 */
function showVaultCreateModal() {
    return new Promise((resolve) => {
        ensureModalsExist();

        const modal = new bootstrap.Modal(document.getElementById('vaultCreateModal'));
        const passwordInput = document.getElementById('vault-create-password');
        const confirmInput = document.getElementById('vault-create-confirm');
        const errorDiv = document.getElementById('vault-create-error');
        const createBtn = document.getElementById('vault-create-btn');

        passwordInput.value = '';
        confirmInput.value = '';
        errorDiv.style.display = 'none';

        const handleCreate = async () => {
            const password = passwordInput.value;
            const confirm = confirmInput.value;

            if (!password || password.length < 8) {
                errorDiv.textContent = 'Password must be at least 8 characters';
                errorDiv.style.display = 'block';
                return;
            }
            if (password !== confirm) {
                errorDiv.textContent = 'Passwords do not match';
                errorDiv.style.display = 'block';
                return;
            }

            createBtn.disabled = true;
            createBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

            try {
                const response = await fetch('/api/vault/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ master_password: password })
                });
                const data = await response.json();

                if (data.success) {
                    modal.hide();
                    resolve(true);
                } else {
                    errorDiv.textContent = data.error || 'Failed to create vault';
                    errorDiv.style.display = 'block';
                }
            } catch (error) {
                errorDiv.textContent = 'Connection error';
                errorDiv.style.display = 'block';
            } finally {
                createBtn.disabled = false;
                createBtn.innerHTML = '<i class="bi bi-plus-lg"></i> Create Vault';
            }
        };

        // Cleanup previous handlers
        createBtn.replaceWith(createBtn.cloneNode(true));
        document.getElementById('vault-create-btn').addEventListener('click', handleCreate);

        confirmInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') handleCreate();
        });

        modal.show();

        document.getElementById('vaultCreateModal').addEventListener('hidden.bs.modal', () => {
            resolve(false);
        }, { once: true });
    });
}
