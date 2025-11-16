# --- START OF FILE config_manager.py ---

import json
import os
import sys
import hashlib
import binascii # Needed for hex conversion of salt/hash bytes
import tempfile # For atomic writes
import logging

from paths import CREDENTIALS_FILE_PATH, PERSISTENT_DATA_DIR, USER_CONFIG_DIR, USER_CONFIG_FILE_PATH

# --- Hashing Constants (Standard Library) ---
# OWASP recommendation as of early 2023 for PBKDF2-HMAC-SHA256
PBKDF2_ITERATIONS = 260000
PBKDF2_SALT_BYTES = 16
PBKDF2_ALGORITHM = 'sha256'
PASSWORD_INFO_KEY = "password_info" # Key in credentials dict for the hash details

# --- Daemon Logging Setup ---
# Simplified: Daemon will configure its own logger
log = logging.getLogger(__name__) # Use standard logging

def load_config() -> dict:
    """Loads the configuration from the JSON file."""
    config_path = USER_CONFIG_FILE_PATH
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                if isinstance(config, dict):
                    return config
                else:
                    print(f"CONFIG: Warning: Config file '{config_path}' does not contain a valid JSON object. Using defaults.", file=sys.stderr)
                    return {} # Return empty dict if not valid structure
        except (json.JSONDecodeError, IOError) as e:
            print(f"CONFIG: Error loading config file '{config_path}': {e}. Using defaults.", file=sys.stderr)
            return {} # Return empty dict on error
    return {} # Return empty dict if file doesn't exist

def save_config(config: dict):
    """Saves the configuration dictionary to the JSON file."""
    config_dir = str(USER_CONFIG_DIR)
    config_path = USER_CONFIG_FILE_PATH
    try:
        os.makedirs(config_dir, exist_ok=True)
        # Ensure user owns the config dir/file if created by root previously (unlikely now)
        # This might fail if run without appropriate permissions, but best effort
        try:
            uid = os.getuid()
            gid = os.getgid()
            if os.path.exists(config_dir) and os.stat(config_dir).st_uid != uid:
                 os.chown(config_dir, uid, gid)
            if os.path.exists(config_path) and os.stat(config_path).st_uid != uid:
                 os.chown(config_path, uid, gid)
        except OSError as chown_e:
             print(f"CONFIG: Warning: Could not set ownership on config dir/file: {chown_e}", file=sys.stderr)

        with open(config_path, 'w') as f:
            json.dump(config, f, indent=4)
    except IOError as e:
        print(f"CONFIG: Error saving config file '{config_path}': {e}", file=sys.stderr)
        # Consider showing an error to the user if saving fails critically

# --- Setting accessors with defaults ---
_config_cache = None

def _get_cached_config() -> dict:
    """Internal helper to load config only once."""
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    return _config_cache

def get_setting(key: str, default=None):
    """Gets a specific setting from the config, returning a default if not found."""
    # Ensure cache is loaded if accessed first time
    return _get_cached_config().get(key, default)

def set_setting(key: str, value):
    """Sets a specific setting and saves the entire config."""
    global _config_cache
    config = _get_cached_config()
    config[key] = value
    save_config(config)
    # Update the cache immediately
    _config_cache = config

# --- Log File Path (Daemon uses this) ---
# --- ADD Password Management Functions (Daemon-side) ---

def _read_credentials() -> dict:
    """Reads the credentials file. Returns {} if not found or invalid."""
    if not os.path.exists(CREDENTIALS_FILE_PATH):
        log.warning(f"Credentials file not found at {CREDENTIALS_FILE_PATH}")
        return {}
    try:
        with open(CREDENTIALS_FILE_PATH, 'r') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            else:
                log.error(f"Credentials file {CREDENTIALS_FILE_PATH} does not contain a JSON object.")
                return {}
    except (json.JSONDecodeError, IOError, OSError) as e:
        log.exception(f"Error reading credentials file {CREDENTIALS_FILE_PATH}: {e}")
        return {}

def _write_credentials(credentials: dict) -> bool:
    """Writes the credentials dict to the file atomically. Returns True on success."""
    try:
        # Ensure data dir exists (should be created by installer)
        os.makedirs(str(PERSISTENT_DATA_DIR), mode=0o755, exist_ok=True)
        # Atomic write using temporary file
        temp_fd, temp_path = tempfile.mkstemp(dir=str(PERSISTENT_DATA_DIR))
        with os.fdopen(temp_fd, 'w') as f:
            json.dump(credentials, f, indent=4)

        # Ensure correct permissions before renaming
        os.chmod(temp_path, 0o644) # RW for root, R for group/others
        os.chown(temp_path, 0, 0) # Owner: root, Group: root

        # Replace original file
        os.replace(temp_path, CREDENTIALS_FILE_PATH)
        log.info(f"Credentials successfully written to {CREDENTIALS_FILE_PATH}")
        return True
    except (IOError, OSError) as e:
        log.exception(f"Error writing credentials file {CREDENTIALS_FILE_PATH}: {e}")
        # Attempt to clean up temp file on error
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False

def update_user_password(username: str, new_password: str) -> bool:
    """
    Updates the password for the given username using PBKDF2.
    This function is called by the daemon (running as root).
    Assumes old password verification was done by the client (web_ui).
    Returns True on success, False otherwise.
    """
    if not username or not new_password:
        log.error("update_user_password: Username and new_password are required.")
        return False

    credentials = _read_credentials()
    user_found = False
    user_id_to_update = None

    # Find the user by username (credentials stored by user ID key)
    for user_id, user_data in credentials.items():
        if isinstance(user_data, dict) and user_data.get("username") == username:
            user_found = True
            user_id_to_update = user_id
            break

    if not user_found:
        log.error(f"update_user_password: User '{username}' not found in credentials.")
        return False

    try:
        # Generate new salt and hash
        salt = os.urandom(PBKDF2_SALT_BYTES)
        key = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM,
            new_password.encode('utf-8'),
            salt,
            PBKDF2_ITERATIONS
        )

        # Prepare the new password info structure
        password_info = {
            "alg": f"pbkdf2_{PBKDF2_ALGORITHM}",
            "salt": binascii.hexlify(salt).decode('ascii'),
            "hash": binascii.hexlify(key).decode('ascii'),
            "iterations": PBKDF2_ITERATIONS
        }

        # Update the user's data
        credentials[user_id_to_update][PASSWORD_INFO_KEY] = password_info
        # Remove old werkzeug hash if present
        credentials[user_id_to_update].pop("password_hash", None)

        # Write back to file
        if _write_credentials(credentials):
            log.info(f"Password successfully updated for user '{username}'.")
            return True
        else:
            log.error(f"Failed to write updated credentials for user '{username}'.")
            return False

    except Exception as e:
        log.exception(f"An unexpected error occurred during password update for user '{username}': {e}")
        return False

def create_default_credentials_if_missing():
    """
    Checks if the credentials file exists at the system-wide path.
    If not, attempts to create it with a default admin user ('admin'/'admin').
    Logs errors but does not raise exceptions if creation fails.
    Called by the daemon on startup.
    """
    if os.path.exists(CREDENTIALS_FILE_PATH):
        return # File already exists

    log.warning(f"Credentials file not found at {CREDENTIALS_FILE_PATH}. Attempting to create default.")

    try:
        # Generate default user credentials
        default_username = "admin"
        default_password = "admin"

        # Generate salt and hash using PBKDF2
        salt = os.urandom(PBKDF2_SALT_BYTES)
        key = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM,
            default_password.encode('utf-8'),
            salt,
            PBKDF2_ITERATIONS
        )
        password_info = {
            "alg": f"pbkdf2_{PBKDF2_ALGORITHM}",
            "salt": binascii.hexlify(salt).decode('ascii'),
            "hash": binascii.hexlify(key).decode('ascii'),
            "iterations": PBKDF2_ITERATIONS
        }

        default_credentials = {
            "1": { # Default user ID
                "username": default_username,
                PASSWORD_INFO_KEY: password_info
            }
        }

        # Attempt to write the file
        if _write_credentials(default_credentials):
            log.info(f"Successfully created default credentials file at {CREDENTIALS_FILE_PATH}.")
            log.warning("IMPORTANT: The default 'admin' password should be changed immediately.")
        else:
            # _write_credentials already logs the specific error
            log.error("Failed to write default credentials file.")

    except Exception as e:
        # Catch any unexpected errors during hash generation or file writing setup
        log.exception(f"An unexpected error occurred while trying to create default credentials: {e}")

# --- END OF FILE config_manager.py ---
