"""
Credential Vault - Encrypted password storage for agent credentials.

Provides secure storage for agent passwords using AES-256-GCM encryption
with key derivation from a user master password via PBKDF2.

Storage location: ~/.config/ZfDash/credentials_vault.json
"""

import json
import os
import base64
import hashlib
from typing import Optional, Dict
from pathlib import Path

from paths import USER_CONFIG_DIR

# Vault file path
VAULT_FILE_PATH = USER_CONFIG_DIR / "credentials_vault.json"

# Crypto settings
SALT_SIZE = 16  # 128-bit salt
NONCE_SIZE = 12  # 96-bit nonce for GCM
KEY_SIZE = 32  # 256-bit key
ITERATIONS = 100000  # PBKDF2 iterations

# Check if cryptography is available
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


class CredentialVault:
    """
    Encrypted password storage for agent credentials.
    
    Passwords are encrypted with AES-256-GCM using a key derived from
    the user's master password via PBKDF2.
    
    The vault must be unlocked with the master password before passwords
    can be retrieved or stored. The unlocked state is maintained in memory.
    """
    
    def __init__(self, vault_path: Optional[Path] = None):
        """
        Initialize credential vault.
        
        Args:
            vault_path: Path to vault file. Defaults to ~/.config/ZfDash/credentials_vault.json
        """
        self.vault_path = vault_path or VAULT_FILE_PATH
        self._key: Optional[bytes] = None  # Derived encryption key (when unlocked)
        self._data: Optional[Dict] = None  # Decrypted vault data
        
    def is_available(self) -> bool:
        """Check if crypto libraries are installed."""
        return CRYPTO_AVAILABLE
    
    def is_initialized(self) -> bool:
        """Check if vault file exists (has been created with master password)."""
        return self.vault_path.exists()
    
    def is_unlocked(self) -> bool:
        """Check if vault is currently unlocked."""
        return self._key is not None and self._data is not None
    
    def create(self, master_password: str) -> tuple[bool, str]:
        """
        Create a new vault with the given master password.
        
        Args:
            master_password: Master password for vault encryption
            
        Returns:
            Tuple of (success, message)
        """
        if not CRYPTO_AVAILABLE:
            return False, "Cryptography library not installed"
        
        if not master_password:
            return False, "Master password cannot be empty"
        
        if len(master_password) < 8:
            return False, "Master password must be at least 8 characters"
        
        if self.is_initialized():
            return False, "Vault already exists. Delete it first to create a new one."
        
        try:
            # Generate random salt
            salt = os.urandom(SALT_SIZE)
            
            # Derive key from master password
            key = self._derive_key(master_password, salt)
            
            # Create empty vault data
            vault_data = {
                "version": 1,
                "passwords": {}
            }
            
            # Encrypt vault data
            encrypted = self._encrypt(json.dumps(vault_data), key)
            
            # Store vault file
            vault = {
                "salt": base64.b64encode(salt).decode('utf-8'),
                "data": base64.b64encode(encrypted).decode('utf-8'),
                "verification": base64.b64encode(
                    self._encrypt("vault_verification", key)
                ).decode('utf-8')
            }
            
            # Ensure config directory exists
            self.vault_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write vault file with secure permissions
            with open(self.vault_path, 'w') as f:
                json.dump(vault, f, indent=2)
            os.chmod(self.vault_path, 0o600)  # Read/write for owner only
            
            # Keep vault unlocked
            self._key = key
            self._data = vault_data
            
            return True, "Vault created successfully"
            
        except Exception as e:
            return False, f"Failed to create vault: {e}"
    
    def unlock(self, master_password: str) -> tuple[bool, str]:
        """
        Unlock the vault with the master password.
        
        Args:
            master_password: Master password
            
        Returns:
            Tuple of (success, message)
        """
        if not CRYPTO_AVAILABLE:
            return False, "Cryptography library not installed"
        
        if not self.is_initialized():
            return False, "Vault not initialized. Create it first."
        
        try:
            # Load vault file
            with open(self.vault_path, 'r') as f:
                vault = json.load(f)
            
            salt = base64.b64decode(vault['salt'])
            encrypted_data = base64.b64decode(vault['data'])
            verification = base64.b64decode(vault['verification'])
            
            # Derive key from master password
            key = self._derive_key(master_password, salt)
            
            # Verify password by decrypting verification string
            try:
                verified = self._decrypt(verification, key)
                if verified != "vault_verification":
                    return False, "Invalid master password"
            except Exception:
                return False, "Invalid master password"
            
            # Decrypt vault data
            decrypted = self._decrypt(encrypted_data, key)
            self._data = json.loads(decrypted)
            self._key = key
            
            return True, "Vault unlocked"
            
        except json.JSONDecodeError:
            return False, "Vault file is corrupted"
        except Exception as e:
            return False, f"Failed to unlock vault: {e}"
    
    def lock(self) -> None:
        """Lock the vault, clearing the key from memory."""
        self._key = None
        self._data = None
    
    def get_password(self, agent_alias: str) -> Optional[str]:
        """
        Get stored password for an agent.
        
        Args:
            agent_alias: Agent alias/identifier
            
        Returns:
            Password string, or None if not found or vault locked
        """
        if not self.is_unlocked():
            return None
        
        return self._data.get("passwords", {}).get(agent_alias)
    
    def has_password(self, agent_alias: str) -> bool:
        """Check if password is stored for agent."""
        if not self.is_unlocked():
            return False
        return agent_alias in self._data.get("passwords", {})
    
    def set_password(self, agent_alias: str, password: str) -> tuple[bool, str]:
        """
        Store password for an agent.
        
        Args:
            agent_alias: Agent alias/identifier
            password: Password to store
            
        Returns:
            Tuple of (success, message)
        """
        if not self.is_unlocked():
            return False, "Vault is locked"
        
        try:
            self._data["passwords"][agent_alias] = password
            self._save()
            return True, "Password saved"
        except Exception as e:
            return False, f"Failed to save password: {e}"
    
    def delete_password(self, agent_alias: str) -> tuple[bool, str]:
        """
        Delete stored password for an agent.
        
        Args:
            agent_alias: Agent alias/identifier
            
        Returns:
            Tuple of (success, message)
        """
        if not self.is_unlocked():
            return False, "Vault is locked"
        
        try:
            if agent_alias in self._data.get("passwords", {}):
                del self._data["passwords"][agent_alias]
                self._save()
                return True, "Password deleted"
            return False, "Password not found"
        except Exception as e:
            return False, f"Failed to delete password: {e}"
    
    def list_agents(self) -> list[str]:
        """List all agents with stored passwords."""
        if not self.is_unlocked():
            return []
        return list(self._data.get("passwords", {}).keys())
    
    def change_master_password(self, old_password: str, new_password: str) -> tuple[bool, str]:
        """
        Change the master password.
        
        Args:
            old_password: Current master password
            new_password: New master password
            
        Returns:
            Tuple of (success, message)
        """
        if not new_password or len(new_password) < 8:
            return False, "New password must be at least 8 characters"
        
        # First verify old password
        success, msg = self.unlock(old_password)
        if not success:
            return False, f"Current password verification failed: {msg}"
        
        try:
            # Generate new salt and key
            salt = os.urandom(SALT_SIZE)
            key = self._derive_key(new_password, salt)
            
            # Re-encrypt vault data with new key
            encrypted = self._encrypt(json.dumps(self._data), key)
            
            # Update vault file
            vault = {
                "salt": base64.b64encode(salt).decode('utf-8'),
                "data": base64.b64encode(encrypted).decode('utf-8'),
                "verification": base64.b64encode(
                    self._encrypt("vault_verification", key)
                ).decode('utf-8')
            }
            
            with open(self.vault_path, 'w') as f:
                json.dump(vault, f, indent=2)
            
            # Update in-memory key
            self._key = key
            
            return True, "Master password changed successfully"
            
        except Exception as e:
            return False, f"Failed to change password: {e}"
    
    def delete_vault(self) -> tuple[bool, str]:
        """
        Delete the entire vault file.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            if self.vault_path.exists():
                self.vault_path.unlink()
            self.lock()
            return True, "Vault deleted"
        except Exception as e:
            return False, f"Failed to delete vault: {e}"
    
    def _derive_key(self, password: str, salt: bytes) -> bytes:
        """Derive encryption key from password using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=KEY_SIZE,
            salt=salt,
            iterations=ITERATIONS,
        )
        return kdf.derive(password.encode('utf-8'))
    
    def _encrypt(self, plaintext: str, key: bytes) -> bytes:
        """Encrypt plaintext using AES-256-GCM."""
        aesgcm = AESGCM(key)
        nonce = os.urandom(NONCE_SIZE)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
        return nonce + ciphertext  # Prepend nonce to ciphertext
    
    def _decrypt(self, data: bytes, key: bytes) -> str:
        """Decrypt ciphertext using AES-256-GCM."""
        aesgcm = AESGCM(key)
        nonce = data[:NONCE_SIZE]
        ciphertext = data[NONCE_SIZE:]
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode('utf-8')
    
    def _save(self) -> None:
        """Save current vault data to disk."""
        if not self.is_unlocked():
            raise RuntimeError("Vault is locked")
        
        # Load existing vault to get salt
        with open(self.vault_path, 'r') as f:
            vault = json.load(f)
        
        # Re-encrypt with current key
        encrypted = self._encrypt(json.dumps(self._data), self._key)
        vault['data'] = base64.b64encode(encrypted).decode('utf-8')
        
        with open(self.vault_path, 'w') as f:
            json.dump(vault, f, indent=2)


# Global vault instance (initialized on first use)
_vault: Optional[CredentialVault] = None


def get_vault() -> CredentialVault:
    """Get the global vault instance."""
    global _vault
    if _vault is None:
        _vault = CredentialVault()
    return _vault
