#!/bin/bash
# ZfDash Installation Script
# Supports: fresh install, upgrade, manual install, and get-zfdash.sh automated install
# Preserves user credentials and configuration during upgrades
# Usage: sudo ./install.sh [-y]
#   -y  Skip confirmation prompts (auto-yes)

set -u -o pipefail

# ============================================================================
# CONFIGURATION
# ============================================================================

AUTO_YES=false
while getopts "y" opt; do
    case $opt in
        y) AUTO_YES=true ;;
        *) ;;
    esac
done

APP_NAME="ZfDash"
INSTALL_NAME="zfdash"
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)

# Source paths (from build output and source tree)
BUILD_DIST_DIR="${SCRIPT_DIR}/dist"
SOURCE_APP_DIR="${BUILD_DIST_DIR}/${INSTALL_NAME}"
SOURCE_DATA_DIR="${SCRIPT_DIR}/src/data"
SOURCE_TEMPLATES_DIR="${SCRIPT_DIR}/src/templates"
SOURCE_STATIC_DIR="${SCRIPT_DIR}/src/static"

# Installation paths
INSTALL_DIR="/opt/${INSTALL_NAME}"
INSTALL_DATA_DIR="${INSTALL_DIR}/data"
INSTALL_LAUNCHER="/usr/local/bin/${INSTALL_NAME}"
INSTALL_DESKTOP="/usr/share/applications/${INSTALL_NAME}.desktop"
INSTALL_POLICY="/usr/share/polkit-1/actions/org.zfsgui.pkexec.daemon.launch.policy"

# Files that should be preserved during upgrades (user-modifiable)
PRESERVE_FILES=(
    "data/credentials.json"
    "data/flask_secret_key.txt"
)

# ============================================================================
# LOGGING
# ============================================================================

log_info()  { printf "\033[0;34m[INFO]\033[0m  %s\n" "$1" >&2; }
log_ok()    { printf "\033[0;32m[OK]\033[0m    %s\n" "$1" >&2; }
log_warn()  { printf "\033[0;33m[WARN]\033[0m  %s\n" "$1" >&2; }
log_error() { printf "\033[0;31m[ERROR]\033[0m %s\n" "$1" >&2; }
die()       { log_error "$1"; exit 1; }

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

get_version() {
    local version_file="${SCRIPT_DIR}/src/version.py"
    if [[ -f "$version_file" ]]; then
        grep -oP '__version__\s*=\s*["\x27]\K[^"\x27]+' "$version_file" 2>/dev/null || echo "unknown"
    else
        echo "unknown"
    fi
}

check_root() {
    if [[ $(id -u) -ne 0 ]]; then
        die "This script must be run as root. Use: sudo $0"
    fi
}

check_daemon_running() {
    # Check for any running ZfDash processes (daemon, GUI, or web)
    if pgrep -f "zfs_daemon|zfdash|main\.py.*zfdash" &>/dev/null; then
        log_warn "ZfDash process detected running."
        log_warn "It's recommended to stop it before installing/upgrading."
        if [[ -t 0 ]] && [[ "$AUTO_YES" == "false" ]]; then
            read -p "Continue anyway? (y/N): " response
            [[ "$response" =~ ^[Yy]$ ]] || { log_info "Installation cancelled."; exit 0; }
        else
            log_warn "Auto mode: proceeding despite process running."
        fi
    fi
}

check_build_exists() {
    [[ -d "$SOURCE_APP_DIR" ]] || die "Build not found at $SOURCE_APP_DIR. Run build.sh first."
    [[ -x "${SOURCE_APP_DIR}/${INSTALL_NAME}" ]] || die "Executable not found: ${SOURCE_APP_DIR}/${INSTALL_NAME}"
    [[ -d "$SOURCE_DATA_DIR" ]] || die "Source data directory not found: $SOURCE_DATA_DIR"
}

# ============================================================================
# UPGRADE HANDLING - Preserve user data
# ============================================================================

backup_user_data() {
    # Backup user-modified files before upgrade
    BACKUP_DIR=""
    if [[ -d "$INSTALL_DIR" ]]; then
        for file in "${PRESERVE_FILES[@]}"; do
            local src="${INSTALL_DIR}/${file}"
            if [[ -f "$src" ]]; then
                if [[ -z "$BACKUP_DIR" ]]; then
                    BACKUP_DIR=$(mktemp -d "/tmp/zfdash-backup.XXXXXX")
                    log_info "Backing up user data to $BACKUP_DIR"
                fi
                local dest="${BACKUP_DIR}/${file}"
                mkdir -p "$(dirname "$dest")"
                cp -p "$src" "$dest"
                log_info "  - Backed up: $file"
            fi
        done
    fi
}

restore_user_data() {
    # Restore user-modified files after upgrade
    if [[ -n "${BACKUP_DIR:-}" ]] && [[ -d "$BACKUP_DIR" ]]; then
        log_info "Restoring user data..."
        for file in "${PRESERVE_FILES[@]}"; do
            local src="${BACKUP_DIR}/${file}"
            local dest="${INSTALL_DIR}/${file}"
            if [[ -f "$src" ]]; then
                mkdir -p "$(dirname "$dest")"
                cp -p "$src" "$dest"
                log_info "  - Restored: $file"
            fi
        done
        rm -rf "$BACKUP_DIR"
    fi
}

# ============================================================================
# CLEANUP FUNCTIONS
# ============================================================================

remove_old_installation() {
    # Remove previous installation files (data already backed up)
    log_info "Removing previous installation..."
    
    [[ -f "$INSTALL_LAUNCHER" ]] && rm -f "$INSTALL_LAUNCHER"
    [[ -f "$INSTALL_DESKTOP" ]] && rm -f "$INSTALL_DESKTOP"
    [[ -f "$INSTALL_POLICY" ]] && rm -f "$INSTALL_POLICY"
    
    if [[ -d "$INSTALL_DIR" ]]; then
        rm -rf "$INSTALL_DIR"
    fi
}

# ============================================================================
# INSTALLATION FUNCTIONS
# ============================================================================

install_application() {
    log_info "Installing application bundle..."
    mkdir -p "$INSTALL_DIR"
    
    # Copy PyInstaller bundle (executable + _internal/)
    rsync -a "${SOURCE_APP_DIR}/" "${INSTALL_DIR}/" --exclude='data'
    log_ok "Application bundle installed"
}

install_resources() {
    log_info "Installing resources..."
    
    # Templates
    if [[ -d "$SOURCE_TEMPLATES_DIR" ]]; then
        rsync -a "${SOURCE_TEMPLATES_DIR}/" "${INSTALL_DIR}/templates/"
        log_ok "Templates installed"
    else
        log_warn "Templates not found at $SOURCE_TEMPLATES_DIR"
    fi
    
    # Static files
    if [[ -d "$SOURCE_STATIC_DIR" ]]; then
        rsync -a "${SOURCE_STATIC_DIR}/" "${INSTALL_DIR}/static/"
        log_ok "Static files installed"
    else
        log_warn "Static files not found at $SOURCE_STATIC_DIR"
    fi
    
    # Data directory - icons, policies, and default configs
    mkdir -p "$INSTALL_DATA_DIR"
    
    # Always update icons and policies (system files, not user data)
    if [[ -d "${SOURCE_DATA_DIR}/icons" ]]; then
        rsync -a "${SOURCE_DATA_DIR}/icons/" "${INSTALL_DATA_DIR}/icons/"
    fi
    if [[ -d "${SOURCE_DATA_DIR}/policies" ]]; then
        rsync -a "${SOURCE_DATA_DIR}/policies/" "${INSTALL_DATA_DIR}/policies/"
    fi
    
    # Copy default data files only if they don't exist (preserve user modifications)
    for file in credentials.json update_instructions.json; do
        local src="${SOURCE_DATA_DIR}/${file}"
        local dest="${INSTALL_DATA_DIR}/${file}"
        if [[ -f "$src" ]] && [[ ! -f "$dest" ]]; then
            cp "$src" "$dest"
            log_info "  - Created default: $file"
        fi
    done
    
    log_ok "Resources installed"
}

generate_flask_secret() {
    local key_file="${INSTALL_DATA_DIR}/flask_secret_key.txt"
    if [[ ! -f "$key_file" ]]; then
        log_info "Generating Flask secret key..."
        if command -v openssl &>/dev/null; then
            openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 64 > "$key_file"
        else
            head -c 64 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 64 > "$key_file"
        fi
        log_ok "Flask secret key generated"
    fi
}

install_polkit_policy() {
    log_info "Installing Polkit policy..."
    local policy_src="${INSTALL_DATA_DIR}/policies/org.zfsgui.pkexec.daemon.launch.policy"
    
    if [[ -f "$policy_src" ]]; then
        mkdir -p "$(dirname "$INSTALL_POLICY")"
        # Use symlink for easier updates
        ln -sf "$policy_src" "$INSTALL_POLICY"
        log_ok "Polkit policy installed"
    else
        log_warn "Policy file not found, skipping"
    fi
}

create_launcher() {
    local version="$1"
    log_info "Creating launcher script..."
    
    cat > "$INSTALL_LAUNCHER" <<EOF
#!/bin/bash
# Launcher for ${APP_NAME} v${version}
export QT_ENABLE_HIGHDPI_SCALING=1
export QT_AUTO_SCREEN_SCALE_FACTOR=1
exec "${INSTALL_DIR}/${INSTALL_NAME}" "\$@"
EOF
    chmod 755 "$INSTALL_LAUNCHER"
    log_ok "Launcher created at $INSTALL_LAUNCHER"
}

create_desktop_entry() {
    local version="$1"
    local icon_path="${INSTALL_DATA_DIR}/icons/zfs-gui.png"
    log_info "Creating desktop entry..."
    
    cat > "$INSTALL_DESKTOP" <<EOF
[Desktop Entry]
Version=${version}
Name=${APP_NAME}
GenericName=ZFS Manager
Comment=ZFS pool, dataset, and snapshot management GUI/WebUI
Exec=${INSTALL_NAME}
Icon=${icon_path}
Terminal=false
Type=Application
Categories=System;Utility;Administration;
Keywords=ZFS;GUI;Admin;Pool;Dataset;Snapshot;Storage;
StartupNotify=true
StartupWMClass=${APP_NAME}
EOF
    chmod 644 "$INSTALL_DESKTOP"
    log_ok "Desktop entry created"
}

copy_uninstaller() {
    local src="${SCRIPT_DIR}/uninstall.sh"
    local dest="${INSTALL_DIR}/uninstall.sh"
    if [[ -f "$src" ]]; then
        cp "$src" "$dest"
        chmod 755 "$dest"
        log_ok "Uninstaller copied"
    fi
}

set_permissions() {
    log_info "Setting permissions..."
    
    # Application directory ownership
    chown -R root:root "$INSTALL_DIR"
    
    # Directories: 755
    find "$INSTALL_DIR" -type d -exec chmod 755 {} \;
    
    # Files: 644 by default
    find "$INSTALL_DIR" -type f -exec chmod 644 {} \;
    
    # Executables: 755
    chmod 755 "${INSTALL_DIR}/${INSTALL_NAME}"
    [[ -f "${INSTALL_DIR}/uninstall.sh" ]] && chmod 755 "${INSTALL_DIR}/uninstall.sh"
    
    # External files ownership (already have correct permissions from create_* functions)
    chown root:root "$INSTALL_LAUNCHER" 2>/dev/null || true
    chown root:root "$INSTALL_DESKTOP" 2>/dev/null || true
    # Policy is a symlink - chown would affect target, not needed
    
    log_ok "Permissions set"
}

update_caches() {
    log_info "Updating system caches..."
    command -v update-desktop-database &>/dev/null && update-desktop-database -q /usr/share/applications 2>/dev/null || true
    command -v gtk-update-icon-cache &>/dev/null && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    local version
    version=$(get_version)
    
    echo ""
    log_info "=== ${APP_NAME} Installer v${version} ==="
    echo ""
    
    # Pre-flight checks
    check_root
    check_daemon_running
    check_build_exists
    
    # Detect upgrade vs fresh install and handle accordingly
    if [[ -d "$INSTALL_DIR" ]]; then
        log_info "Existing installation detected - upgrading..."
        backup_user_data
        remove_old_installation
    else
        log_info "Fresh installation..."
    fi
    
    # Install
    install_application
    install_resources
    restore_user_data # only does anything if backup exists (i.e. during upgrade)
    generate_flask_secret # only creates if missing
    install_polkit_policy
    create_launcher "$version"
    create_desktop_entry "$version"
    copy_uninstaller
    set_permissions
    update_caches
    
    # Done
    echo ""
    log_ok "=== Installation Complete ==="
    echo ""
    echo "  Install location: ${INSTALL_DIR}"
    echo "  Run command:      ${INSTALL_NAME}"
    echo "  Uninstall:        sudo ${INSTALL_DIR}/uninstall.sh"
    echo ""
}

main "$@"
