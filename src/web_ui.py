

# --- START OF FILE src/web_ui.py ---

import sys
import os
import traceback
import logging # logging change: Import standard logging library
import tempfile # For atomic writes
from flask import Flask, jsonify, request, render_template, send_from_directory, redirect, url_for, session, flash # RESTORED: flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user # Added Flask-Login imports
from dataclasses import is_dataclass, fields # Needed for recursive dict conversion
import json # For loading/saving credentials
import threading # For file lock on save
import hashlib # For password hashing/checking
import binascii # For hex encoding/decoding salt/hash
import hmac # Import hmac for compare_digest

# --- Modified ZFS Manager Import ---
# Assume zfs_manager and its error class are importable
try:
    # Import the client class and error types
    from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError
    # Import config_manager to get credential path and hashing constants
    import config_manager
    from config_manager import CREDENTIALS_FILE_PATH, PASSWORD_INFO_KEY, \
                               PBKDF2_ALGORITHM, PBKDF2_ITERATIONS, PBKDF2_SALT_BYTES
    import utils # For formatting/parsing in backend if needed
    # Import models needed for type checking in dict conversion
    from models import ZfsObject, Pool, Dataset, Snapshot
except ImportError as e:
    # Use basic print here as logger might not be configured yet
    print(f"WEB_UI: FATAL: Could not import required ZFS modules or config: {e}", file=sys.stderr)
    print("WEB_UI: Ensure zfs_manager.py, config_manager.py, models.py, etc. are in the Python path.", file=sys.stderr)
    # Define dummies
    class ZfsCommandError(Exception): pass
    class ZfsClientCommunicationError(Exception): pass
    class MockZFSManagerClient:
        def __getattr__(self, name):
            def method(*args, **kwargs):
                if name == 'get_all_zfs_data': return []
                if name == 'list_block_devices': return []
                if name == 'list_importable_pools': return (False, "Mock Error", [])
                if name == 'get_all_properties_with_sources': return (False, {}, "Mock Error")
                if name == 'change_webui_password': return (False, "Mock Error")
                if name == 'close': return None
                raise ZfsCommandError(f"MockZFSManagerClient: Method '{name}' called, but module failed to load.")
            return method
    # Instead of replacing zfs_manager, we'll handle the client instance later
    ZfsManagerClient = MockZFSManagerClient # Use mock class if real one failed
    class ZfsObject: pass
    class Pool(ZfsObject): pass
    class Dataset(ZfsObject): pass
    class Snapshot(ZfsObject): pass
    # Dummy config values if import fails
    CREDENTIALS_FILE_PATH = "/tmp/zfdash_credentials.json.err"
    PASSWORD_INFO_KEY = "password_info"
    PBKDF2_ALGORITHM = 'sha256'
    PBKDF2_ITERATIONS = 1000 # Low for dummy
    PBKDF2_SALT_BYTES = 16

# --- *** Defining the app with folder *** ---
# --- pyinstaller change: Determine base directory for resources ---
# This section ensures that template and static files are found correctly
# whether running from source or as a PyInstaller bundled executable.
if getattr(sys, 'frozen', False):
    # Running in a PyInstaller bundle (frozen)
    base_dir = sys._MEIPASS
else:
    # Running in a normal Python environment
    # Assuming web_ui.py is in a 'src' directory, adjust if necessary
    base_dir = os.path.dirname(os.path.abspath(__file__))

# --- pyinstaller change: Construct full paths to template, static, and data folders ---
template_folder = os.path.join(base_dir, 'templates')
static_folder = os.path.join(base_dir, 'static')
data_folder = os.path.join(base_dir, 'data') # Define data folder path
# --- pyinstaller change: End resource path determination ---


# --- pyinstaller change: Create Flask app using dynamic paths ---
app = Flask(__name__,
            template_folder=template_folder,
            static_folder=static_folder)
app.config['JSON_SORT_KEYS'] = False # Keep order in JSON responses


# --- *** IMPORTANT: Secret Key for Sessions *** ---
# Handle Flask Secret Key generation and persistence within the Docker container.
# In this Docker setup, the entire container runs as root (see run_docker.sh).
# Therefore, this web_ui.py process has root privileges within the container
# and can manage the key file in the persistent volume.

# Path for the persistent secret key within the container, mapped to a Docker volume.
FLASK_KEY_PERSISTENT_PATH = "/opt/zfdash/data/flask_secret_key.txt"

flask_key = None

# 1. Try to load the key from the persistent path (mapped volume) (generated during install)
try:
    if os.path.exists(FLASK_KEY_PERSISTENT_PATH):
        with open(FLASK_KEY_PERSISTENT_PATH, 'r') as f:
            flask_key = f.read().strip()
            if not flask_key:
                # Handle case where file exists but is empty
                print(f"WARNING: Flask key file '{FLASK_KEY_PERSISTENT_PATH}' exists but is empty.", file=sys.stderr)
                flask_key = None # Treat empty file as key not found
            else:
                # Key loaded successfully from persistent volume
                print(f"INFO: Loaded Flask secret key from persistent path {FLASK_KEY_PERSISTENT_PATH}", file=sys.stderr)

    # 2. If key wasn't loaded (file missing or empty), generate, save, and use a new one (for docker only .. webui as root).
    if flask_key is None:
        print(f"INFO: Flask secret key not found or empty at {FLASK_KEY_PERSISTENT_PATH}. Generating a new secure key...", file=sys.stderr)
        # Generate a cryptographically secure random key
        flask_key = os.urandom(32).hex()
        try:
            # Ensure the target directory exists in the volume (running as root allows this)
            os.makedirs(os.path.dirname(FLASK_KEY_PERSISTENT_PATH), mode=0o755, exist_ok=True)
            # Write the new key to the persistent file
            with open(FLASK_KEY_PERSISTENT_PATH, 'w') as f:
                f.write(flask_key)
            # Set permissions (root:root, rw-r--r--) - 600 might be slightly better but 644 is fine here.
            os.chmod(FLASK_KEY_PERSISTENT_PATH, 0o644)
            # Ensure ownership is root:root (should be by default as container runs as root)
            try:
                os.chown(FLASK_KEY_PERSISTENT_PATH, 0, 0)
            except OSError as chown_err: # Catch potential permission issues if chown isn't allowed (unlikely for root)
                print(f"WARNING: Could not set ownership on {FLASK_KEY_PERSISTENT_PATH}: {chown_err}", file=sys.stderr)

            print(f"INFO: Successfully generated and saved new Flask secret key to {FLASK_KEY_PERSISTENT_PATH}", file=sys.stderr)
        except (IOError, OSError) as e:
            # Handle errors during key saving
            print(f"ERROR: Failed to save generated Flask secret key to {FLASK_KEY_PERSISTENT_PATH}: {e}", file=sys.stderr)
            print("ERROR: Falling back to environment variable or default key. Session security may be compromised!", file=sys.stderr)
            flask_key = None # Nullify key if save failed, force fallback below

except Exception as e:
    # Catch any other unexpected errors during key handling
    print(f"ERROR: An unexpected error occurred during Flask secret key loading/generation: {e}", file=sys.stderr)
    print("ERROR: Falling back to environment variable or default key. Session security may be compromised!", file=sys.stderr)
    flask_key = None # Nullify key on error, force fallback below


# 3. Fallback to environment variable or insecure default (only if loading/generation/saving failed)
if flask_key is None:
    flask_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-replace-me!')
    if flask_key == 'dev-secret-key-replace-me!':
        # This warning should ideally not appear if the volume permissions are correct.
        print("WARNING: Using insecure default Flask secret key. This should only happen if saving the generated key failed.", file=sys.stderr)
        print("         Check permissions for the 'zfdash_data' volume mount or set FLASK_SECRET_KEY environment variable.", file=sys.stderr)


# Set the Flask application's secret key
app.secret_key = flask_key
# --- *** IMPORTANT: Secret Key for Sessions *** ---

# ---End Defining app-----------------------------

# --- *** Authentication Setup (Flask-Login) *** ---
login_manager = LoginManager()
login_manager.session_protection = "strong"
login_manager.init_app(app)
login_manager.login_view = 'login' # *** THIS IS KEY: Redirects @login_required to the /login route ***
login_manager.login_message = "Please log in to access this page." # RESTORED: Flash message for redirect
login_manager.login_message_category = "info" # RESTORED: Category for flash message

# --- Simple User Model (Replace with proper storage later) ---
class User(UserMixin):
    def __init__(self, id, username, password_info):
        """Password info is now a dictionary from credentials file."""
        self.id = id
        self.username = username
        self.password_info = password_info # Store the dict {alg, salt, hash, iterations}

    def set_password(self, password):
        """
        Generates salt and hash using PBKDF2, storing the info dict.
        Used ONLY for creating the default user if credentials file doesn't exist.
        The password change flow relies on the daemon to generate/save.
        """
        salt = os.urandom(PBKDF2_SALT_BYTES)
        key = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM,
            password.encode('utf-8'),
            salt,
            PBKDF2_ITERATIONS
        )
        self.password_info = {
            "alg": f"pbkdf2_{PBKDF2_ALGORITHM}",
            "salt": binascii.hexlify(salt).decode('ascii'),
            "hash": binascii.hexlify(key).decode('ascii'),
            "iterations": PBKDF2_ITERATIONS
        }

    def check_password(self, password):
        """Verifies a password against the stored salt/hash using PBKDF2."""
        if not isinstance(self.password_info, dict):
            app.logger.error(f"User '{self.username}' has invalid password_info format: {self.password_info}")
            return False

        stored_alg = self.password_info.get("alg")
        stored_salt_hex = self.password_info.get("salt")
        stored_hash_hex = self.password_info.get("hash")
        stored_iterations = self.password_info.get("iterations")

        # Basic validation
        if not stored_alg or not stored_salt_hex or not stored_hash_hex or not stored_iterations:
            app.logger.error(f"User '{self.username}' has incomplete password_info: {self.password_info}")
            return False

        # Check if algorithm matches (allow only pbkdf2_sha256 for now)
        if stored_alg != f"pbkdf2_{PBKDF2_ALGORITHM}":
            app.logger.error(f"User '{self.username}' has unsupported password hash algorithm: {stored_alg}")
            return False

        try:
            salt = binascii.unhexlify(stored_salt_hex)
            stored_hash = binascii.unhexlify(stored_hash_hex)

            # Hash the provided password with the stored salt and iterations
            key_to_check = hashlib.pbkdf2_hmac(
                PBKDF2_ALGORITHM,
                password.encode('utf-8'),
                salt,
                stored_iterations
            )

            # Compare the derived key with the stored hash (use compare_digest for timing resistance)
            return hmac.compare_digest(key_to_check, stored_hash) # Use hmac's compare_digest (timing resistant)
        except (binascii.Error, TypeError, ValueError) as e:
            app.logger.exception(f"Error during password check for user '{self.username}': {e}")
            return False

# --- User Store Configuration ---
# Use canonical path imported from config_manager
CREDENTIALS_FILE = CREDENTIALS_FILE_PATH
_users_lock = threading.Lock() # Lock for writing to the credentials file (only used for default user creation now)

# --- User Store Loading/Saving Functions ---
def _load_users():
    """Loads users from the JSON credentials file."""
    # global users # No longer modifying global directly, return the dict
    loaded_users = {}
    try:
        if not os.path.exists(CREDENTIALS_FILE):
            # --- MODIFIED: Do not create file, log error instead ---
            app.logger.error(f"Credentials file not found at {CREDENTIALS_FILE}.")
            app.logger.error("Please ensure the file exists and is readable. It should be created by the daemon if it doesn't exist.")
            # Return empty users, login will fail until file exists.
            return {}
            # --- END MODIFICATION ---
        else:
            with open(CREDENTIALS_FILE, 'r') as f:
                data = json.load(f)
                # Convert loaded dict back to User objects
                for user_id, user_data in data.items():
                    # --- *** Use PASSWORD_INFO_KEY *** ---
                    if 'username' in user_data and PASSWORD_INFO_KEY in user_data and isinstance(user_data[PASSWORD_INFO_KEY], dict):
                         loaded_users[user_id] = User(id=user_id,
                                                      username=user_data['username'],
                                                      password_info=user_data[PASSWORD_INFO_KEY])
                    # Handle legacy format (optional, maybe log warning)
                    elif 'username' in user_data and 'password_hash' in user_data:
                         app.logger.warning(f"User ID {user_id} has legacy password format. Please reset password.")
                         # Optionally skip loading legacy users:
                         # continue
                         # Or load with unusable password info:
                         loaded_users[user_id] = User(id=user_id,
                                                     username=user_data['username'],
                                                     password_info={})

                    else:
                         app.logger.warning(f"Skipping invalid user entry with id {user_id} in credentials file.")
            #app.logger.info(f"Loaded {len(loaded_users)} user(s) from {CREDENTIALS_FILE}")

    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        # Changed Exception to OSError for file-related errors
        app.logger.exception(f"Failed to load or create credentials file at {CREDENTIALS_FILE}. Using empty user store. Error: {e}")
        # Fallback to empty store if loading fails catastrophically
        loaded_users = {}

    return loaded_users

# --- Initialize User Store ---
# --- End User Store ---


@login_manager.user_loader
def load_user(user_id):
    """Flask-Login required callback to load a user from the 'session'. Reads file on demand."""
    # Read credentials file here instead of using global cache
    current_users = _load_users() # _load_users reads the file or returns {} if missing/error
    return current_users.get(user_id)
# --- End Authentication Setup ---

# --- logging change: Ensure Flask logger outputs to stderr explicitly
app.logger.addHandler(logging.StreamHandler(sys.stderr))
# logging change: Set Flask logger level (optional, basicConfig might cover it)
app.logger.setLevel(logging.INFO) # Or logging.DEBUG


# --- logging change: Define the request logging function ---
def log_request_info(response):
    """Log request details after each request if debug is enabled."""
    if request.path.startswith('/static'):
        return response
    app.logger.debug(
        f'{request.remote_addr} - "{request.method} {request.path} {request.scheme.upper()}/{request.environ.get("SERVER_PROTOCOL", "HTTP/1.1").split("/")[1]}" '
        f'{response.status_code} {response.content_length}'
    )
    return response


# --- NEW: Helper Function to Convert Dataclasses to Dicts Recursively (excluding 'parent') ---
def _to_dict_recursive(obj):
    """
    Recursively converts dataclass instances into dictionaries,
    handling lists and excluding the 'parent' field.
    """
    if isinstance(obj, list):
        return [_to_dict_recursive(item) for item in obj]
    elif is_dataclass(obj) and not isinstance(obj, type): # Check if it's an instance, not the class itself
        result = {}
        for field_info in fields(obj):
            if field_info.name == 'parent':
                continue
            value = getattr(obj, field_info.name)
            result[field_info.name] = _to_dict_recursive(value)
        return result
    elif isinstance(obj, (str, int, float, bool, type(None), dict)):
        return obj
    else:
        app.logger.warning(f"Converting unhandled type {type(obj)} to string in _to_dict_recursive.")
        return str(obj)


# --- Helper Function (Modified) ---
def _get_zfs_client() -> ZfsManagerClient:
    """Helper to get the ZFS client instance stored in the app context."""
    client = getattr(app, 'zfs_client', None)
    if client is None:
        app.logger.error("ZFS Manager Client not found in Flask app context!")
        raise ZfsClientCommunicationError("ZFS Client not initialized.")
    return client

def _handle_zfs_call(func_name: str, *args, **kwargs):
    """Wraps zfs_manager calls using the client instance to handle errors and return JSON."""
    try:
        zfs_client = _get_zfs_client()
        method_to_call = getattr(zfs_client, func_name)
        result = method_to_call(*args, **kwargs)

        # --- Specific Handling for different return types ---
        if func_name == 'get_all_zfs_data':
            dict_result = _to_dict_recursive(result)
            return jsonify(status="success", data=dict_result)
        elif func_name == 'list_block_devices':
            return jsonify(status="success", data=result)
        elif func_name == 'list_importable_pools':
            success, msg, data = result
            if success:
                 return jsonify(status="success", message=msg, data=data)
            else:
                 return jsonify(status="error", error=msg, details=""), 400
        elif func_name == 'get_all_properties_with_sources':
             success, data, error_msg = result
             if success:
                  return jsonify(status="success", data=data)
             else:
                  return jsonify(status="error", error=error_msg, details=""), 400
        elif func_name == 'execute_generic_action':
             zfs_command = args[0] if args else "unknown_action"
             success, message = result
             if success:
                 return jsonify(status="success", message=message, data=None)
             else:
                 return jsonify(status="error", error=message, details=""), 400
        # --- NEW: Password change handled via standard execute_generic_action ---
        else:
            # Default handling: Assume successful result is the data
            data = None
            if isinstance(result, tuple) and len(result) == 2:
                 if result[0] is True: data = result[1]
            elif result is not None:
                 data = result
            return jsonify(status="success", data=data)

    except (ZfsCommandError, ZfsClientCommunicationError, TimeoutError) as e:
        app.logger.error(f"Error calling ZFS function '{func_name}': {e}")
        app.logger.error(traceback.format_exc())
        error_details = getattr(e, 'details', str(e))
        return jsonify(status="error", error=str(e), details=error_details), 500
    except AttributeError:
        app.logger.error(f"ZFS client does not have method '{func_name}'")
        return jsonify(status="error", error=f"Internal Server Error: Invalid ZFS client method '{func_name}'", details=""), 500
    except Exception as e:
        app.logger.exception(f"Unexpected error handling ZFS call '{func_name}': {e}")
        return jsonify(status="error", error="An unexpected server error occurred.", details=str(e)), 500

# --- Authentication Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index')) # Already logged in, go to main app

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash("Username and password are required.", "warning")
            return render_template('login.html')

        users = _load_users()
        user = next((u for u in users.values() if u.username == username), None)

        if user and user.check_password(password):
            login_user(user, remember=True) # Use remember=True
            app.logger.info(f"User '{username}' logged in successfully.")
            next_page = request.args.get('next')
            # --- Prevent redirecting to logout page --- 
            logout_url = url_for('logout')
            if next_page == logout_url:
                app.logger.debug(f"Login redirect target was '{logout_url}', overriding to index.")
                next_page = None # Override to redirect to index
            # --- End prevention ---    
            if next_page and not next_page.startswith('/'): # Basic security check
                app.logger.warning(f"Invalid next_page value detected: {next_page}. Clearing.")
                next_page = None
            return redirect(next_page or url_for('index'))
        else:
            app.logger.warning(f"Failed login attempt for username: '{username}'.")
            flash('Invalid username or password.', 'danger')
            return render_template('login.html')

    # GET request - Just render the login page
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
@login_required # Require login to logout
def logout():
    user_name = current_user.username if current_user.is_authenticated else "Unknown"
    logout_user()
    app.logger.info(f"User '{user_name}' logged out.")
    flash("You have been logged out successfully.", "success")
    # Redirect back to the login page after logout
    return redirect(url_for('login'))

@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    if not request.is_json:
        return jsonify(status="error", error="Invalid Request", details="Request must be JSON."), 400

    data = request.get_json()
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    confirm_password = data.get('confirm_password')

    if not current_password or not new_password:
        return jsonify(status="error", error="Missing Fields", details="Current and new passwords are required."), 400
    if new_password != confirm_password:
         return jsonify(status="error", error="Password Mismatch", details="New passwords do not match."), 400

    user = current_user
    if not user or not user.check_password(current_password):
        app.logger.warning(f"User '{user.username}' failed password change attempt: Incorrect current password.")
        return jsonify(status="error", error="Incorrect Password", details="The current password provided is incorrect."), 403

    # --- Call ZFS Manager Daemon to change password via specific client method ---
    app.logger.info(f"User '{user.username}' attempting password change via daemon.")
    try:
        client = _get_zfs_client()
        success, message = client.change_webui_password(user.username, new_password)

        if success:
            app.logger.info(f"User '{user.username}' password successfully changed by daemon.")
            # Force re-login for security and to update potential session data
            logout_user()
            # Return success, client-side JS should prompt for re-login maybe?
            # Or just return success and rely on the session being invalid on next protected request?
            # For simplicity, let's return success and let the next request handle the re-auth.
            return jsonify(status="success", message=message or "Password changed successfully. Please log in again if needed."), 200
        else:
            app.logger.error(f"Password change failed for user '{user.username}'. Daemon error: {message}")
            return jsonify(status="error", error="Password Change Failed", details=message or "Daemon failed to change the password."), 500

    except (ZfsCommandError, ZfsClientCommunicationError, TimeoutError) as e:
        app.logger.exception(f"Error communicating with daemon during password change for '{user.username}': {e}")
        error_details = str(e) if isinstance(e, ZfsCommandError) else "Could not communicate with the backend service."
        return jsonify(status="error", error="Communication Error", details=error_details), 503 # Service Unavailable
    except Exception as e:
        app.logger.exception(f"Unexpected error during password change for '{user.username}': {e}")
        return jsonify(status="error", error="Internal Server Error", details="An unexpected error occurred."), 500


# --- Protected API Routes ---

@app.route('/api/data')
@login_required
def get_data():
    """Endpoint to get the main pool/dataset/snapshot hierarchy."""
    return _handle_zfs_call('get_all_zfs_data')

@app.route('/api/properties/<path:obj_name>')
@login_required
def get_properties(obj_name):
    """Endpoint to get properties for a specific ZFS object."""
    return _handle_zfs_call('get_all_properties_with_sources', obj_name)

@app.route('/api/block_devices')
@login_required
def get_block_devices():
    """Endpoint to get available block devices for UI dialogs."""
    return _handle_zfs_call('list_block_devices')

@app.route('/api/importable_pools')
@login_required
def get_importable_pools():
    """Endpoint to search for importable pools."""
    search_dirs_str = request.args.get('search_dirs')
    search_dirs_list = search_dirs_str.split(',') if search_dirs_str else None
    return _handle_zfs_call('list_importable_pools', search_dirs=search_dirs_list)


@app.route('/api/action/<action_name>', methods=['POST'])
@login_required
def execute_action(action_name):
    """Generic endpoint to execute ZFS actions."""
    if not request.is_json:
        return jsonify({"status": "error", "error": "Request must be JSON"}), 400

    data = request.get_json()
    args = data.get('args', [])
    kwargs = data.get('kwargs', {})
    success_msg = f"Action '{action_name}' executed successfully." # Default msg

    # Use the generic executor from zfs_manager via _handle_zfs_call
    return _handle_zfs_call('execute_generic_action', action_name, success_msg, *args, **kwargs)


# --- HTML Serving Routes ---

@app.route('/')
@login_required # *** THIS IS KEY: Protects the main app page ***
def index():
    # Renders index.html ONLY if user is authenticated by Flask-Login.
    # If not authenticated, Flask-Login redirects to login_manager.login_view ('/login')
    return render_template('index.html')

@app.route('/api/auth/status')
def auth_status():
    # This route remains accessible without login to allow JS check
    if current_user.is_authenticated:
        return jsonify(status="success", authenticated=True, username=current_user.username)
    else:
        return jsonify(status="success", authenticated=False)

# Serve static files (JS, CSS) - Handled automatically by Flask

# --- Main Execution ---
def run_web_ui(host='127.0.0.1', port=5001, debug=False, zfs_client: ZfsManagerClient = None):
    """Runs the Flask app using Waitress, with conditional request logging."""

    if zfs_client is None:
        print("WEB_UI: FATAL - ZfsManagerClient instance not provided!", file=sys.stderr)
        sys.exit(1)

    app.zfs_client = zfs_client
    print(f"WEB_UI: ZFS Manager Client attached to Flask app.", file=sys.stderr)

    if debug:
        logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:%(name)s:%(message)s')
        app.logger.setLevel(logging.DEBUG)
        app.after_request(log_request_info)
        print(f"WEB_UI: Debug mode enabled. Running Flask development server on http://{host}:{port}", file=sys.stderr)
        app.run(host=host, port=port, debug=True)
    else:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
        app.logger.setLevel(logging.INFO)
        try:
            from waitress import serve
            print(f"WEB_UI: Production mode. Running Waitress server on http://{host}:{port}", file=sys.stderr)
            serve(app, host=host, port=port, threads=8)
        except ImportError:
            app.logger.error("Waitress not found. Falling back to Flask development server (NOT recommended for production).")
            print("WEB_UI: Waitress not installed. Running Flask development server.", file=sys.stderr)
            app.run(host=host, port=port, debug=False)
        except Exception as e:
            app.logger.exception(f"Error starting Waitress server: {e}")
            print(f"WEB_UI: Error starting Waitress server: {e}", file=sys.stderr)
            try:
                print("WEB_UI: Attempting fallback to Flask development server...", file=sys.stderr)
                app.run(host=host, port=port, debug=False)
            except Exception as fallback_e:
                 app.logger.exception(f"Fallback to Flask dev server also failed: {fallback_e}")
                 print(f"WEB_UI: Fallback to Flask dev server failed: {fallback_e}", file=sys.stderr)
                 sys.exit(1)

# Direct execution block
if __name__ == '__main__':
    # No changes needed here for testing
    debug_mode = '--debug' in sys.argv
    if not debug_mode:
        print("Use '--debug' flag for debugging")

    # --- Mock client for standalone testing if needed ---
    # Comment this out if running with the actual main.py or daemon
    mock_client = MockZFSManagerClient()
    run_web_ui(host='127.0.0.1', port=5001, debug=debug_mode, zfs_client=mock_client)
    # --------------------------------------------------

    # If running via main.py, zfs_client will be provided.
    # run_web_ui(host='127.0.0.1', port=5001, debug=debug_mode) # This line expects zfs_client from caller

# --- END OF FILE src/web_ui.py ---

# --- END OF FILE web_ui.py ---
