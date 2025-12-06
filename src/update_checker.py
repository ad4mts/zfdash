# --- START OF FILE src/update_checker.py ---
"""
Update checker module for ZfDash.
Checks GitHub releases API for new versions and fetches update instructions.
"""

import urllib.request
import json
import ssl
import os
import certifi
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from version import __version__, __repository__

# GitHub API endpoint for latest release
GITHUB_API_URL = f"https://api.github.com/repos/ad4mts/zfdash/releases/latest"
# Raw GitHub URL for update instructions (fetches from src/data/ in repo)
INSTRUCTIONS_URL = "https://raw.githubusercontent.com/ad4mts/zfdash/main/src/data/update_instructions.json"
REQUEST_TIMEOUT = 10  # seconds

# Local fallback path for update instructions (follows paths.py pattern)
def _get_local_instructions_path() -> str:
    """Get the path to local update instructions file, respecting deployment type."""
    # Import here to avoid circular imports
    try:
        from paths import RESOURCES_BASE_DIR
        local_path = RESOURCES_BASE_DIR / "data" / "update_instructions.json"
    except ImportError:
        # Fallback if paths module not available
        local_path = Path(__file__).parent / "data" / "update_instructions.json"
    return str(local_path)


def parse_version(version_str: str) -> Tuple[int, ...]:
    """
    Parse a version string into a tuple for comparison.
    Handles formats like: 1.8.5, 1.8.5-beta, v1.8.5-beta
    Pre-release versions (with -beta, -alpha, etc.) are considered lower than release versions.
    """
    # Remove 'v' prefix if present
    version_str = version_str.lstrip('v')
    
    # Split on hyphen to separate version from pre-release tag
    parts = version_str.split('-', 1)
    main_version = parts[0]
    is_prerelease = len(parts) > 1
    
    # Parse main version numbers
    try:
        version_tuple = tuple(int(x) for x in main_version.split('.'))
    except ValueError:
        version_tuple = (0, 0, 0)
    
    # Add a final element: 0 for release, -1 for pre-release
    # This makes 1.8.5 > 1.8.5-beta
    return version_tuple + (-1 if is_prerelease else 0,)


def compare_versions(current: str, latest: str) -> int:
    """
    Compare two version strings.
    Returns:
        -1 if current < latest (update available)
         0 if current == latest (up to date)
         1 if current > latest (current is newer, e.g., dev version)
    """
    current_tuple = parse_version(current)
    latest_tuple = parse_version(latest)
    
    if current_tuple < latest_tuple:
        return -1
    elif current_tuple > latest_tuple:
        return 1
    else:
        return 0


def check_for_updates() -> dict:
    """
    Check GitHub releases API for the latest version.
    
    Returns:
        dict with keys:
            - success: bool - whether the check succeeded
            - error: str or None - error message if failed
            - current_version: str - current installed version
            - latest_version: str or None - latest version from GitHub
            - update_available: bool - True if a newer version exists
            - release_url: str or None - URL to the release page
            - release_notes: str or None - Brief release notes/title
    """
    result = {
        "success": False,
        "error": None,
        "current_version": __version__,
        "latest_version": None,
        "update_available": False,
        "release_url": None,
        "release_notes": None,
    }
    
    try:
        # Create a request with a User-Agent header (required by GitHub API)
        request = urllib.request.Request(
            GITHUB_API_URL,
            headers={
                "User-Agent": f"ZfDash/{__version__}",
                "Accept": "application/vnd.github.v3+json"
            }
        )
        
        # Create SSL context (use certifi CA certificates for cross-platform reliability)
        context = ssl.create_default_context(cafile=certifi.where())
        
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT, context=context) as response:
            data = json.loads(response.read().decode('utf-8'))
        
        # Extract version from tag_name (e.g., "v1.8.5" -> "1.8.5")
        tag_name = data.get("tag_name", "")
        latest_version = tag_name.lstrip('v')
        
        result["latest_version"] = latest_version
        result["release_url"] = data.get("html_url", f"{__repository__}/releases/latest")
        result["release_notes"] = data.get("name", "") or data.get("body", "")[:200]
        
        # Compare versions
        comparison = compare_versions(__version__, latest_version)
        result["update_available"] = comparison < 0
        result["success"] = True
        
    except urllib.error.HTTPError as e:
        result["error"] = f"GitHub API error: HTTP {e.code}"
    except urllib.error.URLError as e:
        result["error"] = f"Network error: {e.reason}"
    except json.JSONDecodeError:
        result["error"] = "Invalid response from GitHub API"
    except Exception as e:
        result["error"] = f"Unexpected error: {str(e)}"
    
    return result


def fetch_update_instructions(deployment_type: str = "native") -> Dict[str, Any]:
    """
    Fetch update instructions from remote GitHub, with local fallback.
    
    Args:
        deployment_type: One of "docker", "native", or "source"
    
    Returns:
        dict with keys:
            - success: bool - whether fetch succeeded
            - source: str - "remote" or "local"
            - title: str - instruction set title
            - steps: list - list of step dicts with title, command/description
            - notes: list - additional notes
            - error: str or None - error message if both remote and local failed
    """
    result = {
        "success": False,
        "source": None,
        "title": "",
        "steps": [],
        "notes": [],
        "error": None,
    }
    
    instructions_data = None
    
    # Try fetching from remote first
    try:
        request = urllib.request.Request(
            INSTRUCTIONS_URL,
            headers={"User-Agent": f"ZfDash/{__version__}"}
        )
        context = ssl.create_default_context(cafile=certifi.where())
        
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT, context=context) as response:
            instructions_data = json.loads(response.read().decode('utf-8'))
            result["source"] = "remote"
            
    except Exception as e:
        # Remote failed, try local fallback
        local_path = _get_local_instructions_path()
        try:
            with open(local_path, 'r', encoding='utf-8') as f:
                instructions_data = json.load(f)
                result["source"] = "local"
        except Exception as local_error:
            result["error"] = f"Remote: {str(e)}. Local fallback: {str(local_error)}"
            return result
    
    # Extract instructions for the specified deployment type
    if instructions_data and deployment_type in instructions_data:
        deployment_info = instructions_data[deployment_type]
        result["success"] = True
        result["title"] = deployment_info.get("title", "")
        result["steps"] = deployment_info.get("steps", [])
        result["notes"] = deployment_info.get("notes", [])
    else:
        result["error"] = f"No instructions found for deployment type: {deployment_type}"
    
    return result


def get_all_instructions() -> Dict[str, Any]:
    """
    Fetch all update instructions from remote GitHub, with local fallback.
    
    Returns:
        dict with keys:
            - success: bool
            - source: str - "remote" or "local"
            - docker: dict - Docker instructions
            - native: dict - Native/binary instructions
            - source: dict - Source/dev instructions
            - error: str or None
    """
    result = {
        "success": False,
        "source": None,
        "docker": None,
        "native": None,
        "dev": None,  # renamed from "source" to avoid conflict with result["source"]
        "error": None,
    }
    
    instructions_data = None
    
    # Try fetching from remote first
    try:
        request = urllib.request.Request(
            INSTRUCTIONS_URL,
            headers={"User-Agent": f"ZfDash/{__version__}"}
        )
        context = ssl.create_default_context(cafile=certifi.where())
        
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT, context=context) as response:
            instructions_data = json.loads(response.read().decode('utf-8'))
            result["source"] = "remote"
            
    except Exception as e:
        # Remote failed, try local fallback
        local_path = _get_local_instructions_path()
        try:
            with open(local_path, 'r', encoding='utf-8') as f:
                instructions_data = json.load(f)
                result["source"] = "local"
        except Exception as local_error:
            result["error"] = f"Remote: {str(e)}. Local fallback: {str(local_error)}"
            return result
    
    if instructions_data:
        result["success"] = True
        result["docker"] = instructions_data.get("docker")
        result["native"] = instructions_data.get("native")
        result["dev"] = instructions_data.get("source")  # "source" in JSON -> "dev" in result
    
    return result


# For testing
if __name__ == "__main__":
    print(f"Current version: {__version__}")
    print("Checking for updates...")
    result = check_for_updates()
    print(json.dumps(result, indent=2))
    
    print("\nFetching update instructions...")
    instructions = get_all_instructions()
    print(json.dumps(instructions, indent=2))
