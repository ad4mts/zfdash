#!/bin/bash
# Uninstallation script for ZfDash Web UI systemd service

# --- Strict Mode ---
set -euo pipefail

# --- Configuration ---
APP_NAME="ZfDash"
SERVICE_NAME="zfdash-web"
ENV_DIR="/etc/zfdash"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
DEDICATED_USER="zfdash"
DEDICATED_GROUP="zfdash"

# --- Helper Functions ---
_log_base() { local color_start="\033[0m"; local color_end="\033[0m"; local prefix="[INFO]"; case "$1" in INFO) prefix="[INFO]"; color_start="\033[0;34m";; WARN) prefix="[WARN]"; color_start="\033[0;33m";; ERROR) prefix="[ERROR]"; color_start="\033[0;31m";; *) prefix="[----]";; esac; printf "%b%s%b %s\n" "$color_start" "$prefix" "$color_end" "$2" >&2; }
log_info() { _log_base "INFO" "$1"; }
log_warn() { _log_base "WARN" "$1"; }
log_error() { _log_base "ERROR" "$1"; }
exit_error() { log_error "$1"; exit 1; }
command_exists() { command -v "$1" &> /dev/null; }

# --- Main Script ---
echo ""
log_info "--- Starting ${APP_NAME} Web UI Service Uninstallation ---"

# 1. Check Root Privileges
log_info "Checking for root privileges..."
if [ "$(id -u)" -ne 0 ]; then
    exit_error "Uninstallation requires root privileges. Please run this script with 'sudo ${BASH_SOURCE[0]}'."
fi
log_info "Running as root. Proceeding..."

# 2. Stop and Disable Service
if systemctl list-unit-files | grep -qw "^${SERVICE_NAME}.service"; then
    log_info "Stopping service '${SERVICE_NAME}'..."
    systemctl stop "${SERVICE_NAME}.service" || log_warn "Failed to stop service (maybe not running?)."
    log_info "Disabling service '${SERVICE_NAME}'..."
    systemctl disable "${SERVICE_NAME}.service" || log_warn "Failed to disable service (maybe not enabled?)."
else
    log_info "Service '${SERVICE_NAME}' not found in systemd."
fi

# 3. Remove Service File
if [ -f "${SERVICE_FILE}" ]; then
    log_info "Removing systemd service file: ${SERVICE_FILE}"
    rm -f "${SERVICE_FILE}"
else
    log_info "Systemd service file already removed."
fi

# 4. Remove Environment Directory
if [ -d "${ENV_DIR}" ]; then
    log_info "Removing environment directory: ${ENV_DIR}"
    rm -rf "${ENV_DIR}"
else
    log_info "Environment directory already removed."
fi

# 5. Remove Polkit Rules File
RULES_FILE="/etc/polkit-1/rules.d/45-zfdash-admin.rules"
if [ -f "${RULES_FILE}" ]; then
    log_info "Removing Polkit rules file: ${RULES_FILE}"
    rm -f "${RULES_FILE}"
else
    log_info "Polkit rules file already removed."
fi

# 6. Reload Systemd Daemon
log_info "Reloading systemd daemon..."
systemctl daemon-reload

# 7. Optionally Remove Dedicated User/Group
if id "${DEDICATED_USER}" > /dev/null 2>&1; then
    log_info "Found dedicated service user '${DEDICATED_USER}'."
    read -p "Do you want to remove the user '${DEDICATED_USER}' and group '${DEDICATED_GROUP}'? (y/N): " remove_user_confirm
    if [[ "$remove_user_confirm" =~ ^[Yy]$ ]]; then
        # Detect admin group again to remove user from it
        ADMIN_GROUP=""
        if getent group sudo > /dev/null; then ADMIN_GROUP="sudo";
        elif getent group wheel > /dev/null; then ADMIN_GROUP="wheel"; fi

        if [ -n "${ADMIN_GROUP}" ]; then
            log_info "Removing user '${DEDICATED_USER}' from group '${ADMIN_GROUP}'..."
            # gpasswd is generally safer for removing from secondary groups
            if groups "${DEDICATED_USER}" | grep -qw "${ADMIN_GROUP}"; then
                gpasswd -d "${DEDICATED_USER}" "${ADMIN_GROUP}" || log_warn "Could not remove user from ${ADMIN_GROUP}."
            else
                log_info "User '${DEDICATED_USER}' is not in group '${ADMIN_GROUP}', skipping removal from group."
            fi
        fi

        log_info "Attempting to kill any remaining processes for user '${DEDICATED_USER}'..."
        # Try pkill first, then killall as a fallback if pkill isn't available
        if command_exists pkill; then
            pkill -u "${DEDICATED_USER}" && sleep 2 || log_warn "pkill failed or no processes found for user ${DEDICATED_USER}."
        elif command_exists killall; then
            killall -u "${DEDICATED_USER}" && sleep 2 || log_warn "killall failed or no processes found for user ${DEDICATED_USER}."
        else
            log_warn "Neither pkill nor killall found. Cannot automatically kill user processes. Manual intervention might be needed if user deletion fails."
        fi

        log_info "Removing user '${DEDICATED_USER}'..."
        if userdel "${DEDICATED_USER}"; then
            log_info "User '${DEDICATED_USER}' removed successfully."
            # Remove dedicated group only if it exists and the user was successfully removed
            if getent group "${DEDICATED_GROUP}" > /dev/null; then
                # Check if group is empty before removing (it should be now)
                if [ -z "$(getent group "${DEDICATED_GROUP}" | cut -d: -f4)" ]; then
                    log_info "Removing group '${DEDICATED_GROUP}'..."
                    groupdel "${DEDICATED_GROUP}" || log_warn "Failed to remove group '${DEDICATED_GROUP}'."
                else
                    log_warn "Group '${DEDICATED_GROUP}' is not empty after user removal? Not removing group."
                fi
            fi
        else
            log_warn "Failed to remove user '${DEDICATED_USER}'. Check for running processes or manual locks."
            log_warn "Group '${DEDICATED_GROUP}' will not be removed as the user still exists."
        fi
    else
        log_info "Skipping removal of user/group '${DEDICATED_USER}'."
    fi
fi

echo ""
log_info "--- ${APP_NAME} Web UI Service Uninstallation Complete ---"
echo ""
exit 0 