#!/usr/bin/env bash
#
# Release creation script for zfdash
# Usage: ./scripts/release.sh <version> [--github] [--yes|-y]
# Example: ./scripts/release.sh v1.8.5-beta --github
# Changelog format in changelog.txt:
#    ## v1.8.4-Beta
#    *   **Feature** Description here
#    *   **Fix** Another change
# Options:
#   --github    Create GitHub release using gh CLI
#   --yes, -y   Skip confirmation prompts (auto-yes)
## uses build.sh > depends on uv; build.sh installs it if missing
set -euo pipefail

#######################################
# Constants
#######################################
readonly SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly CHANGELOG_FILE="${ROOT_DIR}/changelog.txt"

#######################################
# Print usage information
#######################################
usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} <version> [OPTIONS]

Create a release tarball for zfdash.

Arguments:
  version     Version tag (e.g., v1.8.5-beta)

Options:
  --github    Create GitHub release using gh CLI
  --yes, -y   Skip confirmation prompts
  --help, -h  Show this help message

Example:
  ${SCRIPT_NAME} v1.8.5-beta --github
EOF
}

#######################################
# Log functions
#######################################
log_info() {
  echo "[INFO] $*"
}

log_warn() {
  echo "[WARN] $*" >&2
}

log_error() {
  echo "[ERROR] $*" >&2
}

#######################################
# Confirm action (respects AUTO_YES)
# Arguments:
#   $1 - Prompt message
# Returns:
#   0 if confirmed, 1 otherwise
#######################################
confirm() {
  local prompt="$1"
  if [[ "${AUTO_YES}" == true ]]; then
    return 0
  fi
  printf "%s [Y/n]: " "$prompt"
  read -r ans
  case "${ans,,}" in
    ""|y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

#######################################
# Extract changelog entries for a version
# Parses changelog.txt and extracts bullet points for the given version.
# Arguments:
#   $1 - Version string (e.g., v1.8.5-beta)
# Outputs:
#   Changelog entries (one per line) or empty if not found
#######################################
extract_changelog() {
  local version="$1"
  local changelog_file="${CHANGELOG_FILE}"
  
  if [[ ! -f "${changelog_file}" ]]; then
    log_warn "Changelog file not found: ${changelog_file}"
    return 1
  fi
  
  # Normalize version for matching (case-insensitive, handle v prefix)
  local version_pattern="${version}"
  # Remove leading 'v' if present for flexible matching
  version_pattern="${version_pattern#v}"
  
  local in_section=false
  local entries=()
  
  while IFS= read -r line || [[ -n "$line" ]]; do
    # Check if this is a version header line (## vX.X.X or ## X.X.X)
    if [[ "$line" =~ ^##[[:space:]]+(v?[0-9]+\.[0-9]+\.[0-9]+[^[:space:]]*) ]]; then
      local header_version="${BASH_REMATCH[1]}"
      # Normalize header version (remove leading v)
      header_version="${header_version#v}"
      
      if [[ "${header_version,,}" == "${version_pattern,,}" ]]; then
        in_section=true
        continue
      elif [[ "${in_section}" == true ]]; then
        # We've hit the next version section, stop
        break
      fi
    fi
    
    # If we're in the target section, collect bullet points
    if [[ "${in_section}" == true ]]; then
      # Match lines starting with * or - (bullet points)
      if [[ "$line" =~ ^[[:space:]]*[\*\-][[:space:]]+(.+)$ ]]; then
        entries+=("${BASH_REMATCH[1]}")
      fi
    fi
  done < "${changelog_file}"
  
  # Output entries
  if [[ ${#entries[@]} -gt 0 ]]; then
    printf '%s\n' "${entries[@]}"
    return 0
  else
    return 1
  fi
}

#######################################
# Parse command line arguments
#######################################
parse_args() {
  VERSION=""
  USE_GH=false
  AUTO_YES=false
  
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --github)
        USE_GH=true
        shift
        ;;
      --yes|-y)
        AUTO_YES=true
        shift
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      -*)
        log_error "Unknown option: $1"
        usage
        exit 1
        ;;
      *)
        if [[ -z "${VERSION}" ]]; then
          VERSION="$1"
        else
          log_error "Unexpected argument: $1"
          usage
          exit 1
        fi
        shift
        ;;
    esac
  done
  
  if [[ -z "${VERSION}" ]]; then
    log_error "Version argument is required"
    usage
    exit 1
  fi
}

#######################################
# Main script
#######################################
main() {
  parse_args "$@"
  
  cd "${ROOT_DIR}"
  
  local tmp_dir="${ROOT_DIR}/release_tmp"
  local release_dir="${tmp_dir}/Release.Binary"
  local tar_name="zfdash-${VERSION}.tar.gz"
  
  log_info "Starting release build for ${VERSION}"
  
  #######################################
  # Pre-flight checks
  #######################################
  if [[ ! -x "${ROOT_DIR}/build.sh" ]]; then
    log_error "build.sh not found or not executable in project root: ${ROOT_DIR}"
    exit 1
  fi
  
  #######################################
  # Build step
  #######################################
  if confirm "Run ./build.sh now?"; then
    log_info "Running ./build.sh"
    if [[ "${AUTO_YES}" == true ]]; then
      ./build.sh --yes
    else
      ./build.sh
    fi
  else
    log_error "Skipped build step by user. Aborting."
    exit 1
  fi
  
  #######################################
  # Prepare release directory
  #######################################
  log_info "Preparing release directory: ${release_dir}"
  rm -rf "${tmp_dir}"
  mkdir -p "${release_dir}"
  
  # Copy dist (if exists) or fallback to build output
  if [[ -d "${ROOT_DIR}/dist" ]]; then
    log_info "Copying existing dist/ -> Release.Binary/dist/"
    mkdir -p "${release_dir}/dist"
    rsync -a --delete "${ROOT_DIR}/dist/" "${release_dir}/dist/"
  elif [[ -d "${ROOT_DIR}/build/zfdash" ]]; then
    log_info "No dist/ found; copying build/zfdash -> Release.Binary/dist/"
    mkdir -p "${release_dir}/dist"
    rsync -a "${ROOT_DIR}/build/zfdash/" "${release_dir}/dist/"
  else
    log_warn "No dist/ or build/zfdash/ found. Release may be incomplete."
  fi
  
  # Copy required files
  for item in install_service install.sh uninstall.sh; do
    if [[ -e "${ROOT_DIR}/${item}" ]]; then
      log_info "Copying ${item}"
      rsync -a "${ROOT_DIR}/${item}" "${release_dir}/"
    else
      log_warn "${item} not found in project root; skipping."
    fi
  done
  
  # Copy src with exclusions
  if [[ -d "${ROOT_DIR}/src" ]]; then
    log_info "Copying src (excluding __pycache__ and .gitignored files)"
    rsync -a \
      --exclude='build_env_zfdash/' \
      --exclude='miniconda_installer/' \
      --exclude='miniconda_base/' \
      --exclude='build/' \
      --exclude='dist/' \
      --exclude='__pycache__/' \
      --exclude='*.spec' \
      --exclude='*.pyc' \
      --exclude='*.pyo' \
      --exclude='*.pyd' \
      --exclude='*.log' \
      --exclude='.cache/' \
      --exclude='.cache' \
      --exclude='.venv/' \
      --exclude='developer documentation/' \
      --exclude='compose.override.yml' \
      --exclude='**/docker-local-debug.sh' \
      --exclude='release_tmp/' \
      --exclude='*.tar.gz' \
      --exclude='_ign-*' \
      --filter=':- .gitignore' \
      "${ROOT_DIR}/src/" "${release_dir}/src/"
  else
    log_warn "src not found in project root; skipping."
  fi
  
  #######################################
  # Create tarball
  #######################################
  log_info "Creating tarball ${tar_name}"
  if confirm "Create tarball ${tar_name}?"; then
    rm -f "${tar_name}"
    tar -czf "${tar_name}" -C "${release_dir}" .
  else
    log_error "User chose not to create tarball. Aborting."
    exit 1
  fi
  
  #######################################
  # Compute checksums
  #######################################
  log_info "Computing checksums"
  local md5_sum sha256_sum
  md5_sum="$(md5sum "${tar_name}" | awk '{print $1}')"
  sha256_sum="$(sha256sum "${tar_name}" | awk '{print $1}')"
  
  log_info "MD5: ${md5_sum}"
  log_info "SHA256: ${sha256_sum}"
  
  #######################################
  # Prepare release notes
  #######################################
  local notes_file="${tmp_dir}/release_notes_${VERSION}.txt"
  local latest_tag=""
  local remote_url=""
  local gh_http_url=""
  local changelog_link=""
  
  # Get latest git tag
  if git rev-parse --git-dir >/dev/null 2>&1; then
    latest_tag="$(git describe --tags --abbrev=0 2>/dev/null || true)"
    if [[ "${latest_tag}" == "${VERSION}" ]]; then
      latest_tag="$(git tag --sort=-v:refname | grep -v "^${VERSION}$" | head -n1 || true)"
    fi
  fi
  
  # Get GitHub URL
  remote_url="$(git remote get-url origin 2>/dev/null || true)"
  if [[ -n "${remote_url}" ]]; then
    if [[ "${remote_url}" =~ ^git@ ]]; then
      gh_http_url="$(echo "${remote_url}" | sed -E 's/^git@([^:]+):/https:\/\/\1\//; s/\.git$//')"
    else
      gh_http_url="$(echo "${remote_url}" | sed -E 's/\.git$//')"
    fi
  fi
  
  # Build changelog link
  if [[ -n "${gh_http_url}" && -n "${latest_tag}" ]]; then
    changelog_link="${gh_http_url}/compare/${latest_tag}...${VERSION}"
  elif [[ -n "${gh_http_url}" ]]; then
    changelog_link="${gh_http_url}/commits/${VERSION}"
  fi
  
  # Extract changelog entries for this version
  log_info "Extracting changelog entries for ${VERSION}"
  local changelog_entries=""
  if changelog_entries="$(extract_changelog "${VERSION}")"; then
    log_info "Found changelog entries for ${VERSION}"
  else
    log_warn "No changelog entries found for ${VERSION}. Using placeholder."
    changelog_entries=""
  fi
  
  # Format changelog entries for release notes
  local formatted_changes=""
  if [[ -n "${changelog_entries}" ]]; then
    while IFS= read -r entry; do
      formatted_changes+="  - ${entry}"$'\n'
    done <<< "${changelog_entries}"
  else
    formatted_changes="  - (Add your changes here)"$'\n'
  fi
  
  # Write release notes
  cat > "${notes_file}" <<EOF
## ZfDash ${VERSION}

### Changes in this release:
${formatted_changes}
> **IMPORTANT:** This is BETA software. Use cautiously, ensure backups, and change the default Web UI password (admin/admin) immediately. Incorrect use can lead to **PERMANENT DATA LOSS**.

### Installation
Extract and run \`sudo ./install.sh\` (after \`chmod +x install.sh\`) for system-wide installation. See README for details. Licensed under GPLv3.

### Checksums
- **MD5:** \`${md5_sum}\`
- **SHA256:** \`${sha256_sum}\`

**Full Changelog**: ${changelog_link:-"N/A"}
EOF

  log_info "Release notes written to: ${notes_file}"
  
  #######################################
  # Allow user to edit release notes
  #######################################
  echo
  echo "=============================================="
  echo "Release notes preview:"
  echo "=============================================="
  cat "${notes_file}"
  echo "=============================================="
  
  if [[ "${AUTO_YES}" == true ]]; then
    log_info "Skipping manual edit prompt (--yes flag provided)."
  else
    echo
    echo "You can now edit the release notes at: ${notes_file}"
    echo "Press ENTER to continue, or type 'abort' to stop."
    read -r user_choice
    if [[ "${user_choice}" == "abort" ]]; then
      log_error "Aborted by user after editing release notes."
      exit 1
    fi
  fi
  
  #######################################
  # GitHub release (optional)
  #######################################
  if [[ "${USE_GH}" == true ]]; then
    if ! command -v gh >/dev/null 2>&1; then
      log_error "gh CLI not found. Install GitHub CLI or omit --github."
    else
      # Check if we're in CI (tag already exists and pushed)
      local tag_exists=false
      if git rev-parse "${VERSION}" >/dev/null 2>&1; then
        tag_exists=true
        log_info "Tag ${VERSION} already exists."
      fi
      
      # Only create and push tag if it doesn't exist (local runs)
      if [[ "${tag_exists}" == false ]]; then
        log_info "Creating git tag ${VERSION} and pushing"
        git tag -a "${VERSION}" -m "Release ${VERSION}" 2>/dev/null || log_warn "Tag ${VERSION} may already exist"
        git push origin "${VERSION}" 2>/dev/null || log_warn "Failed to push tag ${VERSION}"
      fi
      
      log_info "Creating GitHub release ${VERSION} and uploading ${tar_name}"
      if ! gh release create "${VERSION}" "${tar_name}" --title "ZfDash ${VERSION}" --notes-file "${notes_file}"; then
        log_error "gh release create failed. You may need GH_TOKEN or interactive login."
        exit 1
      fi
    fi
  fi
  
  #######################################
  # Summary
  #######################################
  echo
  log_info "=============================================="
  log_info "Release complete!"
  log_info "=============================================="
  log_info "Tarball: ${ROOT_DIR}/${tar_name}"
  log_info "MD5: ${md5_sum}"
  log_info "SHA256: ${sha256_sum}"
  log_info "Release notes: ${notes_file}"
  log_info "=============================================="
}

# Run main function
main "$@"
