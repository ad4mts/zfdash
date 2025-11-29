#!/bin/bash
# Uninstaller script for ZfDash
echo "--- ZfDash Uninstaller ---"
set +e # Allow errors during removal

INSTALL_BASE_DIR="/opt/zfdash"
INSTALL_DATA_DIR="${INSTALL_BASE_DIR}/data"
INSTALL_LAUNCHER_PATH="/usr/local/bin/zfdash"
INSTALL_DESKTOP_FILE_PATH="/usr/share/applications/zfdash.desktop"
INSTALL_POLICY_PATH="/usr/share/polkit-1/actions/org.zfsgui.pkexec.daemon.launch.policy"
# Log paths/patterns
SYSTEM_DAEMON_LOG_PATTERN="/tmp/zfdash-daemon.log*"
SYSTEM_DAEMON_STDERR_LOG_PATH="/tmp/zfdash_daemon_stderr.log"

if [ "$(id -u)" -ne 0 ]; then echo "ERROR: Must run as root/sudo." >&2; exit 1; fi

echo "This script will remove:"
echo " - App dir:       ${INSTALL_BASE_DIR}"
echo " - Launcher:      ${INSTALL_LAUNCHER_PATH}"
echo " - Desktop file:  ${INSTALL_DESKTOP_FILE_PATH}"
echo " - Polkit policy: ${INSTALL_POLICY_PATH}"
echo ""

read -p "Are you sure you want to uninstall ZfDash? (y/N): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then echo "Uninstall cancelled."; exit 0; fi

# Ask about preserving credentials/config data
PRESERVE_DATA=false
if [ -d "${INSTALL_DATA_DIR}" ]; then
    echo ""
    echo "The data directory contains credentials and configuration:"
    echo "  ${INSTALL_DATA_DIR}"
    read -p "Do you want to KEEP your credentials and configuration? (Y/n): " keep_data
    if [[ ! "$keep_data" =~ ^[Nn]$ ]]; then
        PRESERVE_DATA=true
        echo "INFO: Credentials and configuration will be preserved."
    else
        echo "INFO: Credentials and configuration will be REMOVED."
    fi
fi

echo ""
echo "INFO: Removing application files..."

if [ -d "${INSTALL_BASE_DIR}" ]; then
    if [ "$PRESERVE_DATA" = true ] && [ -d "${INSTALL_DATA_DIR}" ]; then
        # Preserve data directory - remove everything else in INSTALL_BASE_DIR
        echo "INFO: Preserving data directory: ${INSTALL_DATA_DIR}"
        # Move data dir temporarily
        TEMP_DATA_DIR="/tmp/zfdash_data_backup_$$"
        mv "${INSTALL_DATA_DIR}" "${TEMP_DATA_DIR}"
        # Remove everything else
        rm -rf "${INSTALL_BASE_DIR}"
        # Recreate base dir and restore data
        mkdir -p "${INSTALL_BASE_DIR}"
        mv "${TEMP_DATA_DIR}" "${INSTALL_DATA_DIR}"
        echo "INFO: Application removed, data preserved at ${INSTALL_DATA_DIR}"
    else
        # Remove everything including data
        rm -rf "${INSTALL_BASE_DIR}"
        echo "INFO: Application directory removed: ${INSTALL_BASE_DIR}"
    fi
else
    echo "INFO: App directory already removed."
fi

echo "INFO: Removing launcher script: ${INSTALL_LAUNCHER_PATH}..."
if [ -f "${INSTALL_LAUNCHER_PATH}" ]; then rm -f "${INSTALL_LAUNCHER_PATH}"; else echo "INFO: Launcher already removed."; fi

echo "INFO: Removing desktop entry: ${INSTALL_DESKTOP_FILE_PATH}..."
if [ -f "${INSTALL_DESKTOP_FILE_PATH}" ]; then rm -f "${INSTALL_DESKTOP_FILE_PATH}"; else echo "INFO: Desktop entry already removed."; fi

echo "INFO: Removing Polkit policy: ${INSTALL_POLICY_PATH}..."
if [ -f "${INSTALL_POLICY_PATH}" ]; then rm -f "${INSTALL_POLICY_PATH}"; else echo "INFO: Polkit policy already removed."; fi

# Remove log files
echo "INFO: Checking for daemon log files..."
rm -f ${SYSTEM_DAEMON_LOG_PATTERN} 2>/dev/null && echo "INFO: Removed daemon log files." || true
if [ -f "${SYSTEM_DAEMON_STDERR_LOG_PATH}" ]; then
    rm -f "${SYSTEM_DAEMON_STDERR_LOG_PATH}" || echo "WARN: Failed to remove ${SYSTEM_DAEMON_STDERR_LOG_PATH}." >&2
fi

echo "INFO: Updating desktop database (optional)..."
if command -v update-desktop-database &> /dev/null && [ -d "$(dirname "${INSTALL_DESKTOP_FILE_PATH}")" ]; then
    update-desktop-database -q "$(dirname "${INSTALL_DESKTOP_FILE_PATH}")" || echo "Warning: update-desktop-database failed." >&2
fi
if command -v gtk-update-icon-cache &> /dev/null && [ -d "/usr/share/icons/hicolor" ]; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || echo "Warning: gtk-update-icon-cache failed." >&2
fi

echo ""
echo "NOTE: User-specific configuration (~/.config/ZfDash) and cache (~/.cache/ZfDash) are NOT removed by this script."
echo "      You may need to remove them manually if they exist."
if [ "$PRESERVE_DATA" = true ]; then
    echo ""
    echo "NOTE: Your credentials and configuration were preserved at: ${INSTALL_DATA_DIR}"
    echo "      To remove them later: sudo rm -rf ${INSTALL_DATA_DIR}"
fi

echo ""
echo "--- ZfDash Uninstallation Complete ---"
exit 0
