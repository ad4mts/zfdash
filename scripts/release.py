#!/usr/bin/env python3
"""
Main release orchestrator script for zfdash.

Combines all release functionality: build, tarball, notes, and GitHub publish.

Usage:
    python scripts/release.py [--github] [--yes|-y] [--clean]

This script orchestrates the release process by calling:
  1. generate_tarball.py - Build and create tarball with hash
  2. generate_notes.py   - Generate release notes from changelog
  3. publish_release.py  - Create GitHub release (if --github)

Options:
  --github    Create GitHub release using gh CLI
  --yes, -y   Skip confirmation prompts (auto-yes) and note editing
  --clean     Clean build before creating tarball
  --draft     Create as draft release (not visible to users); requires --github
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


def run_python_script(
    script_name: str,
    args: list[str] | None = None,
) -> bool:
    """
    Run a Python script from the scripts directory.
    
    Args:
        script_name: Name of the script (e.g., "generate_tarball.py").
        args: Additional arguments to pass to the script.
    
    Returns:
        True if script succeeded, False otherwise.
    """
    script_path = SCRIPT_DIR / script_name
    
    if not script_path.exists():
        log.error(f"Script not found: {script_path}")
        return False
    
    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)
    
    log.info(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, cwd=ROOT_DIR, check=False)
        return result.returncode == 0
    except OSError as e:
        log.error(f"Failed to run script: {e}")
        return False


def wait_for_user_edit(notes_file: Path) -> bool:
    """
    Wait for user to edit release notes.
    
    Args:
        notes_file: Path to the release notes file.
    
    Returns:
        True to continue, False to abort.
    """
    print()
    print("=" * 46)
    print("You can now edit the release notes at:")
    print(f"  {notes_file}")
    print("=" * 46)
    print()
    
    try:
        response = input("Press ENTER when ready to continue, or type 'abort' to stop: ")
        if response.strip().lower() == "abort":
            return False
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    
    # Show final notes
    print()
    print("=" * 46)
    print("Final release notes:")
    print("=" * 46)
    if notes_file.exists():
        print(notes_file.read_text(encoding="utf-8"))
    print("=" * 46)
    
    return True


#######################################
# Argument parsing
#######################################
def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Full release workflow for zfdash.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  1. Build and create tarball (generate_tarball.py)
  2. Generate release notes (generate_notes.py)
  3. Optionally publish to GitHub (publish_release.py)

Version is automatically detected from src/version.py.

Individual scripts:
  python scripts/generate_tarball.py  - Build and create tarball only
  python scripts/generate_notes.py    - Generate release notes only
  python scripts/publish_release.py   - Publish to GitHub only

Examples:
  python scripts/release.py                  # Interactive release
  python scripts/release.py --github         # Interactive with GitHub publish
  python scripts/release.py --github --yes   # Fully automated release
        """,
    )
    parser.add_argument(
        "--github",
        action="store_true",
        help="Create GitHub release using gh CLI",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        dest="auto_yes",
        help="Skip confirmation prompts and note editing",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean build before creating tarball",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Create as draft release (not visible to users)",
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
    if version == "unknown":
        log.error("Could not detect version from src/version.py")
        sys.exit(1)
    
    version_tag, _ = normalize_version(version)
    
    log.info("=" * 42)
    log.info("ZfDash Release Workflow")
    log.info("=" * 42)
    log.info(f"Version: {version_tag}")
    log.info(f"GitHub:  {args.github}")
    log.info(f"Draft:   {args.draft}")
    log.info(f"Auto:    {args.auto_yes}")
    log.info("=" * 42)
    
    #######################################
    # Check required scripts exist
    #######################################
    required_scripts = ["generate_tarball.py", "generate_notes.py"]
    if args.github:
        required_scripts.append("publish_release.py")
    
    for script in required_scripts:
        script_path = SCRIPT_DIR / script
        if not script_path.exists():
            log.error(f"Required script not found: {script_path}")
            sys.exit(1)
    
    #######################################
    # Step 1: Generate tarball
    #######################################
    log.info("")
    log.info("=" * 42)
    log.info("Step 1: Generate Tarball")
    log.info("=" * 42)
    
    tarball_args = []
    if args.auto_yes:
        tarball_args.append("--yes")
    if args.clean:
        tarball_args.append("--clean")
    
    if not run_python_script("generate_tarball.py", tarball_args):
        log.error("Tarball generation failed. Aborting.")
        sys.exit(1)
    
    #######################################
    # Step 2: Generate release notes
    #######################################
    log.info("")
    log.info("=" * 42)
    log.info("Step 2: Generate Release Notes")
    log.info("=" * 42)
    
    notes_file = RELEASES_DIR / f"release_notes_{version_tag}.md"
    
    if not run_python_script("generate_notes.py", [version]):
        log.error("Release notes generation failed. Aborting.")
        sys.exit(1)
    
    #######################################
    # Step 3: Allow user to edit notes (if not --yes)
    #######################################
    if args.auto_yes:
        log.info("Skipping manual edit prompt (--yes flag provided).")
    else:
        if not wait_for_user_edit(notes_file):
            log.error("Aborted by user after editing release notes.")
            sys.exit(1)
    
    #######################################
    # Step 4: Publish to GitHub (if --github)
    #######################################
    if args.github:
        log.info("")
        log.info("=" * 42)
        log.info("Step 3: Publish GitHub Release")
        log.info("=" * 42)
        
        publish_args = [version]
        if args.auto_yes:
            publish_args.append("--yes")
        if args.draft:
            publish_args.append("--draft")
        
        if not run_python_script("publish_release.py", publish_args):
            log.error("GitHub release failed.")
            sys.exit(1)
    else:
        log.info("")
        log.info("Skipping GitHub release (use --github to publish).")
        log.info("To publish later, run:")
        log.info(f"  python scripts/publish_release.py {version}")
    
    #######################################
    # Summary
    #######################################
    print()
    log.info("=" * 42)
    log.info("Release Workflow Complete!")
    log.info("=" * 42)
    log.info(f"Version: {version_tag}")
    log.info(f"Releases directory: {RELEASES_DIR}")
    log.info("")
    log.info("Files created:")
    
    # List all release files
    if RELEASES_DIR.exists():
        for pattern in ("*.tar.gz", "*.sha256", "*.md"):
            for f in sorted(RELEASES_DIR.glob(pattern)):
                size = f.stat().st_size
                log.info(f"  {f.name} ({size:,} bytes)")
    
    log.info("=" * 42)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
