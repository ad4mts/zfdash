#!/bin/bash
# ZfDash Uninstaller
# Cleanly removes ZfDash with option to preserve user data
# Usage: sudo ./uninstall.sh [-y]
#   -y  Skip confirmation prompts (auto-yes, preserves data by default)

set +e  # Allow errors during removal

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
INSTALL_DIR="/opt/zfdash"
INSTALL_DATA_DIR="${INSTALL_DIR}/data"
INSTALL_LAUNCHER="/usr/local/bin/zfdash"
INSTALL_DESKTOP="/usr/share/applications/zfdash.desktop"
INSTALL_POLICY="/usr/share/polkit-1/actions/org.zfsgui.pkexec.daemon.launch.policy"
LOG_PATTERNS=("/tmp/zfdash-daemon.log*" "/tmp/zfdash_daemon_stderr.log")

# ============================================================================
# LOGGING (matches install.sh style)
# ============================================================================

log_info()  { printf "\033[0;34m[INFO]\033[0m  %s\n" "$1" >&2; }
log_ok()    { printf "\033[0;32m[OK]\033[0m    %s\n" "$1" >&2; }
log_warn()  { printf "\033[0;33m[WARN]\033[0m  %s\n" "$1" >&2; }
log_error() { printf "\033[0;31m[ERROR]\033[0m %s\n" "$1" >&2; }

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

check_root() {
    if [[ $(id -u) -ne 0 ]]; then
        log_error "This script must be run as root. Use: sudo $0"
        exit 1
    fi
}

is_interactive() {
    [[ -t 0 ]] && [[ "$AUTO_YES" == "false" ]]
}

confirm_prompt() {
    local prompt="$1" default="$2" response
    if is_interactive; then
        read -p "$prompt" response
        [[ -z "$response" ]] && response="$default"
    else
        response="$default"
        [[ "$AUTO_YES" == "true" ]] && log_info "Auto-yes mode: using default ($default)"
    fi
    [[ "$response" =~ ^[Yy]$ ]]
}

# ============================================================================
# REMOVAL FUNCTIONS
# ============================================================================

remove_file() {
    local path="$1" desc="$2"
    if [[ -f "$path" ]] || [[ -L "$path" ]]; then
        rm -f "$path" && log_ok "Removed $desc"
    fi
}

remove_app_directory() {
    local preserve_data="$1"
    
    if [[ ! -d "$INSTALL_DIR" ]]; then
        log_info "Application directory already removed"
        return
    fi
    
    if [[ "$preserve_data" == "true" ]] && [[ -d "$INSTALL_DATA_DIR" ]]; then
        log_info "Preserving user data..."
        local temp_dir="/tmp/zfdash_data_backup_$$"
        mv "$INSTALL_DATA_DIR" "$temp_dir"
        rm -rf "$INSTALL_DIR"
        mkdir -p "$INSTALL_DIR"
        mv "$temp_dir" "$INSTALL_DATA_DIR"
        log_ok "Application removed (data preserved at $INSTALL_DATA_DIR)"
    else
        rm -rf "$INSTALL_DIR"
        log_ok "Application directory removed"
    fi
}

remove_logs() {
    local removed=false
    for pattern in "${LOG_PATTERNS[@]}"; do
        # shellcheck disable=SC2086
        if ls $pattern &>/dev/null 2>&1; then
            rm -f $pattern && removed=true
        fi
    done
    [[ "$removed" == "true" ]] && log_ok "Log files removed"
}

update_caches() {
    command -v update-desktop-database &>/dev/null && update-desktop-database -q /usr/share/applications 2>/dev/null || true
    command -v gtk-update-icon-cache &>/dev/null && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    echo ""
    log_info "=== ${APP_NAME} Uninstaller ==="
    echo ""
    
    check_root
    
    # Show what will be removed
    echo "This will remove:"
    echo "  • Application:   $INSTALL_DIR"
    echo "  • Launcher:      $INSTALL_LAUNCHER"
    echo "  • Desktop entry: $INSTALL_DESKTOP"
    echo "  • Polkit policy: $INSTALL_POLICY"
    echo ""
    
    # Confirm uninstall
    if ! confirm_prompt "Uninstall ${APP_NAME}? (y/N): " "n"; then
        log_info "Uninstall cancelled"
        exit 0
    fi
    
    # Ask about preserving data
    local preserve_data="false"
    if [[ -d "$INSTALL_DATA_DIR" ]]; then
        echo ""
        log_warn "Data directory contains credentials: $INSTALL_DATA_DIR"
        if confirm_prompt "Keep credentials and configuration? (Y/n): " "y"; then
            preserve_data="true"
            log_info "User data will be preserved"
        else
            log_info "User data will be removed"
        fi
    fi
    
    echo ""
    log_info "Removing ${APP_NAME}..."
    
    # Remove components
    remove_app_directory "$preserve_data"
    remove_file "$INSTALL_LAUNCHER" "launcher"
    remove_file "$INSTALL_DESKTOP" "desktop entry"
    remove_file "$INSTALL_POLICY" "polkit policy"
    remove_logs
    update_caches
    
    # Summary
    echo ""
    log_ok "=== Uninstall Complete ==="
    echo ""
    echo "  Note: User config (~/.config/ZfDash) and cache (~/.cache/ZfDash)"
    echo "        are not removed. Delete manually if needed."
    if [[ "$preserve_data" == "true" ]]; then
        echo ""
        echo "  Your data was preserved at: $INSTALL_DATA_DIR"
        echo "  To remove: sudo rm -rf $INSTALL_DATA_DIR"
    fi
    echo ""
}

main "$@"
