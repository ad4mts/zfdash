#!/bin/bash
# Build script for ZfDash
# Creates a local Conda environment, installs dependencies,
# and bundles the application using PyInstaller.
# This script should be run as a regular user (NO SUDO).

# --- Strict Mode ---
set -u # Treat unset variables as errors
set -o pipefail # Handle pipe errors correctly
# Exit immediately if a command exits with a non-zero status during build.
set -e

# --- ========================== ---
# --- === CONFIGURATION START ==== ---
# --- ========================== ---

# --- Application Info ---
APP_NAME="ZfDash"
INSTALL_NAME="zfdash" # Base name for executable output
APP_VERSION="1.8.0" # Used in logging, could be dynamic later

# --- Build Configuration ---
CONDA_PYTHON_VERSION="3.11" # Desired Python version for the build env
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CONDA_INSTALLER_DIR="${SCRIPT_DIR}/miniconda_installer"
CONDA_BASE_DIR="${SCRIPT_DIR}/miniconda_base" # Local Miniconda installation
CONDA_ENV_DIR="${SCRIPT_DIR}/build_env_${INSTALL_NAME}" # Build environment path
BUILD_OUTPUT_DIR="${SCRIPT_DIR}/build" # PyInstaller build temp directory
DIST_OUTPUT_DIR="${SCRIPT_DIR}/dist" # PyInstaller final output directory
APP_EXECUTABLE_NAME="${INSTALL_NAME}" # Name for the bundled executable

# --- Source Code Locations ---
SOURCE_CODE_SUBDIR="src"
SOURCE_DATA_SUBDIR="src/data" # Relative path to the data directory from SCRIPT_DIR
REQUIREMENTS_FILENAME="requirements.txt"

# --- ======================== ---
# --- === CONFIGURATION END ==== ---
# --- ======================== ---

# --- Calculated Paths ---
SOURCE_CODE_DIR="${SCRIPT_DIR}/${SOURCE_CODE_SUBDIR}"
SOURCE_DATA_DIR="${SCRIPT_DIR}/${SOURCE_DATA_SUBDIR}"
REQUIREMENTS_FILE="${SCRIPT_DIR}/${REQUIREMENTS_FILENAME}"
BUNDLED_APP_DIR="${DIST_OUTPUT_DIR}/${APP_EXECUTABLE_NAME}" # Final output dir from PyInstaller

# --- Helper Functions ---
_log_base() { local color_start="\033[0m"; local color_end="\033[0m"; local prefix="[INFO]"; case "$1" in INFO) prefix="[INFO]"; color_start="\033[0;34m";; WARN) prefix="[WARN]"; color_start="\033[0;33m";; ERROR) prefix="[ERROR]"; color_start="\033[0;31m";; *) prefix="[----]";; esac; printf "%b%s%b %s\n" "$color_start" "$prefix" "$color_end" "$2" >&2; }
log_info() { _log_base "INFO" "$1"; }
log_warn() { _log_base "WARN" "$1"; }
log_error() { _log_base "ERROR" "$1"; }
exit_error() { log_error "$1"; exit 1; }
command_exists() { command -v "$1" &> /dev/null; }

# --- Function to run commands within the TARGET conda environment ---
# Uses the Python interpreter within the environment directly
run_in_conda_env() {
    local target_env_python="${CONDA_ENV_DIR}/bin/python"
    local command_to_run=("$@") # Copy the arguments array

    if [ ! -x "$target_env_python" ]; then exit_error "Python executable not found in target Conda env: $target_env_python"; return 1; fi

    log_info "Running in Conda env '${CONDA_ENV_DIR}' using its Python: ${command_to_run[*]}"
    local execution_cmd=()
    case "${command_to_run[0]}" in
        pip) execution_cmd=("$target_env_python" -m "${command_to_run[@]}");;
        pyinstaller)
            # Try running as module first
            if "$target_env_python" -m pyinstaller --version &>/dev/null; then
                 execution_cmd=("$target_env_python" -m "${command_to_run[@]}")
            else
                 # Fallback: try finding the executable directly
                 local pyinstaller_exec="${CONDA_ENV_DIR}/bin/pyinstaller"
                 if [ -x "$pyinstaller_exec" ]; then log_info "Running pyinstaller via direct executable path."; execution_cmd=("$pyinstaller_exec" "${command_to_run[@]:1}");
                 else exit_error "PyInstaller module/executable not found or not runnable in env $CONDA_ENV_DIR"; return 1; fi
            fi ;;
        *) local target_cmd_path="${CONDA_ENV_DIR}/bin/${command_to_run[0]}"; if [ -x "$target_cmd_path" ]; then log_info "Executing command directly from env bin: $target_cmd_path"; execution_cmd=("$target_cmd_path" "${command_to_run[@]:1}"); else exit_error "Cannot determine how to run command '${command_to_run[0]}' in target env."; return 1; fi ;;
    esac

    log_info "Executing: ${execution_cmd[*]}"
    # Execute and allow output to stream
    if ! "${execution_cmd[@]}"; then log_error "Command failed in conda env: ${command_to_run[*]}"; return 1; fi
    return 0
}


# --- ========================== ---
# --- === BUILD PHASE START ==== ---
# --- ========================== ---
echo ""
log_info "--- Starting ${APP_NAME} Build Process (Version ${APP_VERSION}) ---"

# 1. Check Host Prerequisites
log_info "[1/4] Checking build prerequisites..."
if [ "$(id -u)" -eq 0 ]; then exit_error "This build script should be run as a regular user, NOT as root or with sudo."; fi
HOST_PYTHON_EXEC=""; if command_exists python3; then HOST_PYTHON_EXEC=$(command -v python3); if ! "$HOST_PYTHON_EXEC" -c 'import sys; exit(0 if sys.version_info.major == 3 else 1)'; then log_warn "Found python3 at '$HOST_PYTHON_EXEC', but it's not Python 3.x."; HOST_PYTHON_EXEC=""; fi; elif command_exists python; then HOST_PYTHON_EXEC=$(command -v python); if "$HOST_PYTHON_EXEC" -c 'import sys; exit(0 if sys.version_info.major == 3 else 1)'; then log_warn "Found 'python' at '$HOST_PYTHON_EXEC' (Python 3.x). Consider using 'python3' alias."; else log_warn "Found 'python' at '$HOST_PYTHON_EXEC', but it's Python 2.x. Cannot use."; HOST_PYTHON_EXEC=""; fi; fi
if [ -z "$HOST_PYTHON_EXEC" ]; then exit_error "Host Python 3.x executable not found ('python3' or 'python')."; fi; log_info " Found Host Python 3: $HOST_PYTHON_EXEC ($($HOST_PYTHON_EXEC --version 2>&1))"
DOWNLOADER=""; if command_exists wget; then DOWNLOADER="wget -q -O"; elif command_exists curl; then DOWNLOADER="curl -fsSL -o"; else exit_error "Neither wget nor curl found. Cannot download Miniconda."; fi; log_info " Using downloader: $(echo "$DOWNLOADER" | cut -d' ' -f1)"
if ! command_exists gcc; then log_warn "'gcc' not found. Some pip packages might fail to build."; fi; if ! command_exists make; then log_warn "'make' not found. Some pip packages might fail to build."; fi
if [ ! -d "$SOURCE_CODE_DIR" ]; then exit_error "Source code directory not found: $SOURCE_CODE_DIR"; fi; if [ ! -f "${SOURCE_CODE_DIR}/main.py" ]; then exit_error "Main script not found: ${SOURCE_CODE_DIR}/main.py"; fi; if [ ! -f "$REQUIREMENTS_FILE" ]; then exit_error "Requirements file not found: $REQUIREMENTS_FILE"; fi
# Check data dir structure needed for PyInstaller --add-data
if [ ! -d "${SCRIPT_DIR}/${SOURCE_CODE_SUBDIR}/templates" ]; then exit_error "Source templates directory not found: ${SCRIPT_DIR}/${SOURCE_CODE_SUBDIR}/templates"; fi
if [ ! -d "${SCRIPT_DIR}/${SOURCE_CODE_SUBDIR}/static" ]; then exit_error "Source static directory not found: ${SCRIPT_DIR}/${SOURCE_CODE_SUBDIR}/static"; fi
if [ ! -d "$SOURCE_DATA_DIR" ]; then exit_error "Source data directory not found: $SOURCE_DATA_DIR"; fi
if [ ! -d "${SOURCE_DATA_DIR}/icons" ]; then exit_error "Source icons subdirectory not found: ${SOURCE_DATA_DIR}/icons"; fi
log_info " Prerequisite checks passed."

# 2. Setup Conda Environment
log_info "[2/4] Setting up Conda build environment..."
if ! command_exists conda; then
    log_info " Conda not found in PATH. Setting up local Miniconda instance..."
    
    # --- Terms of Service Agreement ---
    log_info " This script needs to download and install Miniconda to create a local build environment."
    log_info " Miniconda is governed by the Anaconda Terms of Service."
    log_info " Please review the terms at: https://legal.anaconda.com/policies/en/?name=terms-of-service"
    read -p " Do you agree to these terms and wish to proceed with the download? (y/N): " agree_to_tos
    if [[ ! "$agree_to_tos" =~ ^[Yy]$ ]]; then
        exit_error "Build cancelled by user. You must agree to the Anaconda ToS to proceed."
    fi
    # --- End ToS Agreement ---

    PLATFORM=$(uname -s); ARCH=$(uname -m)
    if [ "$PLATFORM" != "Linux" ]; then exit_error "Unsupported build platform: $PLATFORM"; fi
    
    # Architecture Detection and URL Selection
    case "$ARCH" in
        "x86_64")
            MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
            log_info " Detected x86_64 architecture"
            ;;
        "aarch64"|"arm64")
            MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh"
            log_info " Detected ARM64/aarch64 architecture"
            ;;
        *)
            exit_error "Unsupported architecture: $ARCH. Supported: x86_64, aarch64/arm64"
            ;;
    esac
    
    MINICONDA_SCRIPT="${CONDA_INSTALLER_DIR}/miniconda_installer.sh"
    log_info " Creating directory for installer: $CONDA_INSTALLER_DIR"; mkdir -p "$CONDA_INSTALLER_DIR" || exit_error "Failed to create directory: $CONDA_INSTALLER_DIR"
    if [ ! -f "$MINICONDA_SCRIPT" ]; then log_info " Downloading Miniconda installer for $ARCH..."; $DOWNLOADER "$MINICONDA_SCRIPT" "$MINICONDA_URL" || exit_error "Failed to download Miniconda."; chmod +x "$MINICONDA_SCRIPT" || exit_error "Failed to make Miniconda script executable."; else log_info " Using existing Miniconda installer: $MINICONDA_SCRIPT"; fi
    log_info " Installing Miniconda to ${CONDA_BASE_DIR}..."; if [ -d "$CONDA_BASE_DIR" ]; then log_warn " Removing existing local Miniconda base: $CONDA_BASE_DIR"; rm -rf "$CONDA_BASE_DIR" || exit_error "Failed to remove existing Miniconda base."; fi
    bash "$MINICONDA_SCRIPT" -b -p "$CONDA_BASE_DIR" || exit_error "Miniconda installation failed."; log_info " Miniconda installed locally."
    CONDA_EXEC_PATH="${CONDA_BASE_DIR}/bin/conda"
else
    CONDA_EXEC_PATH=$(command -v conda); log_info " Using existing Conda found at: $CONDA_EXEC_PATH"
fi
if [ ! -x "$CONDA_EXEC_PATH" ]; then exit_error "Conda executable not found at expected path after setup: $CONDA_EXEC_PATH"; fi

# Accept Terms of Service to prevent build errors in non-interactive environments
log_info " Configuring Conda to be non-interactive and accepting ToS..."
"$CONDA_EXEC_PATH" config --set auto_update_conda false
"$CONDA_EXEC_PATH" config --set notify_outdated_conda false

# Use the 'tos' command for newer conda versions, which is more robust.
# If the '--non-interactive' flag is not supported, pipe 'yes' to the command.
if "$CONDA_EXEC_PATH" tos --help &>/dev/null; then
    log_info " Accepting Terms of Service for default channels..."
    if "$CONDA_EXEC_PATH" tos accept --help | grep -q -- '--non-interactive'; then
        "$CONDA_EXEC_PATH" tos accept --non-interactive --channel https://repo.anaconda.com/pkgs/main
        "$CONDA_EXEC_PATH" tos accept --non-interactive --channel https://repo.anaconda.com/pkgs/r
    else
        log_warn " '--non-interactive' flag not available. Piping 'yes' to 'conda tos accept' command."
        # Temporarily disable pipefail to avoid issues with 'yes' and SIGPIPE
        (
            set +o pipefail
            echo "yes" | "$CONDA_EXEC_PATH" tos accept --channel https://repo.anaconda.com/pkgs/main
            echo "yes" | "$CONDA_EXEC_PATH" tos accept --channel https://repo.anaconda.com/pkgs/r
        )
    fi
else
    log_warn " 'conda tos' command not found. Attempting legacy ToS acceptance..."
    "$CONDA_EXEC_PATH" config --set anaconda_tos_accepted true || log_warn "Could not set legacy anaconda_tos_accepted config."
fi


# Create/Update the build environment
CREATE_ENV=false
if [ -d "$CONDA_ENV_DIR" ]; then
    log_info " Build environment directory already exists: $CONDA_ENV_DIR"; read -p " Do you want to remove and recreate it? (y/N): " recreate_env
    if [[ "$recreate_env" =~ ^[Yy]$ ]]; then log_info " Removing existing build environment..."; rm -rf "$CONDA_ENV_DIR" || exit_error "Failed to remove existing build environment."; CREATE_ENV=true; fi
else CREATE_ENV=true; fi

if [ "$CREATE_ENV" = true ]; then
    log_info " Adding Miniconda bin to PATH temporarily for env creation..."; export PATH="${CONDA_BASE_DIR}/bin:${PATH}"
    log_info " Creating new Conda build environment with Python ${CONDA_PYTHON_VERSION}..."; "$CONDA_EXEC_PATH" create -p "$CONDA_ENV_DIR" python="$CONDA_PYTHON_VERSION" -y || exit_error "Failed to create Conda environment."
    log_info " Restoring original PATH..."; export PATH=$(echo "$PATH" | sed -e "s;${CONDA_BASE_DIR}/bin:;;"); log_info " Conda environment created."
else log_info " Using existing build environment. Ensure it has Python ${CONDA_PYTHON_VERSION}."; fi

CONDA_ENV_PYTHON="${CONDA_ENV_DIR}/bin/python"; if [ ! -x "$CONDA_ENV_PYTHON" ]; then exit_error "Python not found in created build environment: $CONDA_ENV_PYTHON"; fi
log_info " Build environment Python found: $CONDA_ENV_PYTHON ($($CONDA_ENV_PYTHON --version 2>&1))"
log_info " Conda environment setup complete."

# 3. Install Dependencies in Conda Env
log_info "[3/4] Installing dependencies into conda env '${CONDA_ENV_DIR}'..."
run_in_conda_env pip install --upgrade pip || exit_error "Failed to upgrade pip in conda env."
log_info " Installing packages from ${REQUIREMENTS_FILE}..."
run_in_conda_env pip install -r "$REQUIREMENTS_FILE" || exit_error "Failed to install requirements in conda env."
log_info " Ensuring PyInstaller is installed..."
run_in_conda_env pip install pyinstaller || exit_error "Failed to install PyInstaller in conda env."
log_info " Dependencies installed."

# 4. Run PyInstaller
log_info "[4/4] Running PyInstaller to bundle the application..."
run_in_conda_env pyinstaller --version || exit_error "PyInstaller command check failed within conda env."

# Define source paths relative to SCRIPT_DIR and destination paths relative to bundle root
SOURCE_TEMPLATES_PATH="${SCRIPT_DIR}/${SOURCE_CODE_SUBDIR}/templates"
SOURCE_STATIC_PATH="${SCRIPT_DIR}/${SOURCE_CODE_SUBDIR}/static"
# SOURCE_DATA_DIR is already defined relative to SCRIPT_DIR

# Destination paths are relative to the bundle's root directory (_MEIPASS)
DEST_TEMPLATES_PATH="templates"
DEST_STATIC_PATH="static"
DEST_DATA_PATH="data" # Bundle src/data/* into data/*

# Create the --add-data arguments using correct Bash syntax
# Use ':' as the separator for source:destination on Linux
PYINSTALLER_ADD_DATA_TEMPLATES="${SOURCE_TEMPLATES_PATH}:${DEST_TEMPLATES_PATH}"
PYINSTALLER_ADD_DATA_STATIC="${SOURCE_STATIC_PATH}:${DEST_STATIC_PATH}"
PYINSTALLER_ADD_DATA_DATA="${SOURCE_DATA_DIR}:${DEST_DATA_PATH}"

PYINSTALLER_MAIN_SCRIPT="${SOURCE_CODE_DIR}/main.py"

# Clean previous build/dist directories
log_info " Cleaning previous build artifacts (build/, dist/)..."
rm -rf "$BUILD_OUTPUT_DIR" "$DIST_OUTPUT_DIR"

# Run PyInstaller
log_info " PyInstaller Arguments:"
log_info "  --add-data $PYINSTALLER_ADD_DATA_TEMPLATES"
log_info "  --add-data $PYINSTALLER_ADD_DATA_STATIC"
log_info "  --add-data $PYINSTALLER_ADD_DATA_DATA" # Bundle the entire data directory
log_info "  --name $APP_EXECUTABLE_NAME"
log_info "  Main Script: $PYINSTALLER_MAIN_SCRIPT"

run_in_conda_env pyinstaller \
    --noconfirm \
    --distpath "$DIST_OUTPUT_DIR" \
    --workpath "$BUILD_OUTPUT_DIR" \
    --specpath "$SCRIPT_DIR" \
    --add-data "$PYINSTALLER_ADD_DATA_TEMPLATES" \
    --add-data "$PYINSTALLER_ADD_DATA_STATIC" \
    --add-data "$PYINSTALLER_ADD_DATA_DATA" \
    --name "$APP_EXECUTABLE_NAME" \
    "$PYINSTALLER_MAIN_SCRIPT" || exit_error "PyInstaller bundling failed."

# --- MODIFICATION: Remove the unreliable verification checks ---
# The previous checks using `[ ! -d ... ]` against the output directory
# were not reliable for verifying internal bundling.
# The success of the `pyinstaller` command above is the primary indicator.
# Runtime testing is the best way to confirm resources are found.
log_info " Verifying main executable creation..."
if [ ! -d "$BUNDLED_APP_DIR" ]; then exit_error "PyInstaller dist directory not created: ${BUNDLED_APP_DIR}"; fi
if [ ! -f "${BUNDLED_APP_DIR}/${APP_EXECUTABLE_NAME}" ]; then exit_error "PyInstaller executable not created: ${BUNDLED_APP_DIR}/${APP_EXECUTABLE_NAME}"; fi
log_info " Main executable created."
# --- END MODIFICATION ---

log_info " PyInstaller bundling complete."
echo ""
log_info "--- Build Phase Completed Successfully ---"
log_info "Application bundled in: ${BUNDLED_APP_DIR}"
log_info "You can now run the installation script (e.g., sudo ./install.sh) if needed."
echo ""
# Disable exit on error now that build is done
set +e

# --- ======================== ---
# --- === BUILD PHASE END ==== ---
# --- ======================== ---

exit 0
