#!/bin/bash
# Build script for ZfDash
# Uses uv with uv.lock and .python-version for reproducible builds.
#
# Usage: ./build.sh [--yes|-y] [--clean]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

#######################################
# Parse Arguments
#######################################
AUTO_YES=false
CLEAN_BUILD=false

for arg in "$@"; do
    case "$arg" in
        --yes|-y) AUTO_YES=true ;;
        --clean) CLEAN_BUILD=true ;;
        --help|-h)
            echo "Usage: $0 [--yes|-y] [--clean]"
            echo "  --yes, -y   Skip confirmation prompts (for CI)"
            echo "  --clean     Remove .venv and rebuild from scratch"
            exit 0
            ;;
    esac
done

#######################################
# Helpers
#######################################
log_info()  { printf '\033[0;34m[INFO]\033[0m %s\n' "$*"; }
log_error() { printf '\033[0;31m[ERROR]\033[0m %s\n' "$*" >&2; }
exit_error() { log_error "$1"; exit 1; }

#######################################
# Install uv if needed
#######################################
if ! command -v uv &>/dev/null; then
    log_info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    command -v uv &>/dev/null || exit_error "Failed to install uv"
fi

#######################################
# Checks
#######################################
[[ "$(id -u)" -eq 0 ]] && exit_error "Don't run as root"
[[ -f "pyproject.toml" ]] || exit_error "pyproject.toml not found"
[[ -f "uv.lock" ]] || exit_error "uv.lock not found - run 'uv lock' first"
[[ -d "src" ]] || exit_error "src/ directory not found"

VERSION=$(grep -oP '__version__\s*=\s*["\047]\K[^"\047]+' src/version.py 2>/dev/null || echo "unknown")
log_info "=== ZfDash Build (v${VERSION}) ==="

#######################################
# Clean if requested
#######################################
if [[ "$CLEAN_BUILD" == true ]]; then
    log_info "Cleaning build environment..."
    rm -rf .venv build dist
fi

#######################################
# Sync environment (creates venv if needed, uses .python-version)
#######################################
log_info "Syncing dependencies..."
uv sync --extra dev

#######################################
# Build with PyInstaller
#######################################
log_info "Building with PyInstaller..."
rm -rf build dist

uv run python -m PyInstaller \
    --noconfirm \
    --distpath dist \
    --workpath build \
    --name zfdash \
    src/main.py

#######################################
# Verify
#######################################
[[ -f "dist/zfdash/zfdash" ]] || exit_error "Build failed: dist/zfdash/zfdash not found"

log_info "=== Build Complete ==="
log_info "Output: dist/zfdash/"
log_info "Run 'sudo ./install.sh' to install"
