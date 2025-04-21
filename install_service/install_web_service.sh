#!/bin/bash
# Installation script for ZfDash Web UI systemd service

# --- Strict Mode ---
set -euo pipefail

# --- ========================== ---
# --- === CONFIGURATION START ==== ---
# --- ========================== ---

APP_NAME="ZfDash"
INSTALL_NAME="zfdash"
SERVICE_NAME="zfdash-web"
ENV_DIR="/etc/zfdash"
ENV_FILE="${ENV_DIR}/web.env"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
INSTALL_BASE_DIR="/opt/${INSTALL_NAME}"
INSTALLED_APP_DIR="${INSTALL_BASE_DIR}/app"
INSTALLED_LAUNCHER="/usr/local/bin/${INSTALL_NAME}"

# --- Web Service Configuration ---
# --- !!! SECURITY WARNING !!! ---
# Binding the host to '0.0.0.0' will expose the ZfDash web interface
# to your entire network. This is a SIGNIFICANT security risk,
# especially if default credentials are not changed or if other
# vulnerabilities exist. ONLY change DEFAULT_WEB_HOST from '127.0.0.1'
# if you understand the risks and have properly secured your network
# (e.g., with a firewall).
DEFAULT_WEB_HOST="127.0.0.1" # Default to localhost only (recommended)
DEFAULT_WEB_PORT="5001"
# --- End Web Service Configuration ---

# --- ======================== ---
# --- === CONFIGURATION END ==== ---
# --- ======================== ---

# --- Helper Functions ---
_log_base() { local color_start="\033[0m"; local color_end="\033[0m"; local prefix="[INFO]"; case "$1" in INFO) prefix="[INFO]"; color_start="\033[0;34m";; WARN) prefix="[WARN]"; color_start="\033[0;33m";; ERROR) prefix="[ERROR]"; color_start="\033[0;31m";; *) prefix="[----]";; esac; printf "%b%s%b %s\n" "$color_start" "$prefix" "$color_end" "$2" >&2; }
log_info() { _log_base "INFO" "$1"; }
log_warn() { _log_base "WARN" "$1"; }
log_error() { _log_base "ERROR" "$1"; }
exit_error() { log_error "$1"; exit 1; }
command_exists() { command -v "$1" &> /dev/null; }

# --- Main Script --- 
echo ""
log_info "--- Starting ${APP_NAME} Web UI Service Installation ---"

# 1. Check Root Privileges
log_info "Checking for root privileges..."
if [ "$(id -u)" -ne 0 ]; then
    exit_error "Installation requires root privileges. Please run this script with 'sudo ${BASH_SOURCE[0]}'."
fi
log_info "Running as root. Proceeding..."

# 2. Check if main application seems installed
log_info "Checking for main ZfDash installation..."
if [ ! -x "${INSTALLED_LAUNCHER}" ]; then
    exit_error "ZfDash launcher '${INSTALLED_LAUNCHER}' not found or not executable. Please install ZfDash first using install.sh."
fi
log_info "Found ZfDash launcher."

# 3. Check if service already exists
if systemctl is-active --quiet "${SERVICE_NAME}.service" || systemctl is-enabled --quiet "${SERVICE_NAME}.service"; then
    log_warn "The '${SERVICE_NAME}' service appears to be already installed/active."
    read -p "Do you want to overwrite the existing service configuration? (y/N): " overwrite_confirm
    if [[ ! "$overwrite_confirm" =~ ^[Yy]$ ]]; then
        exit_error "Installation aborted by user."
    fi
    log_info "Proceeding with overwrite..."
    log_info "Stopping existing service (if running)..."
    systemctl stop "${SERVICE_NAME}.service" || true
fi

# 4. Detect Admin Group
ADMIN_GROUP=""
if getent group sudo > /dev/null; then
    ADMIN_GROUP="sudo"
    log_info "Detected 'sudo' group for Polkit permissions."
elif getent group wheel > /dev/null; then
    ADMIN_GROUP="wheel"
    log_info "Detected 'wheel' group for Polkit permissions."
else
    log_warn "Could not automatically detect 'sudo' or 'wheel' group."
    read -p "Please enter the admin group name for Polkit authorization: " ADMIN_GROUP
    if ! getent group "${ADMIN_GROUP}" > /dev/null; then
        exit_error "Group '${ADMIN_GROUP}' does not exist. Cannot proceed."
    fi
fi

# 5. Determine Service User
SERVICE_USER=""
SERVICE_GROUP=""
CREATE_ZFDASH_USER=false
ZFDASH_GROUP="zfdash" # Define the dedicated group name

# Ensure zfdash group exists
if ! getent group "${ZFDASH_GROUP}" > /dev/null; then
    log_info "Creating system group '${ZFDASH_GROUP}'..."
    groupadd --system "${ZFDASH_GROUP}" || exit_error "Failed to create group '${ZFDASH_GROUP}'."
fi

while true; do
    # Updated prompt to show default
    read -p "Run Web UI service as dedicated user '${ZFDASH_GROUP}' (default) or an existing user (less secure)? [${ZFDASH_GROUP}(default)/existing]: " user_choice
    # Set default if user presses Enter
    user_choice=${user_choice:-${ZFDASH_GROUP}}

    if [[ "$user_choice" =~ ^[Zz][Ff][Dd][Aa][Ss][Hh]$ ]]; then
        SERVICE_USER="${ZFDASH_GROUP}"
        # zfdash group already created/checked above
        SERVICE_GROUP="${ZFDASH_GROUP}"
        if ! id -u "${SERVICE_USER}" > /dev/null 2>&1; then
            log_info "Creating system user '${SERVICE_USER}' (group: ${SERVICE_GROUP}, no shell, no home dir)..."
            useradd --system -g "${SERVICE_GROUP}" -s /bin/false "${SERVICE_USER}" || exit_error "Failed to create user '${SERVICE_USER}'."
            CREATE_ZFDASH_USER=true
        else
            log_info "System user '${SERVICE_USER}' already exists."
        fi
        # REMOVED: No longer adding service user to admin group
        # log_info "Ensuring user '${SERVICE_USER}' is in admin group '${ADMIN_GROUP}'..."
        # usermod -a -G "${ADMIN_GROUP}" "${SERVICE_USER}" || log_warn "Failed to add '${SERVICE_USER}' to '${ADMIN_GROUP}'. Polkit auth might fail."
        # User is already in zfdash group by creation
        break
    elif [[ "$user_choice" =~ ^[Ee][Xx][Ii][Ss][Tt][Ii][Nn][Gg]$ ]]; then
        read -p "Enter the existing username: " existing_user
        if ! id "${existing_user}" > /dev/null 2>&1; then
            log_error "User '${existing_user}' does not exist. Please try again."
            continue
        fi
        if [ "$(id -u "${existing_user}")" -eq 0 ]; then
            log_error "Cannot run the service as the root user. Please choose a non-root user."
            continue
        fi
        SERVICE_USER="${existing_user}"
        SERVICE_GROUP=$(id -gn "${SERVICE_USER}") # Primary group
        # REMOVED: No longer adding service user to admin group
        # log_info "Ensuring user '${SERVICE_USER}' is in admin group '${ADMIN_GROUP}'..."
        # if ! groups "${SERVICE_USER}" | grep -qw "${ADMIN_GROUP}"; then
        #     usermod -a -G "${ADMIN_GROUP}" "${SERVICE_USER}" || log_warn "Failed to add '${SERVICE_USER}' to '${ADMIN_GROUP}'. Polkit auth might fail."
        #     log_warn "User '${SERVICE_USER}' may need to log out and back in fully apply group changes in some contexts."
        # else
        #     log_info "User '${SERVICE_USER}' is already in group '${ADMIN_GROUP}'."
        # fi
        log_info "Ensuring user '${SERVICE_USER}' is in dedicated group '${ZFDASH_GROUP}'..."
        if ! groups "${SERVICE_USER}" | grep -qw "${ZFDASH_GROUP}"; then
            usermod -a -G "${ZFDASH_GROUP}" "${SERVICE_USER}" || log_warn "Failed to add '${SERVICE_USER}' to '${ZFDASH_GROUP}'. Service functionality might be impaired." # Changed warning slightly
            log_warn "User '${SERVICE_USER}' may need to log out and back in fully apply group changes in some contexts."
        else
             log_info "User '${SERVICE_USER}' is already in group '${ZFDASH_GROUP}'."
        fi
        break
    else
        log_error "Invalid choice. Please enter '${ZFDASH_GROUP}' or 'existing'."
    fi
done

log_info "Service will run as User='${SERVICE_USER}', Group='${SERVICE_GROUP}'. User must be in group '${ZFDASH_GROUP}' for Polkit authorization." # Updated message

# 6. Prepare Environment File
log_info "Creating environment directory: ${ENV_DIR}"
mkdir -p "${ENV_DIR}"

log_info "Generating Flask secret key..."
FLASK_SECRET=$(command_exists openssl && openssl rand -hex 32 || date +%s | sha256sum | base64 | head -c 48)
if [ -z "${FLASK_SECRET}" ]; then exit_error "Failed to generate a Flask secret key."; fi

log_info "Creating environment file: ${ENV_FILE}"
cat > "${ENV_FILE}" << EOF
FLASK_SECRET_KEY='${FLASK_SECRET}'
# Add other Web UI environment variables here if needed
EOF

log_info "Setting permissions on ${ENV_FILE} (readable by root and group ${ZFDASH_GROUP})" # Updated message
chown root:"${ZFDASH_GROUP}" "${ENV_FILE}" # Changed ADMIN_GROUP to ZFDASH_GROUP
chmod 640 "${ENV_FILE}"

# 7. Determine Working Directory
WORKING_DIR=""
if [ "${SERVICE_USER}" == "zfdash" ]; then
    WORKING_DIR="${INSTALLED_APP_DIR}" # System user has no home
    log_info "Setting WorkingDirectory to ${WORKING_DIR} (system user)"
elif [ -d "/home/${SERVICE_USER}" ]; then
    WORKING_DIR="/home/${SERVICE_USER}"
    log_info "Setting WorkingDirectory to ${WORKING_DIR}"
elif [ -d "${INSTALLED_APP_DIR}" ]; then
    WORKING_DIR="${INSTALLED_APP_DIR}" # Fallback for existing user without standard home
    log_info "Setting WorkingDirectory to ${WORKING_DIR} (user home not found)"
else
    log_warn "Could not determine a suitable WorkingDirectory. Service might fail."
    WORKING_DIR="/"
fi

# 8. Create Polkit .rules file for passwordless access (javascript)
RULES_FILE="/etc/polkit-1/rules.d/45-zfdash-admin.rules"
log_info "Creating Polkit rules file: ${RULES_FILE}"
cat > "${RULES_FILE}" << EOF
polkit.addRule(function(action, subject) {
    if (action.id == "org.zfsgui.pkexec.daemon.launch" &&
        subject.isInGroup("${ZFDASH_GROUP}")) {
        return polkit.Result.YES;
    }
});
EOF
# Set permissions for the rules file (readable by all is standard)
chmod 644 "${RULES_FILE}"

# 9. Prompt for Web Host and Port
log_info "Configuring Web UI host and port..."
read -p "Enter the host address to bind the web service to. Press Enter for default [${DEFAULT_WEB_HOST}]: " WEB_HOST
WEB_HOST=${WEB_HOST:-${DEFAULT_WEB_HOST}} # Use default if empty

# --- SECURITY WARNING ---
if [[ "${WEB_HOST}" == "0.0.0.0" ]]; then
    log_warn "!!! SECURITY WARNING !!!"
    log_warn "Binding the host to '0.0.0.0' will expose the ZfDash web interface"
    log_warn "to your entire network. This is a SIGNIFICANT security risk,"
    log_warn "especially if default credentials are not changed or if other"
    log_warn "vulnerabilities exist. Ensure your system/network is secured (e.g., firewall)."
    read -p "Are you sure you want to bind to 0.0.0.0? (y/N): " confirm_bind_all
    if [[ ! "$confirm_bind_all" =~ ^[Yy]$ ]]; then
        exit_error "Installation aborted due to security concerns. Consider using '127.0.0.1' or a specific internal IP."
    fi
fi
# --- End Security Warning ---


read -p "Enter the port number for the web service. Press Enter for default [${DEFAULT_WEB_PORT}]: " WEB_PORT
WEB_PORT=${WEB_PORT:-${DEFAULT_WEB_PORT}} # Use default if empty

# Validate port number (basic check)
if ! [[ "$WEB_PORT" =~ ^[0-9]+$ ]] || [ "$WEB_PORT" -lt 1 ] || [ "$WEB_PORT" -gt 65535 ]; then
    exit_error "Invalid port number: '${WEB_PORT}'. Must be between 1 and 65535."
fi

log_info "Web service will listen on ${WEB_HOST}:${WEB_PORT}"

# 10. Create systemd Service File
log_info "Creating systemd service file: ${SERVICE_FILE}"
cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=${APP_NAME} Web UI Service (User: ${SERVICE_USER})
After=network-online.target zfs.target #graphical.target removed
Wants=network-online.target zfs.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${ZFDASH_GROUP}

# Required for Polkit interaction
#PAMName=login # Commented out: Can cause errors on server systems without full graphical sessions, Polkit rule relies on groups.
# Environment=DISPLAY=:0 # Commented out: Not typically needed for non-graphical service using Polkit rules for authorization.
# Note: XAUTHORITY path might need adjustment based on display manager
# Common paths: /run/user/%U/gdm/Xauthority, /run/user/%U/lightdm/Xauthority, or user's ~/.Xauthority
# Trying a common default, may need manual edit if Polkit fails.
# Environment=XAUTHORITY=/run/user/%U/gdm/Xauthority # Commented out: See DISPLAY explanation.

EnvironmentFile=${ENV_FILE}

WorkingDirectory=${WORKING_DIR}

# Use the installed launcher script with configured host/port
ExecStart=${INSTALLED_LAUNCHER} --web --host ${WEB_HOST} --port ${WEB_PORT}

Restart=on-failure
RestartSec=5s

# Optional: Limit resource usage (example)
# CPUQuota=50%
# MemoryMax=512M

[Install]
WantedBy=multi-user.target
EOF

# 11. Reload, Enable, and Start Service
log_info "Reloading systemd daemon..."
systemctl daemon-reload

log_info "Enabling ${SERVICE_NAME} service to start on boot..."
systemctl enable "${SERVICE_NAME}.service"

log_info "Starting ${SERVICE_NAME} service..."
if systemctl start "${SERVICE_NAME}.service"; then
    log_info "Service started successfully."
    sleep 2 # Give service a moment to potentially fail
    log_info "Current service status:"
    systemctl status "${SERVICE_NAME}.service" --no-pager || true
    echo ""
    log_info "--- ${APP_NAME} Web UI Service Installation Complete ---"
    log_info "Access the Web UI typically at http://<your-server-ip>:5001"
    log_info "To view logs: sudo journalctl -u ${SERVICE_NAME} -f"
    log_info "To stop service: sudo systemctl stop ${SERVICE_NAME}"
    log_info "To start service: sudo systemctl start ${SERVICE_NAME}"
echo ""
else
    log_error "Service '${SERVICE_NAME}' failed to start!"
    log_error "Check the service status for details: sudo systemctl status ${SERVICE_NAME}"
    log_error "Check the logs for errors: sudo journalctl -u ${SERVICE_NAME}"
    exit 1
fi

exit 0 
