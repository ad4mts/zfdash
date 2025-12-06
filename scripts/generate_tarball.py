#!/usr/bin/env python3
"""
Generate tarball script for zfdash.

Builds the project and creates a tarball with SHA256 hash file.
Naming: zfdash-(version)-(system)-(architecture).tar.gz

Usage:
    python scripts/generate_tarball.py [--yes|-y] [--clean]

Tarballs are stored in releases/ folder and kept across runs.
Only overwrites if exact same name exists.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import NoReturn

#######################################
# Constants
#######################################
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
RELEASES_DIR = ROOT_DIR / "releases"
VERSION_FILE = ROOT_DIR / "src" / "version.py"

# Files/directories to exclude from the tarball
EXCLUDE_PATTERNS = {
    "build_env_zfdash",
    "miniconda_installer",
    "miniconda_base",
    "build",
    "dist",
    "__pycache__",
    ".cache",
    ".venv",
    "developer documentation",
    "release_tmp",
    "releases",
    ".git",
    ".github",
}

EXCLUDE_EXTENSIONS = {".spec", ".pyc", ".pyo", ".pyd", ".log", ".tar.gz"}

EXCLUDE_FILES = {
    "compose.override.yml",
    "docker-local-debug.sh",
}

EXCLUDE_PREFIXES = {"_ign-"}


#######################################
# Logging functions
#######################################
class Logger:
    """Simple logger with colored output support."""
    
    COLORS = {
        "info": "\033[0;34m",  # Blue
        "warn": "\033[0;33m",  # Yellow
        "error": "\033[0;31m",  # Red
        "reset": "\033[0m",
    }
    
    @classmethod
    def _supports_color(cls) -> bool:
        """Check if the terminal supports color."""
        if os.environ.get("NO_COLOR"):
            return False
        if not hasattr(sys.stdout, "isatty"):
            return False
        return sys.stdout.isatty()
    
    @classmethod
    def _format(cls, level: str, message: str) -> str:
        """Format a log message with optional color."""
        tag = f"[{level.upper()}]"
        if cls._supports_color():
            color = cls.COLORS.get(level, "")
            reset = cls.COLORS["reset"]
            return f"{color}{tag}{reset} {message}"
        return f"{tag} {message}"
    
    @classmethod
    def info(cls, message: str) -> None:
        """Log an info message."""
        print(cls._format("info", message))
    
    @classmethod
    def warn(cls, message: str) -> None:
        """Log a warning message."""
        print(cls._format("warn", message), file=sys.stderr)
    
    @classmethod
    def error(cls, message: str) -> None:
        """Log an error message."""
        print(cls._format("error", message), file=sys.stderr)


log = Logger()


#######################################
# Utility functions
#######################################
def confirm(prompt: str, auto_yes: bool = False) -> bool:
    """
    Prompt user for confirmation.
    
    Args:
        prompt: The confirmation prompt to display.
        auto_yes: If True, automatically return True without prompting.
    
    Returns:
        True if confirmed, False otherwise.
    """
    if auto_yes:
        return True
    
    try:
        response = input(f"{prompt} [Y/n]: ").strip().lower()
        return response in ("", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def detect_system() -> str:
    """
    Detect the current system and architecture.
    
    Returns:
        A string in the format "os-arch" (e.g., "linux-x86_64").
    """
    # Detect OS
    system = platform.system().lower()
    os_map = {
        "linux": "linux",
        "darwin": "macos",
        "windows": "windows",
        "freebsd": "freebsd",
    }
    os_name = os_map.get(system, system)
    
    # Detect architecture
    machine = platform.machine().lower()
    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "armv7",
        "armv8l": "arm64",
        "i386": "x86",
        "i686": "x86",
    }
    arch = arch_map.get(machine, machine)
    
    return f"{os_name}-{arch}"


def get_version() -> str:
    """
    Get the version from version.py.
    
    Returns:
        The version string, or "unknown" if not found.
    """
    if not VERSION_FILE.exists():
        return "unknown"
    
    try:
        content = VERSION_FILE.read_text(encoding="utf-8")
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            return match.group(1)
    except OSError as e:
        log.warn(f"Failed to read version file: {e}")
    
    return "unknown"


def should_exclude(path: Path, base_dir: Path) -> bool:
    """
    Check if a path should be excluded from the tarball.
    
    Args:
        path: The path to check.
        base_dir: The base directory for relative path calculation.
    
    Returns:
        True if the path should be excluded, False otherwise.
    """
    name = path.name
    
    # Check exact name matches
    if name in EXCLUDE_PATTERNS or name in EXCLUDE_FILES:
        return True
    
    # Check prefixes
    for prefix in EXCLUDE_PREFIXES:
        if name.startswith(prefix):
            return True
    
    # Check extensions
    if path.suffix in EXCLUDE_EXTENSIONS:
        return True
    
    # Check if any parent directory should be excluded
    try:
        rel_path = path.relative_to(base_dir)
        for part in rel_path.parts:
            if part in EXCLUDE_PATTERNS:
                return True
    except ValueError:
        pass
    
    return False


def copy_tree_filtered(
    src: Path,
    dst: Path,
    base_dir: Path,
) -> None:
    """
    Copy a directory tree, filtering out excluded files.
    
    Args:
        src: Source directory.
        dst: Destination directory.
        base_dir: Base directory for exclusion pattern matching.
    """
    dst.mkdir(parents=True, exist_ok=True)
    
    for item in src.iterdir():
        if should_exclude(item, base_dir):
            continue
        
        dst_item = dst / item.name
        
        if item.is_dir():
            copy_tree_filtered(item, dst_item, base_dir)
        else:
            shutil.copy2(item, dst_item)


def compute_sha256(file_path: Path) -> str:
    """
    Compute SHA256 hash of a file.
    
    Args:
        file_path: Path to the file.
    
    Returns:
        The SHA256 hash as a hexadecimal string.
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def run_build(auto_yes: bool, clean: bool) -> bool:
    """
    Run the build script.
    
    Args:
        auto_yes: If True, pass --yes to build script.
        clean: If True, pass --clean to build script.
    
    Returns:
        True if build succeeded, False otherwise.
    """
    build_script = ROOT_DIR / "build.sh"
    
    if not build_script.exists():
        log.error(f"build.sh not found in project root: {ROOT_DIR}")
        return False
    
    cmd = ["bash", str(build_script)]
    if auto_yes:
        cmd.append("--yes")
    if clean:
        cmd.append("--clean")
    
    log.info(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, cwd=ROOT_DIR, check=False)
        return result.returncode == 0
    except OSError as e:
        log.error(f"Failed to run build script: {e}")
        return False


#######################################
# Argument parsing
#######################################
def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Build zfdash and create a release tarball with SHA256 hash file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Output naming: zfdash-(version)-(system)-(architecture).tar.gz
Example: zfdash-1.8.8-beta-linux-x86_64.tar.gz

Tarballs are stored in releases/ and kept across multiple runs.
        """,
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        dest="auto_yes",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean build before creating tarball",
    )
    return parser.parse_args()


#######################################
# Main function
#######################################
def main() -> NoReturn:
    """Main entry point."""
    args = parse_args()
    
    os.chdir(ROOT_DIR)
    
    version = get_version()
    system_arch = detect_system()
    tar_name = f"zfdash-{version}-{system_arch}.tar.gz"
    sha_name = f"{tar_name}.sha256"
    
    log.info("=" * 42)
    log.info("Generate Tarball for ZfDash")
    log.info("=" * 42)
    log.info(f"Version: {version}")
    log.info(f"System:  {system_arch}")
    log.info(f"Output:  {tar_name}")
    log.info("=" * 42)
    
    #######################################
    # Build step
    #######################################
    if not confirm("Run ./build.sh now?", args.auto_yes):
        log.error("Skipped build step by user. Aborting.")
        sys.exit(1)
    
    if not run_build(args.auto_yes, args.clean):
        log.error("Build failed. Aborting.")
        sys.exit(1)
    
    #######################################
    # Prepare release directory structure
    #######################################
    tmp_dir = ROOT_DIR / "release_tmp"
    release_dir = tmp_dir / "Release.Binary"
    
    log.info(f"Preparing release directory: {release_dir}")
    
    # Clean up any previous tmp directory
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    
    release_dir.mkdir(parents=True, exist_ok=True)
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Copy dist (if exists) or fallback to build output
    dist_dir = ROOT_DIR / "dist"
    build_dir = ROOT_DIR / "build" / "zfdash"
    dest_dist = release_dir / "dist"
    
    if dist_dir.exists():
        log.info("Copying existing dist/ -> Release.Binary/dist/")
        shutil.copytree(dist_dir, dest_dist, dirs_exist_ok=True, symlinks=True)
    elif build_dir.exists():
        log.info("No dist/ or build/zfdash/ found; copying build/zfdash -> Release.Binary/dist/")
        shutil.copytree(build_dir, dest_dist, dirs_exist_ok=True, symlinks=True)
    else:
        log.warn("No dist/ or build/zfdash/ found. Release may be incomplete.")
    
    # Copy required files
    for item_name in ("install_service", "install.sh", "uninstall.sh"):
        item_path = ROOT_DIR / item_name
        if item_path.exists():
            log.info(f"Copying {item_name}")
            if item_path.is_dir():
                shutil.copytree(item_path, release_dir / item_name, dirs_exist_ok=True)
            else:
                shutil.copy2(item_path, release_dir / item_name)
        else:
            log.warn(f"{item_name} not found in project root; skipping.")
    
    # Copy src with exclusions
    src_dir = ROOT_DIR / "src"
    if src_dir.exists():
        log.info("Copying src (excluding __pycache__ and other build artifacts)")
        copy_tree_filtered(src_dir, release_dir / "src", ROOT_DIR)
    else:
        log.warn("src not found in project root; skipping.")
    
    #######################################
    # Create tarball
    #######################################
    tar_path = RELEASES_DIR / tar_name
    sha_path = RELEASES_DIR / sha_name
    
    log.info(f"Creating tarball: {tar_path}")
    
    if not confirm(f"Create tarball {tar_name}?", args.auto_yes):
        log.error("User chose not to create tarball. Aborting.")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        sys.exit(1)
    
    # Create tarball (overwrites if same name exists)
    with tarfile.open(tar_path, "w:gz") as tar:
        for item in release_dir.iterdir():
            tar.add(item, arcname=item.name)
    
    log.info(f"Tarball created: {tar_path}")
    
    #######################################
    # Compute SHA256 checksum
    #######################################
    log.info("Computing SHA256 checksum")
    sha256_sum = compute_sha256(tar_path)
    
    # Write hash file (checksum  filename format for easy verification with sha256sum -c)
    sha_path.write_text(f"{sha256_sum}  {tar_name}\n", encoding="utf-8")
    
    log.info(f"SHA256: {sha256_sum}")
    log.info(f"Hash file: {sha_path}")
    
    #######################################
    # Cleanup
    #######################################
    shutil.rmtree(tmp_dir, ignore_errors=True)
    
    #######################################
    # Summary
    #######################################
    print()
    log.info("=" * 42)
    log.info("Tarball generation complete!")
    log.info("=" * 42)
    log.info(f"Tarball:   {tar_path}")
    log.info(f"Hash file: {sha_path}")
    log.info(f"SHA256:    {sha256_sum}")
    log.info("=" * 42)
    print()
    log.info("All tarballs in releases/:")
    
    tarballs = list(RELEASES_DIR.glob("*.tar.gz"))
    if tarballs:
        for tb in sorted(tarballs):
            size = tb.stat().st_size
            log.info(f"  {tb.name} ({size:,} bytes)")
    else:
        log.info("  (none)")
    
    sys.exit(0)


if __name__ == "__main__":
    main()
