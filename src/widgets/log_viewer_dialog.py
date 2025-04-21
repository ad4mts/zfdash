# --- START OF FILE log_viewer_dialog.py ---

import sys
import os
import traceback # For error logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QDialogButtonBox, QApplication,
    QCheckBox, QPushButton, QMessageBox
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, Slot

# Import the config manager
try:
    import config_manager
except ImportError:
    # Mock for standalone testing
    print("Warning: config_manager not found, using mock.", file=sys.stderr)
    class MockConfigManager:
        def get_setting(self, key, default): return default
        def set_setting(self, key, value): pass
        def get_viewer_log_file_path(self): return "mock_zfdash.log" # Use viewer path getter
    config_manager = MockConfigManager()


class LogViewerDialog(QDialog):
    """A dialog to display text logs, clear them, and enable/disable logging."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ZfDash Log Viewer")
        self.setMinimumSize(700, 500)
        # Get the log path from the viewer's perspective
        self._log_file_path = config_manager.get_viewer_log_file_path()

        layout = QVBoxLayout(self)

        # --- Toolbar ---
        toolbar_layout = QHBoxLayout()
        self.enable_logging_checkbox = QCheckBox("Enable Command Logging")
        self.enable_logging_checkbox.setToolTip("Log executed ZFS commands and their output to the log file.")
        # Load setting from user's config
        self.enable_logging_checkbox.setChecked(config_manager.get_setting('logging_enabled', False))
        self.enable_logging_checkbox.stateChanged.connect(self._toggle_logging)

        self.refresh_button = QPushButton("Refresh Log")
        self.refresh_button.setToolTip("Reload the log content from the file.")
        self.refresh_button.clicked.connect(self.load_log_content)

        self.clear_log_button = QPushButton("Clear Log File")
        self.clear_log_button.setToolTip("Delete the contents of the log file.")
        self.clear_log_button.clicked.connect(self._clear_log_file)

        toolbar_layout.addWidget(self.enable_logging_checkbox)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.refresh_button)
        toolbar_layout.addWidget(self.clear_log_button)
        layout.addLayout(toolbar_layout)

        # --- Log Display ---
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Monospace", 10)) # Use monospace font
        layout.addWidget(self.text_edit)

        # --- Dialog Buttons ---
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject) # Close connects to reject
        layout.addWidget(button_box)

        self.setLayout(layout)
        self.load_log_content() # Load initially

    @Slot()
    def load_log_content(self):
        """Reads the log file and displays its content."""
        self.text_edit.clear()
        log_path = self._log_file_path # Use stored path
        if not os.path.exists(log_path):
            self.text_edit.setText(f"(Log file '{log_path}' does not exist yet)")
            return
        try:
            with open(log_path, 'r', errors='replace') as f: # Added errors='replace'
                 # Limit reading size to prevent memory issues with huge logs
                 log_content = f.read(5 * 1024 * 1024) # Read max 5MB
                 if len(log_content) == 5 * 1024 * 1024:
                     log_content += "\n\n--- Log file truncated due to size ---"
                 self.text_edit.setPlainText(log_content)
                 # Scroll to the bottom
                 self.text_edit.verticalScrollBar().setValue(self.text_edit.verticalScrollBar().maximum())
        except PermissionError:
             self.text_edit.setText(f"Permission denied reading log file:\n'{log_path}'\n\n(Check permissions on /run/user/UID/ or the log file itself)")
        except IOError as e:
            self.text_edit.setText(f"Error reading log file '{log_path}':\n{e}")
        except Exception as e:
             self.text_edit.setText(f"An unexpected error occurred reading the log file:\n{e}\n{traceback.format_exc()}")

    @Slot(int)
    def _toggle_logging(self, state):
        """Saves the logging enabled state."""
        enabled = (state == Qt.CheckState.Checked.value)
        # Save setting to user's config
        config_manager.set_setting('logging_enabled', enabled)
        # Inform user, change takes effect for commands sent *after* this point
        QMessageBox.information(self, "Logging Status Changed",
                                f"Command logging has been {'enabled' if enabled else 'disabled'}.\n"
                                f"Changes take effect for subsequent commands executed by the daemon.")

    @Slot()
    def _clear_log_file(self):
        """Clears the content of the log file."""
        log_path = self._log_file_path # Use stored path
        reply = QMessageBox.warning(self, "Confirm Clear Log",
                                     f"Are you sure you want to permanently clear the log file?\n'{log_path}'",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Open in write mode to truncate
                with open(log_path, 'w') as f:
                    f.truncate(0)
                self.load_log_content() # Refresh display
                QMessageBox.information(self, "Log Cleared", "Log file content has been cleared.")
            except PermissionError:
                QMessageBox.critical(self, "Error Clearing Log", f"Permission denied clearing log file:\n'{log_path}'")
            except IOError as e:
                QMessageBox.critical(self, "Error Clearing Log", f"Could not clear the log file:\n{e}")
            except Exception as e:
                QMessageBox.critical(self, "Error Clearing Log", f"An unexpected error occurred:\n{e}")

# Example Usage (for testing)
if __name__ == '__main__':
    app = QApplication(sys.argv)
    # Create a dummy log file for testing in the expected location
    dummy_log_path = config_manager.get_viewer_log_file_path()
    try:
        os.makedirs(os.path.dirname(dummy_log_path), exist_ok=True)
        with open(dummy_log_path, 'w') as f:
            f.write("Existing log line 1.\n")
            f.write("Existing log line 2.\n")
    except IOError:
        pass # Ignore if cannot create dummy file
    dialog = LogViewerDialog()
    dialog.exec()
    # Clean up dummy file
    # try: os.remove(dummy_log_path)
    # except OSError: pass
    sys.exit()
# --- END OF FILE log_viewer_dialog.py ---
