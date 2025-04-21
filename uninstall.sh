#!/bin/bash
# Uninstaller script for ZfDash
echo "--- ZfDash Uninstaller ---"; set +e # Allow errors during removal
INSTALL_BASE_DIR="/opt/zfdash"; INSTALL_LAUNCHER_PATH="/usr/local/bin/zfdash"
INSTALL_DESKTOP_FILE_PATH="/usr/share/applications/zfdash.desktop"; INSTALL_POLICY_PATH="/usr/share/polkit-1/actions/org.zfsgui.pkexec.daemon.launch.policy"
# Add log paths to be used within the uninstall script
SYSTEM_DAEMON_LOG_PATH="/tmp/zfdash-daemon.log"
SYSTEM_DAEMON_STDERR_LOG_PATH="/tmp/zfdash_daemon_stderr.log"
# INSTALL_CREDENTIALS_PATH is implicitly removed when INSTALL_BASE_DIR is removed.
# No explicit removal needed here unless it moves outside INSTALL_BASE_DIR later.
if [ "$(id -u)" -ne 0 ]; then echo "ERROR: Must run as root/sudo." >&2; exit 1; fi
echo "This script will remove:"; echo " - App dir:      ${INSTALL_BASE_DIR}"; echo " - Launcher:     ${INSTALL_LAUNCHER_PATH}"
echo " - Desktop file:  ${INSTALL_DESKTOP_FILE_PATH}"; echo " - Polkit policy: ${INSTALL_POLICY_PATH}"; echo ""
read -p "Are you sure? (y/N): " confirm; if [[ ! "$confirm" =~ ^[Yy]$ ]]; then echo "Uninstall cancelled."; exit 0; fi
echo "INFO: Removing application directory: ${INSTALL_BASE_DIR}..." # This removes icons and credentials too
if [ -d "${INSTALL_BASE_DIR}" ]; then rm -rf "${INSTALL_BASE_DIR}"; else echo "INFO: App directory already removed."; fi
echo "INFO: Removing launcher script: ${INSTALL_LAUNCHER_PATH}..."; if [ -f "${INSTALL_LAUNCHER_PATH}" ]; then rm -f "${INSTALL_LAUNCHER_PATH}"; else echo "INFO: Launcher already removed."; fi
echo "INFO: Removing desktop entry: ${INSTALL_DESKTOP_FILE_PATH}..."; if [ -f "${INSTALL_DESKTOP_FILE_PATH}" ]; then rm -f "${INSTALL_DESKTOP_FILE_PATH}"; else echo "INFO: Desktop entry already removed."; fi
echo "INFO: Removing Polkit policy: ${INSTALL_POLICY_PATH}..."; if [ -f "${INSTALL_POLICY_PATH}" ]; then rm -f "${INSTALL_POLICY_PATH}"; else echo "INFO: Polkit policy already removed."; fi

# Attempt to remove potential system-wide log files (defined above)
echo "INFO: Checking for system daemon log file: ${SYSTEM_DAEMON_LOG_PATH}..."
if [ -f "${SYSTEM_DAEMON_LOG_PATH}" ]; then echo "INFO: Removing ${SYSTEM_DAEMON_LOG_PATH}..."; rm -f "${SYSTEM_DAEMON_LOG_PATH}" || echo "WARN: Failed to remove ${SYSTEM_DAEMON_LOG_PATH}." >&2; fi
echo "INFO: Checking for system daemon stderr log file: ${SYSTEM_DAEMON_STDERR_LOG_PATH}..."
if [ -f "${SYSTEM_DAEMON_STDERR_LOG_PATH}" ]; then echo "INFO: Removing ${SYSTEM_DAEMON_STDERR_LOG_PATH}..."; rm -f "${SYSTEM_DAEMON_STDERR_LOG_PATH}" || echo "WARN: Failed to remove ${SYSTEM_DAEMON_STDERR_LOG_PATH}." >&2; fi

echo "INFO: Updating desktop database (optional)..."
if command -v update-desktop-database &> /dev/null && [ -d "$(dirname "${INSTALL_DESKTOP_FILE_PATH}")" ]; then update-desktop-database -q "$(dirname "${INSTALL_DESKTOP_FILE_PATH}")" || echo "Warning: update-desktop-database failed." >&2; fi
if command -v gtk-update-icon-cache &> /dev/null && [ -d "/usr/share/icons/hicolor" ]; then gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || echo "Warning: gtk-update-icon-cache failed." >&2; fi

echo ""
echo "NOTE: User-specific configuration (~/.config/ZfDash) and cache (~/.cache/ZfDash) are NOT removed by this script."
echo "      You may need to remove them manually if they exist."

echo "" && echo "--- ZfDash Uninstallation Complete ---"; exit 0
