#!/usr/bin/env bash
#
# get-zfdash.sh - Automated installer for ZfDash
#
# Detects system/architecture, downloads the latest release,
# extracts it, and runs the installer.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/ad4mts/zfdash/main/get-zfdash.sh | bash
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check for required tools
for cmd in curl tar sudo; do
    if ! command -v $cmd &> /dev/null; then
        log_error "$cmd is required but not installed. Aborting."
        exit 1
    fi
done

# 1. Detect System and Architecture
log_info "Detecting system..."

OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m | tr '[:upper:]' '[:lower:]')

# Map OS names to match release naming convention
case "$OS" in
    linux)
        OS_NAME="linux"
        ;;
    darwin)
        OS_NAME="macos"
        ;;
    freebsd)
        OS_NAME="freebsd"
        ;;
    *)
        log_error "Unsupported OS: $OS"
        exit 1
        ;;
esac

# Map Architecture names
case "$ARCH" in
    x86_64|amd64)
        ARCH_NAME="x86_64"
        ;;
    aarch64|arm64|armv8*)
        ARCH_NAME="arm64"
        ;;
    armv7*)
        ARCH_NAME="armv7"
        ;;
    i386|i686)
        ARCH_NAME="x86"
        ;;
    *)
        log_error "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

PLATFORM_TAG="${OS_NAME}-${ARCH_NAME}"
log_info "Detected platform: ${PLATFORM_TAG}"

# 2. Get Latest Release URL
log_info "Fetching latest release info from GitHub..."

REPO="ad4mts/zfdash"
API_URL="https://api.github.com/repos/${REPO}/releases/latest"

# Fetch release data
RELEASE_JSON=$(curl -sSL "${API_URL}")

# Check if we got valid JSON
if [[ -z "$RELEASE_JSON" ]] || [[ "$RELEASE_JSON" == *"Not Found"* ]]; then
    log_error "Failed to fetch release info. Check your internet connection or GitHub API limits."
    exit 1
fi

# Extract version tag
VERSION_TAG=$(echo "$RELEASE_JSON" | grep '"tag_name":' | sed -E 's/.*"tag_name": "([^"]+)".*/\1/')

if [[ -z "$VERSION_TAG" ]]; then
    log_error "Could not determine latest version tag."
    exit 1
fi

log_info "Latest version: ${VERSION_TAG}"

# Construct expected asset name pattern
# Pattern: zfdash-(version)-(os)-(arch).tar.gz
# Note: version in filename usually doesn't have 'v' prefix if tag has it, but let's check asset list
# Actually, generate_tarball.py uses: zfdash-{version}-{system}-{arch}.tar.gz
# And version usually comes from version.py (e.g., 1.8.8-beta)
# The tag might be v1.8.8-beta.

# Find the asset URL that matches our platform
DOWNLOAD_URL=$(echo "$RELEASE_JSON" | grep "browser_download_url" | grep "${PLATFORM_TAG}.tar.gz" | head -n 1 | sed -E 's/.*"browser_download_url": "([^"]+)".*/\1/')

if [[ -z "$DOWNLOAD_URL" ]]; then
    log_error "No release asset found for platform: ${PLATFORM_TAG}"
    log_info "Available assets:"
    echo "$RELEASE_JSON" | grep "name" | grep ".tar.gz"
    exit 1
fi

FILENAME=$(basename "$DOWNLOAD_URL")

# 3. Download and Extract
TMP_DIR=$(mktemp -d)
log_info "Downloading ${FILENAME}..."

if curl -L --progress-bar -o "${TMP_DIR}/${FILENAME}" "${DOWNLOAD_URL}"; then
    log_success "Download complete."
else
    log_error "Download failed."
    rm -rf "${TMP_DIR}"
    exit 1
fi

log_info "Extracting..."
tar -xzf "${TMP_DIR}/${FILENAME}" -C "${TMP_DIR}"

# Find the extracted directory (it should be the only directory in extracted root, or files are at root)
# generate_tarball.py creates a tarball with files at root (no top-level folder) OR with a folder?
# Let's check generate_tarball.py...
# "tar -czf "${tar_name}" -C "${release_dir}" ." -> It archives the CONTENTS of release_dir.
# So extracting it will dump files into the current directory.
# We should extract into a specific folder to avoid mess.

EXTRACT_DIR="${TMP_DIR}/zfdash_install"
mkdir -p "${EXTRACT_DIR}"
tar -xzf "${TMP_DIR}/${FILENAME}" -C "${EXTRACT_DIR}"

# 4. Run Installer
log_info "Running installer..."

if [[ -f "${EXTRACT_DIR}/install.sh" ]]; then
    chmod +x "${EXTRACT_DIR}/install.sh"
    
    # We need to run install.sh from its directory because it might use relative paths
    cd "${EXTRACT_DIR}"
    
    if sudo ./install.sh; then
        log_success "Installation complete!"
        log_info "You can now run 'zfdash' from your application menu or terminal."
    else
        log_error "Installation failed."
        exit 1
    fi
else
    log_error "install.sh not found in the downloaded archive."
    ls -la "${EXTRACT_DIR}"
    exit 1
fi

# Cleanup
cd /
rm -rf "${TMP_DIR}"
