# --- START OF FILE src/version.py ---
"""
Single source of truth for ZfDash version and app information.
All other components should import from this module.
"""

__version__ = "1.8.5"
__app_name__ = "ZfDash"
__app_description__ = "A modern graphical interface for managing ZFS storage pools, datasets, snapshots, and encryption."
__author__ = "Ayham(ad4mts) and Contributors"
__license__ = "GNU General Public License v3.0"
__repository__ = "https://github.com/ad4mts/zfdash"
__copyright__ = "© 2024-2025 ZfDash"

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
