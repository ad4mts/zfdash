#!/usr/bin/env python3
"""
Publish release script for zfdash.

Creates a GitHub release with release notes and uploads all tarballs and hash files (gets latest version from version.py).

Usage:
    python scripts/publish_release.py [version] [--yes|-y] [--draft]

Uploads all .tar.gz and .sha256 files from the releases/ folder.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

#######################################
# Constants
#######################################
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
RELEASES_DIR = ROOT_DIR / "releases"
VERSION_FILE = ROOT_DIR / "src" / "version.py"


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


def normalize_version(version: str) -> tuple[str, str]:
    """
    Normalize version string.
    
    Args:
        version: The version string (with or without 'v' prefix).
    
    Returns:
        A tuple of (tag_version, match_version) where tag_version
        has the 'v' prefix and match_version does not.
    """
    match_version = version.lstrip("v")
    tag_version = f"v{match_version}"
    return tag_version, match_version


def run_command(
    *args: str,
    capture: bool = False,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """
    Run a command and return the result.
    
    Args:
        *args: Command and arguments.
        capture: If True, capture stdout and stderr.
        check: If True, raise on non-zero exit code.
    
    Returns:
        CompletedProcess instance.
    """
    return subprocess.run(
        args,
        capture_output=capture,
        text=True,
        cwd=ROOT_DIR,
        check=check,
    )


def check_gh_cli() -> bool:
    """
    Check if GitHub CLI is installed and authenticated.
    
    Returns:
        True if gh CLI is ready, False otherwise.
    """
    # Check if gh is installed
    try:
        result = run_command("gh", "--version", capture=True)
        if result.returncode != 0:
            log.error("GitHub CLI (gh) not found. Please install it first.")
            log.error("See: https://cli.github.com/")
            return False
    except FileNotFoundError:
        log.error("GitHub CLI (gh) not found. Please install it first.")
        log.error("See: https://cli.github.com/")
        return False
    
    # Check if authenticated
    result = run_command("gh", "auth", "status", capture=True)
    if result.returncode != 0:
        log.error("GitHub CLI not authenticated. Run 'gh auth login' first.")
        return False
    
    return True


def check_tag_exists(tag: str, remote: bool = False) -> bool:
    """
    Check if a git tag exists.
    
    Args:
        tag: The tag to check.
        remote: If True, check remote tags.
    
    Returns:
        True if tag exists, False otherwise.
    """
    if remote:
        result = run_command(
            "git", "ls-remote", "--tags", "origin",
            capture=True,
        )
        if result.returncode == 0:
            return f"refs/tags/{tag}" in result.stdout
        return False
    else:
        result = run_command("git", "rev-parse", tag, capture=True)
        return result.returncode == 0


def create_tag(tag: str) -> bool:
    """
    Create a git tag.
    
    Args:
        tag: The tag to create.
    
    Returns:
        True if successful, False otherwise.
    """
    result = run_command(
        "git", "tag", "-a", tag, "-m", f"Release {tag}",
        capture=True,
    )
    return result.returncode == 0


def push_tag(tag: str) -> bool:
    """
    Push a git tag to origin.
    
    Args:
        tag: The tag to push.
    
    Returns:
        True if successful, False otherwise.
    """
    result = run_command("git", "push", "origin", tag, capture=True)
    return result.returncode == 0


def release_exists(tag: str) -> bool:
    """
    Check if a GitHub release exists.
    
    Args:
        tag: The release tag.
    
    Returns:
        True if release exists, False otherwise.
    """
    result = run_command("gh", "release", "view", tag, capture=True)
    return result.returncode == 0


def upload_assets(tag: str, files: list[Path]) -> bool:
    """
    Upload assets to an existing release.
    
    Args:
        tag: The release tag.
        files: List of files to upload.
    
    Returns:
        True if all uploads succeeded, False otherwise.
    """
    success = True
    for file in files:
        log.info(f"Uploading {file.name}")
        result = run_command(
            "gh", "release", "upload", tag, str(file), "--clobber",
            capture=True,
        )
        if result.returncode != 0:
            log.warn(f"Failed to upload {file.name}")
            success = False
    return success


def create_release(
    tag: str,
    title: str,
    notes_file: Path,
    files: list[Path],
    draft: bool = False,
) -> bool:
    """
    Create a new GitHub release.
    
    Args:
        tag: The release tag.
        title: The release title.
        notes_file: Path to release notes file.
        files: List of files to attach.
        draft: If True, create as draft release.
    
    Returns:
        True if successful, False otherwise.
    """
    cmd = ["gh", "release", "create", tag, "--title", title, "--notes-file", str(notes_file)]
    
    if draft:
        cmd.append("--draft")
    
    # Add files
    for file in files:
        cmd.append(str(file))
    
    result = run_command(*cmd, capture=True)
    
    if result.returncode != 0:
        log.error("Failed to create GitHub release.")
        if result.stderr:
            log.error(result.stderr)
        log.error("You may need to run 'gh auth login' or set GH_TOKEN.")
        return False
    
    return True


def create_minimal_notes(notes_file: Path, version_tag: str) -> None:
    """
    Create minimal release notes.
    
    Args:
        notes_file: Path to write notes to.
        version_tag: The version tag.
    """
    content = f"""## ZfDash {version_tag}

Release {version_tag}

> **IMPORTANT:** This is BETA software. Use cautiously, ensure backups, and change the default Web UI password (admin/admin) immediately.

### Installation
Extract and run `sudo ./install.sh` for system-wide installation.

### Checksums
See the `.sha256` files accompanying each tarball for verification.
"""
    notes_file.parent.mkdir(parents=True, exist_ok=True)
    notes_file.write_text(content, encoding="utf-8")


#######################################
# Argument parsing
#######################################
def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Create a GitHub release and upload all tarballs and hash files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Uploads all .tar.gz and .sha256 files from the releases/ folder.

Examples:
    python scripts/publish_release.py v1.8.8-beta
    python scripts/publish_release.py 1.8.8-beta --draft
        """,
    )
    parser.add_argument(
        "version",
        nargs="?",
        default=None,
        help="Version tag (e.g., v1.8.8-beta or 1.8.8-beta). "
             "If not provided, uses version from version.py.",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        dest="auto_yes",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        dest="draft",
        help="Create as draft release",
    )
    parser.add_argument(
        "--notes",
        dest="notes_file",
        default=None,
        help="Use specific notes file (default: releases/release_notes_<version>.md)",
    )
    return parser.parse_args()


#######################################
# Main function
#######################################
def main() -> NoReturn:
    """Main entry point."""
    args = parse_args()
    
    os.chdir(ROOT_DIR)
    
    # Determine version
    version = args.version
    if not version:
        version = get_version()
        if version == "unknown":
            log.error("Version argument is required (could not detect from version.py)")
            sys.exit(1)
        log.info(f"Using version from version.py: {version}")
    
    version_tag, _ = normalize_version(version)
    
    # Determine notes file
    if args.notes_file:
        notes_file = Path(args.notes_file)
    else:
        notes_file = RELEASES_DIR / f"release_notes_{version_tag}.md"
    
    log.info("=" * 42)
    log.info("Publish GitHub Release for ZfDash")
    log.info("=" * 42)
    log.info(f"Version tag: {version_tag}")
    log.info(f"Notes file:  {notes_file}")
    log.info(f"Draft:       {args.draft}")
    log.info("=" * 42)
    
    #######################################
    # Pre-flight checks
    #######################################
    
    # Check gh CLI
    if not check_gh_cli():
        sys.exit(1)
    
    # Check releases directory
    if not RELEASES_DIR.exists():
        log.error(f"Releases directory not found: {RELEASES_DIR}")
        log.error("Run generate_tarball.py first to create tarballs.")
        sys.exit(1)
    
    # Find tarballs and hash files
    tarballs = sorted(RELEASES_DIR.glob("*.tar.gz"))
    hashfiles = sorted(RELEASES_DIR.glob("*.sha256"))
    
    if not tarballs:
        log.error(f"No tarballs found in {RELEASES_DIR}")
        log.error("Run generate_tarball.py first to create tarballs.")
        sys.exit(1)
    
    log.info(f"Found {len(tarballs)} tarball(s) to upload:")
    for tb in tarballs:
        log.info(f"  - {tb.name}")
    
    if hashfiles:
        log.info(f"Found {len(hashfiles)} hash file(s) to upload:")
        for hf in hashfiles:
            log.info(f"  - {hf.name}")
    
    # Check notes file
    if not notes_file.exists():
        log.warn(f"Release notes file not found: {notes_file}")
        log.warn("Run generate_notes.py first, or a minimal note will be created.")
        
        if confirm("Create minimal release notes?", args.auto_yes):
            create_minimal_notes(notes_file, version_tag)
            log.info(f"Created minimal release notes: {notes_file}")
        else:
            log.error("Cannot publish without release notes. Aborting.")
            sys.exit(1)
    
    # Display notes
    print()
    print("=" * 46)
    print("Release notes:")
    print("=" * 46)
    print(notes_file.read_text(encoding="utf-8"))
    print("=" * 46)
    
    #######################################
    # Git tag handling
    #######################################
    local_tag_exists = check_tag_exists(version_tag, remote=False)
    remote_tag_exists = check_tag_exists(version_tag, remote=True)
    
    if local_tag_exists:
        log.info(f"Tag {version_tag} already exists locally.")
    else:
        if confirm(f"Create git tag {version_tag}?", args.auto_yes):
            log.info(f"Creating git tag {version_tag}")
            if not create_tag(version_tag):
                log.error(f"Failed to create tag {version_tag}")
                sys.exit(1)
        else:
            log.error("Cannot publish without a tag. Aborting.")
            sys.exit(1)
    
    if remote_tag_exists:
        log.info(f"Tag {version_tag} already exists on remote.")
    else:
        if confirm(f"Push tag {version_tag} to origin?", args.auto_yes):
            log.info(f"Pushing tag {version_tag} to origin")
            if not push_tag(version_tag):
                log.error(f"Failed to push tag {version_tag}")
                sys.exit(1)
        else:
            log.error("Cannot publish without pushing the tag. Aborting.")
            sys.exit(1)
    
    #######################################
    # Create GitHub release
    #######################################
    all_files = tarballs + hashfiles
    
    if release_exists(version_tag):
        log.warn(f"Release {version_tag} already exists on GitHub.")
        if confirm("Upload assets to existing release?", args.auto_yes):
            log.info(f"Uploading assets to existing release {version_tag}")
            upload_assets(version_tag, all_files)
        else:
            log.error("Aborted by user.")
            sys.exit(1)
    else:
        if confirm(f"Create GitHub release {version_tag}?", args.auto_yes):
            log.info(f"Creating GitHub release {version_tag}")
            if not create_release(
                version_tag,
                f"ZfDash {version_tag}",
                notes_file,
                all_files,
                draft=args.draft,
            ):
                sys.exit(1)
        else:
            log.error("Aborted by user.")
            sys.exit(1)
    
    #######################################
    # Summary
    #######################################
    print()
    log.info("=" * 42)
    log.info("GitHub Release Published!")
    log.info("=" * 42)
    log.info(f"Version: {version_tag}")
    log.info("Files uploaded:")
    for f in all_files:
        log.info(f"  - {f.name}")
    log.info("=" * 42)
    log.info(f"View release: gh release view {version_tag}")
    
    sys.exit(0)


if __name__ == "__main__":
    main()
