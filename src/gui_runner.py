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

# --- Constants ---
APP_NAME = "ZfDash"
APP_VERSION = "1.7.5" # Consider reading from a central place
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
    sys.exit(app.exec())

# --- END OF FILE src/gui_runner.py ---
