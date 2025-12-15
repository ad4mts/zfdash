# --- START OF FILE src/gui_runner.py ---
import sys
import os
import traceback

from paths import ICON_PATH

# GUI Imports
try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtGui import QIcon
    from PySide6.QtCore import Qt
    # Import MainWindow later inside start_gui to ensure QApplication exists first
except ImportError as e:
    print(f"FATAL: Failed to import essential PySide6 components: {e}\n{traceback.format_exc()}", file=sys.stderr)
    # Attempt basic error display if possible
    try:
        _app = QApplication([])
        QMessageBox.critical(None, "Import Error", f"Failed to load PySide6 components:\n{e}\n\nApplication cannot start.")
    except Exception:
        pass
    sys.exit(1)

# --- Import Daemon Utilities & Others ---
try:
    # Import other non-GUI core modules if needed directly by this runner
    pass
except ImportError as e:
    print(f"FATAL: Failed to import core utility modules: {e}\n{traceback.format_exc()}", file=sys.stderr)
    try:
        # Use existing QApplication if available, otherwise create a temporary one
        _app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, "Import Error", f"Failed to load core ZFS components:\n{e}\n\nApplication cannot start.")
    except Exception:
        pass
    sys.exit(1)

# --- Import New ZFS Manager Client ---
from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError

# --- Import Version from single source of truth ---
from version import __version__, __app_name__

# --- Constants ---
APP_NAME = __app_name__
APP_VERSION = __version__
APP_ORG = "ZfDash"

# --- Helper Functions ---
_qt_app_for_errors = None
def show_critical_error(title, message):
    """Displays a critical error message box."""
    global _qt_app_for_errors
    print(f"CRITICAL ERROR: {title}\n{message}", file=sys.stderr) # Always print
    try:
        if QApplication.instance() is None:
             if _qt_app_for_errors is None: _qt_app_for_errors = QApplication([])
        QMessageBox.critical(None, title, message)
    except Exception as e:
        print(f"GUI_RUNNER: Error displaying GUI error message: {e}", file=sys.stderr)


def _ensure_desktop_file_for_wayland():
    """
    Ensure a .desktop file exists for Wayland icon support.
    
    Wayland requires a .desktop file to show application icons - setWindowIcon() alone
    doesn't work. This function creates a user-local .desktop file if:
    - Running on Linux (Wayland is Linux-only)
    - No system-level .desktop file exists (/usr/share/applications/zfdash.desktop)
    - Icon file exists
    
    The file is cleaned up on exit to avoid leaving a broken menu entry.
    """
    import platform
    import atexit
    
    if platform.system() != 'Linux':
        return  # Wayland is Linux-only
    
    # Check if system-level .desktop file exists (installed via install.sh)
    system_desktop = '/usr/share/applications/zfdash.desktop'
    if os.path.exists(system_desktop):
        return  # Already installed, use system file
    
    # Check if icon exists
    if not os.path.exists(ICON_PATH):
        return  # No icon to reference
    
    # Create user-local .desktop file using XDG-compliant path
    from pathlib import Path
    xdg_data_home = os.environ.get('XDG_DATA_HOME', os.path.join(str(Path.home()), '.local', 'share'))
    local_apps_dir = os.path.join(xdg_data_home, 'applications')
    local_desktop = os.path.join(local_apps_dir, 'zfdash.desktop')
    
    try:
        os.makedirs(local_apps_dir, exist_ok=True)
        
        # Determine executable command and working directory based on how we're running
        from paths import DAEMON_SCRIPT_PATH, DAEMON_IS_SCRIPT, RESOURCES_BASE_DIR
        if DAEMON_IS_SCRIPT:
            # Running from source - use uv run with project directory
            exec_cmd = f"uv run {DAEMON_SCRIPT_PATH}"
            # Project root is parent of src/ (RESOURCES_BASE_DIR is src/)
            project_dir = os.path.dirname(str(RESOURCES_BASE_DIR))
            path_line = f"Path={project_dir}"
        else:
            # Frozen executable
            exec_cmd = DAEMON_SCRIPT_PATH
            path_line = ""  # Not needed for frozen
        
        # Write .desktop file with absolute paths
        desktop_content = f"""[Desktop Entry]
Type=Application
Name=ZfDash
Comment=ZFS Management Dashboard
Icon={ICON_PATH}
Exec={exec_cmd}
{path_line}
Terminal=false
Categories=System;Utility;
StartupWMClass=zfdash
"""
        with open(local_desktop, 'w') as f:
            f.write(desktop_content)
        
        # Register cleanup on exit
        def cleanup_desktop_file():
            try:
                if os.path.exists(local_desktop):
                    os.remove(local_desktop)
            except Exception:
                pass  # Best effort cleanup
        
        atexit.register(cleanup_desktop_file)
        
    except Exception as e:
        # Non-fatal - icon just won't show on Wayland
        print(f"WARN: Could not create .desktop file for Wayland: {e}", file=sys.stderr)


# --- Main GUI Application Entry Point Function (Modified) ---
def start_gui(zfs_client: ZfsManagerClient):
    """Sets up and runs the main GUI application, using the provided ZFS client."""

    # --- Daemon is already launched by main.py ---
    if zfs_client is None:
        show_critical_error("Internal Error", "ZFS Manager Client was not provided to the GUI runner.")
        sys.exit(1)
    print("GUI_RUNNER: Using provided ZFS Manager Client.")

    print("GUI_RUNNER: Starting GUI process...")
    # --- Set up Qt Application ---
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication.instance() or QApplication(sys.argv)
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationVersion(APP_VERSION)
    QApplication.setOrganizationName(APP_ORG)
    


    # --- Set Window Icon (Path from paths.py module) ---
    # Ensure Wayland can find the icon via .desktop file
    _ensure_desktop_file_for_wayland()
    QApplication.setDesktopFileName("zfdash")
    #------------------------------------------
    try:
        if os.path.exists(ICON_PATH):
            app.setWindowIcon(QIcon(ICON_PATH))
        else:
            print(f"WARN: Window icon not found at path: {ICON_PATH}", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: Failed to set window icon: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr) # Print traceback for icon errors
    # --- End Set Window Icon ---


    # --- Create and Show Main Window (Pass ZFS Client) ---
    try:
        from main_window import MainWindow
        # Pass the zfs_client instance to the MainWindow constructor
        main_win = MainWindow(zfs_client=zfs_client)
        main_win.show()
    except Exception as e:
        show_critical_error("GUI Initialization Error", f"Failed to initialize the main window:\n{e}\n\n{traceback.format_exc()}")
        # The main.py finally block should handle this.
        sys.exit(1)

    # --- Start Event Loop ---
    exit_code = app.exec()

    # --- Cleanup ---
    # Explicitly delete Python references to Qt objects to encourage destruction
    # BEFORE Python's shutdown phase (Py_Finalize).
    try:
        del main_win
    except NameError:
        pass
    
    return exit_code

# --- END OF FILE src/gui_runner.py ---
