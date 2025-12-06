#!/usr/bin/env python3
"""
Generate release notes script for zfdash.

Extracts changelog entries and generates formatted release notes.

Usage:
    python scripts/generate_notes.py [version] [--output FILE]

Notes are generated without checksums (hash files are separate).
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
CHANGELOG_FILE = ROOT_DIR / "changelog.txt"
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
        A tuple of (display_version, match_version) where display_version
        has the 'v' prefix and match_version does not.
    """
    match_version = version.lstrip("v")
    display_version = f"v{match_version}"
    return display_version, match_version


def extract_changelog(version: str) -> list[str]:
    """
    Extract changelog entries for a specific version.
    
    Parses changelog.txt and extracts bullet points for the given version.
    
    Args:
        version: Version string (e.g., "v1.8.5-beta" or "1.8.5-beta").
    
    Returns:
        List of changelog entries, or empty list if not found.
    """
    if not CHANGELOG_FILE.exists():
        log.warn(f"Changelog file not found: {CHANGELOG_FILE}")
        return []
    
    try:
        content = CHANGELOG_FILE.read_text(encoding="utf-8")
    except OSError as e:
        log.warn(f"Failed to read changelog: {e}")
        return []
    
    # Normalize version for matching (case-insensitive, handle v prefix)
    _, match_version = normalize_version(version)
    
    # Pattern to match version headers (## vX.X.X or ## X.X.X)
    header_pattern = re.compile(r"^##\s+(v?[\d]+\.[\d]+\.[\d]+[^\s]*)", re.IGNORECASE)
    # Pattern to match bullet points (* or -)
    bullet_pattern = re.compile(r"^\s*[\*\-]\s+(.+)$")
    
    entries: list[str] = []
    in_section = False
    
    for line in content.splitlines():
        # Check if this is a version header line
        header_match = header_pattern.match(line)
        if header_match:
            header_version = header_match.group(1).lstrip("v").lower()
            
            if header_version == match_version.lower():
                in_section = True
                continue
            elif in_section:
                # We've hit the next version section, stop
                break
        
        # If we're in the target section, collect bullet points
        if in_section:
            bullet_match = bullet_pattern.match(line)
            if bullet_match:
                entries.append(bullet_match.group(1))
    
    return entries


def run_git_command(*args: str) -> str | None:
    """
    Run a git command and return the output.
    
    Args:
        *args: Git command arguments.
    
    Returns:
        Command output as string, or None if command failed.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=ROOT_DIR,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        pass
    return None


def get_git_info(version: str) -> tuple[str | None, str | None]:
    """
    Get git information for changelog link.
    
    Args:
        version: The current version being released.
    
    Returns:
        A tuple of (previous_tag, github_url).
    """
    display_version, match_version = normalize_version(version)
    
    # Get latest git tag (previous version)
    latest_tag = run_git_command("describe", "--tags", "--abbrev=0")
    
    # If latest tag is the same as current version, get the one before
    if latest_tag in (display_version, match_version):
        tags_output = run_git_command("tag", "--sort=-v:refname")
        if tags_output:
            for tag in tags_output.splitlines():
                if tag not in (display_version, match_version):
                    latest_tag = tag
                    break
    
    # Get GitHub URL
    remote_url = run_git_command("remote", "get-url", "origin")
    github_url = None
    
    if remote_url:
        # Convert SSH URL to HTTPS
        if remote_url.startswith("git@"):
            # git@github.com:user/repo.git -> https://github.com/user/repo
            match = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", remote_url)
            if match:
                github_url = f"https://{match.group(1)}/{match.group(2)}"
        else:
            # Remove .git suffix if present
            github_url = re.sub(r"\.git$", "", remote_url)
    
    return latest_tag, github_url


def generate_changelog_link(
    version: str,
    previous_tag: str | None,
    github_url: str | None,
) -> str:
    """
    Generate a changelog comparison link.
    
    Args:
        version: Current version.
        previous_tag: Previous version tag.
        github_url: GitHub repository URL.
    
    Returns:
        Changelog link or "N/A".
    """
    display_version, _ = normalize_version(version)
    
    if github_url and previous_tag:
        return f"{github_url}/compare/{previous_tag}...{display_version}"
    elif github_url:
        return f"{github_url}/commits/{display_version}"
    
    return "N/A"


def format_release_notes(
    version: str,
    entries: list[str],
    changelog_link: str,
) -> str:
    """
    Format the release notes as markdown.
    
    Args:
        version: Version string.
        entries: List of changelog entries.
        changelog_link: Link to full changelog.
    
    Returns:
        Formatted release notes as a string.
    """
    display_version, _ = normalize_version(version)
    
    # Format changelog entries
    if entries:
        formatted_changes = "\n".join(f"  - {entry}" for entry in entries)
    else:
        formatted_changes = "  - (Add your changes here)"
    
    return f"""## ZfDash {display_version}

### Changes in this release:
{formatted_changes}

> **IMPORTANT:** This is BETA software. Use cautiously, ensure backups, and change the default Web UI password (admin/admin) immediately. Incorrect use can lead to **PERMANENT DATA LOSS**.

### Installation
Extract and run `sudo ./install.sh` (after `chmod +x install.sh`) for system-wide installation. See README for details. Licensed under GPLv3.

### Checksums
See the `.sha256` files accompanying each tarball for verification.

**Full Changelog**: {changelog_link}
"""


#######################################
# Argument parsing
#######################################
def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate release notes for zfdash from changelog.txt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Notes are created without checksums (hash files are separate).

Examples:
    python scripts/generate_notes.py v1.8.8-beta
    python scripts/generate_notes.py 1.8.8-beta --output my-notes.md
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
        "--output", "-o",
        dest="output_file",
        default=None,
        help="Output file path (default: releases/release_notes_<version>.md)",
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
    
    display_version, _ = normalize_version(version)
    
    # Determine output file
    output_file = args.output_file
    if not output_file:
        RELEASES_DIR.mkdir(parents=True, exist_ok=True)
        output_file = RELEASES_DIR / f"release_notes_{display_version}.md"
    else:
        output_file = Path(output_file)
    
    log.info("=" * 42)
    log.info("Generate Release Notes for ZfDash")
    log.info("=" * 42)
    log.info(f"Version: {display_version}")
    log.info(f"Output:  {output_file}")
    log.info("=" * 42)
    
    #######################################
    # Get git information
    #######################################
    previous_tag, github_url = get_git_info(version)
    changelog_link = generate_changelog_link(version, previous_tag, github_url)
    
    #######################################
    # Extract changelog entries
    #######################################
    log.info(f"Extracting changelog entries for {version}")
    entries = extract_changelog(version)
    
    if entries:
        log.info(f"Found {len(entries)} changelog entries for {version}")
    else:
        log.warn(f"No changelog entries found for {version}. Using placeholder.")
    
    #######################################
    # Write release notes
    #######################################
    notes_content = format_release_notes(version, entries, changelog_link)
    
    # Ensure parent directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(notes_content, encoding="utf-8")
    
    log.info(f"Release notes written to: {output_file}")
    
    #######################################
    # Display notes
    #######################################
    print()
    print("=" * 46)
    print("Release notes preview:")
    print("=" * 46)
    print(notes_content)
    print("=" * 46)
    print()
    log.info(f"You can edit the release notes at: {output_file}")
    
    sys.exit(0)


if __name__ == "__main__":
    main()
