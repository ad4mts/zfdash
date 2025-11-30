# --- START OF FILE src/version.py ---
"""
Single source of truth for ZfDash version and app information.
All other components should import from this module.
"""

__version__ = "1.8.8-beta"
__app_name__ = "ZfDash"
__app_description__ = "A modern graphical interface for managing ZFS storage pools, datasets, snapshots, and encryption."
__author__ = "Ayham(ad4mts) and Contributors"
__license__ = "GNU General Public License v3.0"
__repository__ = "https://github.com/ad4mts/zfdash"
__copyright__ = "© 2024-2025 ZfDash"

# Note: Docker step-by-step commands are now maintained in
# `src/data/update_instructions.json` and fetched dynamically by the
# update checker / UI. Keep this module focused on app/version metadata.

def get_version_info():
    """Return a dictionary with all version and app information."""
    return {
        "version": __version__,
        "app_name": __app_name__,
        "description": __app_description__,
        "author": __author__,
        "license": __license__,
        "repository": __repository__,
        "copyright": __copyright__
    }

def get_update_info():
    """Return update-related information including Docker commands."""
    return {
        "version": __version__,
        "repository": __repository__,
        "releases_url": f"{__repository__}/releases",
    }
