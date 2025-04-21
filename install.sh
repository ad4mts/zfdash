#!/bin/bash
# Installation script for ZfDash
# Installs the pre-built ZfDash application (output from build.sh) system-wide,
# copying necessary assets like icons and policies directly from the source tree.
# This script MUST be run as root or with sudo.

# --- Strict Mode ---
set -u # Treat unset variables as errors
set -o pipefail # Handle pipe errors correctly
# Do not set -e globally, handle errors explicitly in installation steps

# --- ========================== ---
# --- === CONFIGURATION START ==== ---
# --- ========================== ---

# --- Application Info (Should match build.sh) ---
APP_NAME="ZfDash"
INSTALL_NAME="zfdash"
APP_VERSION="1.5.4" # Informational

# --- Build Output Configuration (Where to find the pre-built app) ---
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
BUILD_DIST_DIR="${SCRIPT_DIR}/dist"
APP_EXECUTABLE_NAME="${INSTALL_NAME}"
SOURCE_BUNDLED_APP_DIR="${BUILD_DIST_DIR}/${APP_EXECUTABLE_NAME}" # Path to the output of build.sh

# --- Source Data Locations (Needed for icon, policy) ---
# --- MODIFICATION: Correctly point to src/data for source assets ---
SOURCE_DATA_SUBDIR="src/data"
SOURCE_DATA_DIR="${SCRIPT_DIR}/${SOURCE_DATA_SUBDIR}"
# --- END MODIFICATION ---
SOURCE_ICON_FILENAME="zfs-gui.png"
SOURCE_POLICY_FILENAME="org.zfsgui.pkexec.daemon.launch.policy"
SOURCE_CREDENTIALS_FILENAME="credentials.json" # Added for default credentials
SOURCE_FLASK_KEY_FILENAME="flask_secret_key.txt" # Added for Flask secret key

# --- Installation Paths (System-wide) ---
INSTALL_BASE_DIR="/opt/${INSTALL_NAME}"
INSTALL_APP_SUBDIR="app" # Bundled app code goes here
INSTALL_DATA_SUBDIR="data" # Assets like icons go here (separate from app code)
INSTALL_ICON_SUBDIR="icons"
INSTALL_LAUNCHER_DIR="/usr/local/bin"
INSTALL_DESKTOP_DIR="/usr/share/applications"
INSTALL_POLICY_DIR="/usr/share/polkit-1/actions"

# --- Log File Paths (System-wide, typically in /tmp) ---
# These are cleaned up by the uninstaller if they exist.
SYSTEM_DAEMON_LOG_PATH="/tmp/${INSTALL_NAME}-daemon.log"
SYSTEM_DAEMON_STDERR_LOG_PATH="/tmp/${INSTALL_NAME}_daemon_stderr.log"
# User config (~/.config/ZfDash) and cache (~/.cache/ZfDash) are NOT handled here.

# --- ======================== ---
# --- === CONFIGURATION END ==== ---
# --- ======================== ---

# --- Calculated Paths ---
SOURCE_ICON_PATH="${SOURCE_DATA_DIR}/icons/${SOURCE_ICON_FILENAME}" # Icon source path from src/data
SOURCE_POLICY_PATH="${SOURCE_DATA_DIR}/policies/${SOURCE_POLICY_FILENAME}" # Policy source path from src/data
SOURCE_CREDENTIALS_PATH="${SOURCE_DATA_DIR}/${SOURCE_CREDENTIALS_FILENAME}" # Default credentials source path
SOURCE_FLASK_KEY_PATH="${SOURCE_DATA_DIR}/${SOURCE_FLASK_KEY_FILENAME}" # Flask key source path
INSTALL_APP_DIR="${INSTALL_BASE_DIR}/${INSTALL_APP_SUBDIR}" # Bundled app install location
INSTALL_DATA_DIR="${INSTALL_BASE_DIR}/${INSTALL_DATA_SUBDIR}" # Directory for installed assets
INSTALL_ICON_DIR="${INSTALL_DATA_DIR}/${INSTALL_ICON_SUBDIR}" # Directory for installed icons
INSTALLED_ICON_PATH="${INSTALL_ICON_DIR}/${SOURCE_ICON_FILENAME}" # Fixed icon install path
INSTALL_CREDENTIALS_PATH="${INSTALL_DATA_DIR}/${SOURCE_CREDENTIALS_FILENAME}" # Installed credentials path
INSTALL_FLASK_KEY_PATH="${INSTALL_DATA_DIR}/${SOURCE_FLASK_KEY_FILENAME}" # Installed Flask key path
INSTALL_LAUNCHER_PATH="${INSTALL_LAUNCHER_DIR}/${INSTALL_NAME}"
INSTALL_DESKTOP_FILE_PATH="${INSTALL_DESKTOP_DIR}/${INSTALL_NAME}.desktop"
INSTALL_POLICY_PATH="${INSTALL_POLICY_DIR}/${SOURCE_POLICY_FILENAME}"
UNINSTALL_SCRIPT_PATH="${INSTALL_BASE_DIR}/uninstall.sh"

# --- Helper Functions ---
_log_base() { local color_start="\033[0m"; local color_end="\033[0m"; local prefix="[INFO]"; case "$1" in INFO) prefix="[INFO]"; color_start="\033[0;34m";; WARN) prefix="[WARN]"; color_start="\033[0;33m";; ERROR) prefix="[ERROR]"; color_start="\033[0;31m";; *) prefix="[----]";; esac; printf "%b%s%b %s\n" "$color_start" "$prefix" "$color_end" "$2" >&2; }
log_info() { _log_base "INFO" "$1"; }
log_warn() { _log_base "WARN" "$1"; }
log_error() { _log_base "ERROR" "$1"; }
exit_error() { log_error "$1"; exit 1; }
command_exists() { command -v "$1" &> /dev/null; }

# --- Uninstall Function ---
uninstall_existing() {
    log_info "Attempting to remove existing ${APP_NAME} installation components..."
    local failed=false
    # Use explicit checks after each rm command
    if [ -f "$INSTALL_LAUNCHER_PATH" ]; then log_info " - Removing launcher: ${INSTALL_LAUNCHER_PATH}"; rm -f "$INSTALL_LAUNCHER_PATH"; if [ $? -ne 0 ]; then log_warn " Failed to remove launcher."; failed=true; fi; fi
    if [ -f "$INSTALL_DESKTOP_FILE_PATH" ]; then log_info " - Removing desktop entry: ${INSTALL_DESKTOP_FILE_PATH}"; rm -f "$INSTALL_DESKTOP_FILE_PATH"; if [ $? -ne 0 ]; then log_warn " Failed to remove desktop file."; failed=true; fi; fi
    if [ -f "$INSTALL_POLICY_PATH" ]; then log_info " - Removing Polkit policy: ${INSTALL_POLICY_PATH}"; rm -f "$INSTALL_POLICY_PATH"; if [ $? -ne 0 ]; then log_warn " Failed to remove policy file."; failed=true; fi; fi
    if [ -d "$INSTALL_BASE_DIR" ]; then
        log_info " - Removing application directory: ${INSTALL_BASE_DIR}"
        if [ -x "$UNINSTALL_SCRIPT_PATH" ]; then
            log_info "   INFO: Found existing uninstall script. Running it..."
            if ! "$UNINSTALL_SCRIPT_PATH"; then log_warn " Existing uninstall script failed. Removing directory forcefully."; rm -rf "$INSTALL_BASE_DIR"; if [ $? -ne 0 ]; then log_error " Failed to remove directory forcefully."; failed=true; fi; fi
            if [ -d "$INSTALL_BASE_DIR" ]; then log_warn " Existing uninstall did not remove directory. Removing now."; rm -rf "$INSTALL_BASE_DIR"; if [ $? -ne 0 ]; then log_error " Failed to remove directory."; failed=true; fi; fi
        else
             rm -rf "$INSTALL_BASE_DIR"; if [ $? -ne 0 ]; then log_error " Failed to remove directory: $INSTALL_BASE_DIR"; failed=true; fi
        fi
    fi
    log_info "Updating desktop database and icon caches (optional)..."
    if command_exists update-desktop-database && [ -d "$INSTALL_DESKTOP_DIR" ]; then update-desktop-database -q "$INSTALL_DESKTOP_DIR" || log_warn "update-desktop-database failed (non-critical)."; fi
    if command_exists gtk-update-icon-cache && [ -d "/usr/share/icons/hicolor" ]; then gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || log_warn "gtk-update-icon-cache failed (non-critical)."; fi

    if [ "$failed" = true ]; then log_error "Existing installation removal encountered errors."; return 1;
    else log_info "Existing installation removal attempt finished."; return 0; fi
}

# --- ============================== ---
# --- === INSTALLATION PHASE START === ---
# --- ============================== ---
echo ""
log_info "--- Starting ${APP_NAME} Installation Process (Version ${APP_VERSION}) ---"

# 1. Check Root Privileges
log_info "Checking for root privileges..."
if [ "$(id -u)" -ne 0 ]; then
    exit_error "Installation requires root privileges. Please run this script with 'sudo ${BASH_SOURCE[0]}'."
fi
log_info "Running as root. Proceeding..."

# 2. Verify Source Build Directory Exists
log_info "Verifying presence of pre-built application..."
if [ ! -d "$SOURCE_BUNDLED_APP_DIR" ]; then
    exit_error "Bundled application directory not found at expected location: ${SOURCE_BUNDLED_APP_DIR}\nPlease run the build script (build.sh) first."
fi
if [ ! -f "${SOURCE_BUNDLED_APP_DIR}/${APP_EXECUTABLE_NAME}" ]; then
    exit_error "Main executable not found within bundled directory: ${SOURCE_BUNDLED_APP_DIR}/${APP_EXECUTABLE_NAME}"
fi
# --- MODIFICATION: Remove the check for bundled data dir ---
# We no longer rely on this check, we copy assets from source later.
# --- END MODIFICATION ---
log_info "Found bundled application: ${SOURCE_BUNDLED_APP_DIR}"
# --- MODIFICATION: Check source icon and policy exist ---
if [ ! -f "$SOURCE_ICON_PATH" ]; then
    log_warn "Source icon file not found at ${SOURCE_ICON_PATH}. Desktop entry icon may be missing."
fi
if [ ! -f "$SOURCE_POLICY_PATH" ]; then
    exit_error "Source Polkit policy file not found: ${SOURCE_POLICY_PATH}. Cannot proceed."
fi
# --- END MODIFICATION ---
# --- MODIFICATION: Check source credentials exist ---
if [ ! -f "$SOURCE_CREDENTIALS_PATH" ]; then
    log_warn "Source credentials file not found at ${SOURCE_CREDENTIALS_PATH}. Default credentials will not be installed. The daemon will create a default if needed."
fi
# --- END MODIFICATION ---

# 3. Check/Offer Uninstall Existing
log_info "Checking for existing installation..."
if [ -d "$INSTALL_BASE_DIR" ] || [ -f "$INSTALL_LAUNCHER_PATH" ] || [ -f "$INSTALL_DESKTOP_FILE_PATH" ] || [ -f "$INSTALL_POLICY_PATH" ]; then
    log_warn "An existing ${APP_NAME} installation or leftover components were found."; read -p "Do you want to remove the existing components before installing? (y/N): " remove_confirm
    if [[ "$remove_confirm" =~ ^[Yy]$ ]]; then log_info "Uninstalling existing version..."; if ! uninstall_existing; then exit_error "Uninstall of existing version failed. Aborting installation."; fi; log_info "Existing components removed.";
    else log_warn "Proceeding without removing existing components. This might cause issues."; sleep 2; fi
else log_info "No existing installation found."; fi


# 4. Create Installation Directories
log_info "Creating installation directories..."
# --- MODIFICATION: Create app, data, and icon dirs explicitly ---
mkdir -vp "$INSTALL_BASE_DIR" "$INSTALL_APP_DIR" "$INSTALL_ICON_DIR" "$INSTALL_LAUNCHER_DIR" "$INSTALL_DESKTOP_DIR" || exit_error "Failed to create installation directories."
# --- END MODIFICATION ---


# 5. Copy Bundled Application Code
log_info "Copying bundled application code from ${SOURCE_BUNDLED_APP_DIR} to ${INSTALL_APP_DIR}..."
# This rsync command copies the *contents* of SOURCE_BUNDLED_APP_DIR into INSTALL_APP_DIR
if ! rsync -a --delete "${SOURCE_BUNDLED_APP_DIR}/" "${INSTALL_APP_DIR}/"; then exit_error "Failed to copy bundled application files."; fi
log_info "Application code copied."


# 6. Copy Data Files (Icon) from Source Tree to Fixed Location
# --- MODIFICATION: Copy icon from source to fixed install location ---
if [ -f "$SOURCE_ICON_PATH" ]; then
    log_info "Copying icon file from ${SOURCE_ICON_PATH} to ${INSTALL_ICON_DIR}...";
    cp -v "$SOURCE_ICON_PATH" "${INSTALL_ICON_DIR}/" || log_warn "Failed to copy icon file to ${INSTALL_ICON_DIR}.";
else
    log_warn "Source icon file not found at ${SOURCE_ICON_PATH}, skipping icon copy.";
fi
# --- END MODIFICATION ---


# 7. Install Polkit Policy from Source Tree
if [ ! -d "$INSTALL_POLICY_DIR" ]; then log_warn "System policy directory does not exist: $INSTALL_POLICY_DIR. Creating..."; mkdir -p "$INSTALL_POLICY_DIR" || log_warn "Failed to create policy dir."; fi
# Ensure policy is copied from the correct source path
if [ -f "$SOURCE_POLICY_PATH" ]; then
    log_info "Installing Polkit policy file from ${SOURCE_POLICY_PATH} to $INSTALL_POLICY_PATH...";
    if cp -v "$SOURCE_POLICY_PATH" "$INSTALL_POLICY_PATH"; then
        log_info "Polkit policy file copied successfully. Permissions will be set later.";
    else
        log_warn "Failed to copy Polkit policy file.";
    fi
else
    exit_error "Source Polkit policy file not found: ${SOURCE_POLICY_PATH}";
fi

# 7b. Install Default Credentials File from Source Tree
if [ -f "$SOURCE_CREDENTIALS_PATH" ]; then
    log_info "Installing default credentials file from ${SOURCE_CREDENTIALS_PATH} to ${INSTALL_DATA_DIR}..."
    # Ensure the target data directory exists (created in step 4)
    if [ ! -d "$INSTALL_DATA_DIR" ]; then
        log_warn "Installation data directory ${INSTALL_DATA_DIR} does not exist. Creating..."
        mkdir -p "$INSTALL_DATA_DIR" || log_warn "Failed to create data directory."
    fi
    # Copy the file
    if cp -v "$SOURCE_CREDENTIALS_PATH" "$INSTALL_CREDENTIALS_PATH"; then
        log_info "Default credentials file copied successfully. Permissions will be set later.";
    else
        log_warn "Failed to copy default credentials file.";
    fi
else
    log_info "Source credentials file not found at ${SOURCE_CREDENTIALS_PATH}, skipping installation.";
    log_info "The daemon will create a default file if necessary on first run.";
fi

# 7c. Generate and Install Flask Secret Key
log_info "Generating and installing Flask secret key..."
# Ensure the target data directory exists (created in step 4)
if [ ! -d "$INSTALL_DATA_DIR" ]; then
    log_warn "Installation data directory ${INSTALL_DATA_DIR} does not exist. Creating..."
    mkdir -p "$INSTALL_DATA_DIR" || log_warn "Failed to create data directory."
fi

# Generate a random 64-character secret key
if command_exists openssl; then
    FLASK_SECRET_KEY=$(openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 64)
else
    # Fallback if openssl is not available
    FLASK_SECRET_KEY=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 64)
fi

# Write the key to the file
if echo "${FLASK_SECRET_KEY}" > "${INSTALL_FLASK_KEY_PATH}"; then
    log_info "Generated Flask secret key and saved to ${INSTALL_FLASK_KEY_PATH}."
    log_info "Secret key will have permissions set to 644 later during permissions phase."
else
    log_warn "Failed to save Flask secret key to ${INSTALL_FLASK_KEY_PATH}."
    log_warn "Web UI will use fallback key. For production use, consider manually setting FLASK_SECRET_KEY environment variable."
fi


# 8. Create Launcher Script (No changes needed here)
log_info "Creating launcher script at $INSTALL_LAUNCHER_PATH..."
INSTALLED_EXECUTABLE_PATH="${INSTALL_APP_DIR}/${APP_EXECUTABLE_NAME}"
cat > "$INSTALL_LAUNCHER_PATH" <<EOF
#!/bin/bash
# Launcher for ${APP_NAME} (${INSTALL_NAME}) - Version ${APP_VERSION}
APP_EXECUTABLE="${INSTALLED_EXECUTABLE_PATH}"
export QT_ENABLE_HIGHDPI_SCALING="1"; export QT_AUTO_SCREEN_SCALE_FACTOR="1"
if [ ! -x "\$APP_EXECUTABLE" ]; then
    echo "ERROR: ${APP_NAME} executable not found or not executable at '\$APP_EXECUTABLE'" >&2
    if command -v zenity &> /dev/null; then zenity --error --text="ERROR: ${APP_NAME} executable not found at\\n\$APP_EXECUTABLE\\n\\nPlease reinstall the application." --title="${APP_NAME} Error";
    elif command -v kdialog &> /dev/null; then kdialog --error "ERROR: ${APP_NAME} executable not found at\\n\$APP_EXECUTABLE\\n\\nPlease reinstall the application." --title "${APP_NAME} Error"; fi
    exit 1; fi
exec "\$APP_EXECUTABLE" "\$@"; echo "ERROR: Failed to execute ${APP_NAME} at '\$APP_EXECUTABLE'." >&2; exit 1
EOF
if [ $? -ne 0 ]; then exit_error "Failed to write launcher script content."; fi
log_info "Launcher script content written. Permissions will be set later.";


# 9. Create Desktop Entry
log_info "Creating desktop entry at $INSTALL_DESKTOP_FILE_PATH..."
# --- MODIFICATION: Use the fixed INSTALLED_ICON_PATH ---
ICON_LINE=""; if [ -f "$INSTALLED_ICON_PATH" ]; then ICON_LINE="Icon=${INSTALLED_ICON_PATH}"; else log_warn "Installed icon file not found at ${INSTALLED_ICON_PATH}."; ICON_LINE="# Icon=${INSTALL_NAME}"; fi
# --- END MODIFICATION ---
cat > "$INSTALL_DESKTOP_FILE_PATH" <<EOF
[Desktop Entry]
Version=1.5.4
Name=${APP_NAME}
GenericName=ZFS Manager
Comment=ZFS pool, dataset, and snapshot management GUI/WebUI
Exec=${INSTALL_NAME} %F
${ICON_LINE}
Terminal=false
Type=Application
Categories=System;Utility;Administration
Keywords=ZFS;GUI;Admin;Pool;Dataset;Snapshot;Storage;Filesystem;Volume;
StartupNotify=true
StartupWMClass=${APP_NAME}
EOF
if [ $? -ne 0 ]; then exit_error "Failed to write desktop entry content."; fi
log_info "Desktop entry content written. Permissions will be set later.";



# 10. Create Uninstall Script
log_info "Creating uninstall script at $UNINSTALL_SCRIPT_PATH..."
# --- MODIFICATION: Uninstall script removes the base dir, which includes the copied icon and credentials ---
cat > "$UNINSTALL_SCRIPT_PATH" <<EOF
#!/bin/bash
# Uninstaller script for ${APP_NAME}
echo "--- ${APP_NAME} Uninstaller ---"; set +e # Allow errors during removal
INSTALL_BASE_DIR="${INSTALL_BASE_DIR}"; INSTALL_LAUNCHER_PATH="${INSTALL_LAUNCHER_PATH}"
INSTALL_DESKTOP_FILE_PATH="${INSTALL_DESKTOP_FILE_PATH}"; INSTALL_POLICY_PATH="${INSTALL_POLICY_PATH}"
# Add log paths to be used within the uninstall script
SYSTEM_DAEMON_LOG_PATH="${SYSTEM_DAEMON_LOG_PATH}"
SYSTEM_DAEMON_STDERR_LOG_PATH="${SYSTEM_DAEMON_STDERR_LOG_PATH}"
# INSTALL_CREDENTIALS_PATH is implicitly removed when INSTALL_BASE_DIR is removed.
# No explicit removal needed here unless it moves outside INSTALL_BASE_DIR later.
if [ "\$(id -u)" -ne 0 ]; then echo "ERROR: Must run as root/sudo." >&2; exit 1; fi
echo "This script will remove:"; echo " - App dir:      \${INSTALL_BASE_DIR}"; echo " - Launcher:     \${INSTALL_LAUNCHER_PATH}"
echo " - Desktop file:  \${INSTALL_DESKTOP_FILE_PATH}"; echo " - Polkit policy: \${INSTALL_POLICY_PATH}"; echo ""
read -p "Are you sure? (y/N): " confirm; if [[ ! "\$confirm" =~ ^[Yy]$ ]]; then echo "Uninstall cancelled."; exit 0; fi
echo "INFO: Removing application directory: \${INSTALL_BASE_DIR}..." # This removes icons and credentials too
if [ -d "\${INSTALL_BASE_DIR}" ]; then rm -rf "\${INSTALL_BASE_DIR}"; else echo "INFO: App directory already removed."; fi
echo "INFO: Removing launcher script: \${INSTALL_LAUNCHER_PATH}..."; if [ -f "\${INSTALL_LAUNCHER_PATH}" ]; then rm -f "\${INSTALL_LAUNCHER_PATH}"; else echo "INFO: Launcher already removed."; fi
echo "INFO: Removing desktop entry: \${INSTALL_DESKTOP_FILE_PATH}..."; if [ -f "\${INSTALL_DESKTOP_FILE_PATH}" ]; then rm -f "\${INSTALL_DESKTOP_FILE_PATH}"; else echo "INFO: Desktop entry already removed."; fi
echo "INFO: Removing Polkit policy: \${INSTALL_POLICY_PATH}..."; if [ -f "\${INSTALL_POLICY_PATH}" ]; then rm -f "\${INSTALL_POLICY_PATH}"; else echo "INFO: Polkit policy already removed."; fi

# Attempt to remove potential system-wide log files (defined above)
echo "INFO: Checking for system daemon log file: \${SYSTEM_DAEMON_LOG_PATH}..."
if [ -f "\${SYSTEM_DAEMON_LOG_PATH}" ]; then echo "INFO: Removing \${SYSTEM_DAEMON_LOG_PATH}..."; rm -f "\${SYSTEM_DAEMON_LOG_PATH}" || echo "WARN: Failed to remove \${SYSTEM_DAEMON_LOG_PATH}." >&2; fi
echo "INFO: Checking for system daemon stderr log file: \${SYSTEM_DAEMON_STDERR_LOG_PATH}..."
if [ -f "\${SYSTEM_DAEMON_STDERR_LOG_PATH}" ]; then echo "INFO: Removing \${SYSTEM_DAEMON_STDERR_LOG_PATH}..."; rm -f "\${SYSTEM_DAEMON_STDERR_LOG_PATH}" || echo "WARN: Failed to remove \${SYSTEM_DAEMON_STDERR_LOG_PATH}." >&2; fi

echo "INFO: Updating desktop database (optional)..."
if command -v update-desktop-database &> /dev/null && [ -d "\$(dirname "\${INSTALL_DESKTOP_FILE_PATH}")" ]; then update-desktop-database -q "\$(dirname "\${INSTALL_DESKTOP_FILE_PATH}")" || echo "Warning: update-desktop-database failed." >&2; fi
if command -v gtk-update-icon-cache &> /dev/null && [ -d "/usr/share/icons/hicolor" ]; then gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || echo "Warning: gtk-update-icon-cache failed." >&2; fi

echo ""
echo "NOTE: User-specific configuration (~/.config/ZfDash) and cache (~/.cache/ZfDash) are NOT removed by this script."
echo "      You may need to remove them manually if they exist."

echo "" && echo "--- ${APP_NAME} Uninstallation Complete ---"; exit 0
EOF
if [ $? -ne 0 ]; then exit_error "Failed to write uninstall script content."; fi
log_info "Uninstall script content written. Permissions will be set later.";


# 11. Set Final Permissions for Installation Directory
log_info "Setting final permissions for installation files and directories..."

# Set ownership/permissions for files OUTSIDE the main installation directory first
log_info " - Setting permissions for system-wide files..."
if [ -f "$INSTALL_LAUNCHER_PATH" ]; then
    chown root:root "$INSTALL_LAUNCHER_PATH" || log_warn "Failed setting owner on launcher: $INSTALL_LAUNCHER_PATH"
    chmod 755 "$INSTALL_LAUNCHER_PATH" || log_warn "Failed setting 755 permission on launcher: $INSTALL_LAUNCHER_PATH"
fi
if [ -f "$INSTALL_DESKTOP_FILE_PATH" ]; then
    chown root:root "$INSTALL_DESKTOP_FILE_PATH" || log_warn "Failed setting owner on desktop file: $INSTALL_DESKTOP_FILE_PATH"
    chmod 644 "$INSTALL_DESKTOP_FILE_PATH" || log_warn "Failed setting 644 permission on desktop file: $INSTALL_DESKTOP_FILE_PATH"
fi
if [ -f "$INSTALL_POLICY_PATH" ]; then
    chown root:root "$INSTALL_POLICY_PATH" || log_warn "Failed setting owner on policy file: $INSTALL_POLICY_PATH"
    chmod 644 "$INSTALL_POLICY_PATH" || log_warn "Failed setting 644 permission on policy file: $INSTALL_POLICY_PATH"
fi

# Set ownership/permissions for files INSIDE the main installation directory
log_info " - Setting permissions for application directory: ${INSTALL_BASE_DIR}..."
if chown -R root:root "$INSTALL_BASE_DIR"; then
    # ---------Set base directory permissions (755)---------
    find "$INSTALL_BASE_DIR" -type d -exec chmod 755 {} \; || log_warn "Failed setting base directory permissions."
    # ---------Set default file permissions (644)---------
    find "$INSTALL_BASE_DIR" -type f -exec chmod 644 {} \; || log_warn "Failed setting default file permissions."
    #------------------------------------------------------

    # Apply specific permissions overrides within the base directory:
    log_info "   - Applying specific overrides within ${INSTALL_BASE_DIR}..."
    # - Bundled executable (755)
    if [ -f "${INSTALL_APP_DIR}/${APP_EXECUTABLE_NAME}" ]; then
        chmod 755 "${INSTALL_APP_DIR}/${APP_EXECUTABLE_NAME}" || log_warn "Failed setting executable permission on main app: ${INSTALL_APP_DIR}/${APP_EXECUTABLE_NAME}"
    fi
    # - Credentials file (644) - for now 644! (strong hash) web_ui runs as user!
    if [ -f "$INSTALL_CREDENTIALS_PATH" ]; then
        chmod 644 "$INSTALL_CREDENTIALS_PATH" || log_warn "Failed setting 644 permission on credentials file: $INSTALL_CREDENTIALS_PATH"
    fi
    # - Flask secret key file (644) - web_ui runs as user and needs to read this
    if [ -f "$INSTALL_FLASK_KEY_PATH" ]; then
        chmod 644 "$INSTALL_FLASK_KEY_PATH" || log_warn "Failed setting 644 permission on Flask secret key file: $INSTALL_FLASK_KEY_PATH"
    fi
    # - Uninstall script (755) - Overrides the find above (will be created in the next step)
    if [ -f "$UNINSTALL_SCRIPT_PATH" ]; then # Check just in case, though it's created after this section
        chmod 755 "$UNINSTALL_SCRIPT_PATH" || log_warn "Failed setting executable permission on uninstaller: $UNINSTALL_SCRIPT_PATH"
    fi
    log_info "All application directory permissions set."
else
    log_warn "Failed to set base ownership on $INSTALL_BASE_DIR. Permissions might be incorrect.";
fi


#Final Steps
# Update Desktop/Icon Caches After Install
log_info "Updating desktop database and icon caches (optional)..."
if command_exists update-desktop-database && [ -d "$INSTALL_DESKTOP_DIR" ]; then update-desktop-database -q "$INSTALL_DESKTOP_DIR" || log_warn "update-desktop-database command failed."; fi
if command_exists gtk-update-icon-cache && [ -d "/usr/share/icons/hicolor" ]; then gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || log_warn "gtk-update-icon-cache command failed."; fi

# --- Final Message ---
echo ""
log_info "--- ${APP_NAME} Installation Complete ---"
echo ""
# Check if executable exists before showing message
if [ -f "${INSTALL_APP_DIR}/${APP_EXECUTABLE_NAME}" ]; then
    echo "Installed To:        ${INSTALL_BASE_DIR}"
    echo "Bundled App Exec:  ${INSTALL_APP_DIR}/${APP_EXECUTABLE_NAME}"
    echo "Launcher Command:  ${INSTALL_NAME}"
    echo "Launcher Path:     ${INSTALL_LAUNCHER_PATH}"
    echo "Desktop Entry:     ${INSTALL_DESKTOP_FILE_PATH}"
    echo "Icon Location:     ${INSTALLED_ICON_PATH}" # Shows the fixed path
    echo "Credentials:     ${INSTALL_CREDENTIALS_PATH} (if installed from source)" # Added info
    echo "Flask Secret Key: ${INSTALL_FLASK_KEY_PATH}" # Added info
    echo ""
    echo "You should now find '${APP_NAME}' in your application menu or run '${INSTALL_NAME}' from the terminal."
    echo "To uninstall, run: sudo ${UNINSTALL_SCRIPT_PATH}"
else
    log_error "Installation finished, but main executable seems missing!"
    log_error "Please check installation logs. Location: ${INSTALL_APP_DIR}/${APP_EXECUTABLE_NAME}"
fi
echo ""
log_info "--- Installation Phase Finished ---"

exit 0
# --- ============================ ---
# --- === INSTALLATION PHASE END === ---
# --- ============================ ---
