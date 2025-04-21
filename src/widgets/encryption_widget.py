# --- START OF FILE widgets/encryption_widget.py ---

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QPushButton, QMessageBox,
    QGroupBox, QHBoxLayout, QInputDialog, QLineEdit, QFileDialog, QDialog,
    QCheckBox, QDialogButtonBox
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QIcon

from typing import Optional, Dict, Any
import os
import traceback # Import for debugging if needed

# Import client class
from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError
try:
    from models import Dataset
except ImportError:
    print("WARNING: EncryptionWidget could not import Dataset model.")
    class Dataset: pass # Dummy for standalone use/testing


# --- Helper Dialog for Passphrase Input ---
class PassphraseDialog(QDialog):
    """Simple dialog to get a single passphrase."""
    def __init__(self, title, label, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(label))
        self.passphrase_edit = QLineEdit()
        self.passphrase_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.passphrase_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_passphrase(self) -> Optional[str]:
        if self.result() == QDialog.DialogCode.Accepted:
            return self.passphrase_edit.text()
        return None

# --- Helper Dialog for Key Change ---
class ChangePassphraseDialog(QDialog): # Renamed for clarity
    """Dialog to get NEW passphrase twice for zfs change-key."""
    def __init__(self, dataset_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Set New Passphrase for {dataset_name}") # Updated title
        layout = QFormLayout(self)

        self.new_pass_edit = QLineEdit()
        self.new_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("New Passphrase:", self.new_pass_edit)

        self.confirm_pass_edit = QLineEdit()
        self.confirm_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("Confirm New Passphrase:", self.confirm_pass_edit)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)

    def validate_and_accept(self):
        """Validate input before accepting the dialog."""
        new_pass = self.new_pass_edit.text()
        confirm_pass = self.confirm_pass_edit.text()

        if not new_pass:
            QMessageBox.warning(self, "Input Missing", "New passphrase cannot be empty.")
            return
        if new_pass != confirm_pass:
            QMessageBox.warning(self, "Mismatch", "New passphrases do not match.")
            return

        self.accept()

    def get_change_info(self) -> Optional[str]:
        """Returns the formatted string (new\\nnew\\n) only if dialog was accepted."""
        if self.result() == QDialog.DialogCode.Accepted:
            new_pass = self.new_pass_edit.text()
            # ZFS change-key expects new\nnew\n for passphrase change via stdin when key is loaded
            return f"{new_pass}\n{new_pass}\n"
        return None

# --- Main Encryption Widget ---
class EncryptionWidget(QWidget):
    """Widget to display ZFS encryption status and provide key management actions."""

    load_key_requested = Signal(str, bool, str, str) # ds_name, recursive, key_location, passphrase
    unload_key_requested = Signal(str, bool) # ds_name, recursive
    change_key_requested = Signal(str, bool, bool, dict, str) # ds_name, load_key, recursive, options, change_info
    change_key_location_requested = Signal(str, str) # ds_name, new_location
    status_message = Signal(str)


    def __init__(self, zfs_client: ZfsManagerClient, parent=None):
        super().__init__(parent)
        self._current_dataset: Optional[Dataset] = None
        # Store the client instance
        self.zfs_client = zfs_client
        if self.zfs_client is None:
            raise ValueError("ZfsManagerClient instance is required for EncryptionWidget.")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Status Group
        status_group = QGroupBox("Encryption Status")
        status_layout = QFormLayout(status_group)
        self.status_label = QLabel("-"); self.algorithm_label = QLabel("-")
        self.key_status_label = QLabel("-"); self.key_location_label = QLabel("-")
        self.key_format_label = QLabel("-"); self.pbkdf2iters_label = QLabel("-")
        status_layout.addRow("Encrypted:", self.status_label)
        status_layout.addRow("Algorithm:", self.algorithm_label)
        status_layout.addRow("Key Status:", self.key_status_label)
        status_layout.addRow("Key Location:", self.key_location_label)
        status_layout.addRow("Key Format:", self.key_format_label)
        status_layout.addRow("PBKDF2 Iterations:", self.pbkdf2iters_label)
        main_layout.addWidget(status_group)

        # Actions Group
        actions_group = QGroupBox("Key Management Actions")
        actions_layout = QVBoxLayout(actions_group)
        self.load_key_button = QPushButton(QIcon.fromTheme("dialog-password"), " Load Key")
        self.load_key_button.clicked.connect(self._load_key)
        self.unload_key_button = QPushButton(QIcon.fromTheme("lock"), " Unload Key")
        self.unload_key_button.clicked.connect(self._unload_key)
        self.change_key_button = QPushButton(QIcon.fromTheme("svn-commit"), " Change Key/Passphrase")
        self.change_key_button.clicked.connect(self._change_key)
        self.change_key_location_button = QPushButton(QIcon.fromTheme("document-properties"), " Change Key Location")
        self.change_key_location_button.clicked.connect(self._change_key_location)
        actions_layout.addWidget(self.load_key_button)
        actions_layout.addWidget(self.unload_key_button)
        actions_layout.addWidget(self.change_key_button)
        actions_layout.addWidget(self.change_key_location_button)
        actions_layout.addStretch()
        main_layout.addWidget(actions_group)

        main_layout.addStretch()
        self.setLayout(main_layout)
        self._update_ui(None) # Initial state

    def set_dataset(self, dataset: Optional[Dataset]):
        self._current_dataset = dataset
        self._update_ui(dataset)

    def _update_ui(self, dataset: Optional[Dataset]):
        is_encrypted = False
        is_available = False
        key_status = "N/A"
        key_location = "-"
        key_format = "-"
        pbkdf2iters = "-"
        algorithm = "-"
        is_mounted = False

        if dataset:
            is_mounted = getattr(dataset, 'is_mounted', False)
            properties = getattr(dataset, 'properties', {})
            encryption_prop = properties.get('encryption', 'off')
            is_encrypted = (encryption_prop not in ('off', '-', None))

            if is_encrypted:
                 algorithm = encryption_prop
                 raw_keystatus = properties.get('keystatus')
                 # Treat missing status or '-' as 'unavailable' for logic
                 if raw_keystatus and raw_keystatus != '-':
                     key_status = raw_keystatus
                 else:
                     key_status = 'unavailable' # Assume unavailable if missing/placeholder

                 is_available = (key_status == 'available')

                 raw_key_location = properties.get('keylocation', 'prompt')
                 key_location = raw_key_location if raw_key_location and raw_key_location != '-' else 'prompt'
                 key_format = properties.get('keyformat', '-')
                 pbkdf2iters = properties.get('pbkdf2iters', '-')
            else:
                 key_status = "N/A (Not Encrypted)"

        # Update Labels
        self.status_label.setText("Yes" if is_encrypted else "No")
        self.algorithm_label.setText(algorithm if is_encrypted else "-")
        self.key_status_label.setText(key_status.capitalize())
        self.key_location_label.setText(key_location)
        self.key_format_label.setText(key_format)
        self.pbkdf2iters_label.setText(pbkdf2iters)

        # --- Update Button Enabled States ---
        load_enabled = is_encrypted and not is_available
        # *** CHANGE HERE: Unload button is enabled if the key is available,
        #     the click handler will check the mount status ***
        unload_enabled = is_encrypted and is_available
        change_key_enabled = is_encrypted and is_available # Requires key loaded
        change_loc_enabled = is_encrypted # Can change location property anytime if encrypted

        self.load_key_button.setEnabled(load_enabled)
        self.unload_key_button.setEnabled(unload_enabled)
        self.change_key_button.setEnabled(change_key_enabled)
        self.change_key_location_button.setEnabled(change_loc_enabled)

        # Update Tooltips
        load_tooltip = "Load the encryption key."
        if is_encrypted and not is_available:
             if key_location == 'prompt': load_tooltip = "Load key (will prompt for passphrase via GUI)"
             elif key_location.startswith('file://'): load_tooltip = f"Load key using location: {key_location}"
             elif key_status == 'unavailable': load_tooltip = "Load key (status is unavailable)"
             else: load_tooltip = f"Load key (current status: {key_status})"
        self.load_key_button.setToolTip(load_tooltip)

        unload_tooltip = "Unload the encryption key (makes data inaccessible)"
        # *** CHANGE HERE: Tooltip updated to reflect click behavior ***
        if is_mounted and is_encrypted and is_available:
            unload_tooltip += "\n(Dataset must be unmounted first)"
        elif not unload_enabled and is_encrypted: # If button disabled but encrypted
            unload_tooltip = "Key must be loaded (available) to unload."
        self.unload_key_button.setToolTip(unload_tooltip)

        change_tooltip = "Change the encryption key/passphrase"
        if is_encrypted and not is_available:
             change_tooltip += " (requires key to be loaded)"
        elif is_encrypted and is_available and key_format != 'passphrase':
            change_tooltip = "Change the encryption key file (requires current key to be loaded)"
        self.change_key_button.setToolTip(change_tooltip)

        self.change_key_location_button.setToolTip("Change where the key is stored (e.g., prompt, file URI)")

    # --- Action Methods ---

    @Slot()
    def _load_key(self):
        if not self._current_dataset: return
        ds_name = self._current_dataset.name
        properties = getattr(self._current_dataset, 'properties', {})
        key_location = properties.get('keylocation', 'prompt')
        key_format = properties.get('keyformat', 'passphrase')
        # Normalize location for logic, but pass original if needed? No, pass normalized or None.
        key_location_norm = key_location if key_location and key_location != '-' else 'prompt'
        recursive = False # Currently no UI option for recursive load
        passphrase_to_pass = None
        key_location_to_pass = key_location_norm

        if key_location_norm == 'prompt' and key_format == 'passphrase':
            dialog = PassphraseDialog("Load Key", f"Enter passphrase for:\n'{ds_name}'", self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                passphrase_to_pass = dialog.get_passphrase()
                # If passphrase provided, don't pass key_location=prompt to backend
                key_location_to_pass = None
            else:
                self.status_message.emit("Load key cancelled."); return
        elif key_location_norm != 'prompt' and not key_location_norm.startswith('file:///'):
            QMessageBox.warning(self, "Invalid Key Location", f"Cannot load key: Invalid key location '{key_location_norm}' set on dataset. Must be 'prompt' or 'file:///...'."); return

        self.status_message.emit(f"Requesting key load for {ds_name}...")
        self.load_key_requested.emit(ds_name, recursive, key_location_to_pass, passphrase_to_pass)

    @Slot()
    def _unload_key(self):
        if not self._current_dataset: return

        # *** CHANGE HERE: Check mount status *inside* the slot ***
        if getattr(self._current_dataset, 'is_mounted', False):
             QMessageBox.warning(
                 self, "Dataset Mounted",
                 f"Dataset '{self._current_dataset.name}' must be unmounted before its key can be unloaded.\n\n"
                 "Please unmount it first using the 'Dataset' menu or toolbar."
             )
             self.status_message.emit("Unload key cancelled: Dataset is mounted.")
             return # Stop processing if mounted

        # --- Proceed only if not mounted ---
        ds_name = self._current_dataset.name
        recursive = False
        children = getattr(self._current_dataset, 'children', [])
        # Check if any child is specifically a Dataset object
        has_child_datasets = any(isinstance(child, Dataset) for child in children)

        if has_child_datasets:
            reply_rec = QMessageBox.question(
                self, "Recursive Unload?",
                f"Unload keys recursively for all child datasets under '{ds_name}'?",
                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                 QMessageBox.StandardButton.No
            )
            recursive = (reply_rec == QMessageBox.StandardButton.Yes)

        reply = QMessageBox.question(
            self, "Confirm Unload Key",
            f"Unload encryption key{' recursively' if recursive else ''} for '{ds_name}'?\n"
            "Data will become inaccessible until the key is loaded again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.status_message.emit(f"Requesting key unload for {ds_name}...")
            self.unload_key_requested.emit(ds_name, recursive)

    @Slot()
    def _change_key(self):
        if not self._current_dataset: return
        ds_name = self._current_dataset.name
        properties = getattr(self._current_dataset, 'properties', {})
        key_format = properties.get('keyformat', 'passphrase')

        if properties.get('keystatus', 'unavailable') != 'available':
            QMessageBox.warning(self, "Key Unavailable", "The encryption key must be loaded (available) before it can be changed."); return

        change_info = None; options = {}; load_key_after_change = True; recursive_change = False # Add UI for recursive/load later?

        if key_format == 'passphrase':
            change_dialog = ChangePassphraseDialog(ds_name, self)
            if change_dialog.exec():
                 change_info = change_dialog.get_change_info()
                 if change_info is None:
                     self.status_message.emit("Change passphrase cancelled or input invalid.")
                     return
                 # Ensure keyformat is explicitly set for the change command
                 options['keyformat'] = 'passphrase'
            else:
                self.status_message.emit("Change passphrase cancelled.")
                return
        elif key_format in ['raw', 'hex']:
            start_dir = os.path.expanduser("~")
            new_key_file_path, _ = QFileDialog.getOpenFileName(self, f"Select NEW Key File ({key_format}) for {ds_name}", start_dir, "All Files (*)")
            if not new_key_file_path:
                self.status_message.emit("Change keyfile cancelled.")
                return
            if not os.path.isabs(new_key_file_path):
                QMessageBox.warning(self, "Invalid Path", "Selected key file path must be absolute.")
                return
            new_key_location_uri = f"file://{new_key_file_path}"
            reply = QMessageBox.question(
                self, "Confirm Key Change (File)",
                f"Change encryption key for '{ds_name}' to use the key file:\n{new_key_location_uri}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply != QMessageBox.StandardButton.Yes:
                self.status_message.emit("Change keyfile cancelled.")
                return
            # Set options for backend command
            options['keyformat'] = key_format
            options['keylocation'] = new_key_location_uri
            change_info = None # No passphrase info needed for file change
        else:
            QMessageBox.warning(self, "Unsupported Format", f"Changing keys for key format '{key_format}' is not currently supported via this interface."); return

        # If we got here, proceed with the request
        self.status_message.emit(f"Requesting key change for {ds_name}...")
        self.change_key_requested.emit(ds_name, load_key_after_change, recursive_change, options, change_info)

    @Slot()
    def _change_key_location(self):
        if not self._current_dataset: return
        ds_name = self._current_dataset.name
        properties = getattr(self._current_dataset, 'properties', {})
        current_location = properties.get('keylocation', 'prompt')
        # Normalize current location for display and comparison
        current_location_norm = current_location if current_location and current_location != '-' else 'prompt'

        locations = ['prompt'] # Always offer prompt
        # Add current file location if it exists
        if current_location_norm.startswith('file://'):
            if current_location_norm not in locations: # Avoid duplicates if current IS prompt
                 locations.append(current_location_norm)
        locations.append("<Browse for key file...>") # Option to browse

        try:
            suggested_index = locations.index(current_location_norm)
        except ValueError:
            suggested_index = 0 # Default to prompt if current not found

        new_location_display, ok = QInputDialog.getItem(
            self, "Change Key Location",
            f"Select new key location for:\n'{ds_name}'\n\n(Current: {current_location_norm})",
            locations, suggested_index, False
        )

        if not ok or not new_location_display:
            self.status_message.emit("Key location change cancelled.")
            return

        new_location = new_location_display # This is the final chosen value/URI

        if new_location == "<Browse for key file...>":
            # Determine starting directory for browser
            start_dir = os.path.expanduser("~")
            if current_location_norm.startswith('file://'):
                try: start_dir = os.path.dirname(current_location_norm[7:]) # Get dir from file URI
                except: pass # Ignore errors, fallback to home

            file_path, _ = QFileDialog.getOpenFileName(self, "Select Key File", start_dir, "All Files (*)")
            if file_path:
                if not os.path.isabs(file_path):
                    QMessageBox.warning(self, "Invalid Path", "Selected key file path must be absolute.")
                    return
                new_location = f"file://{file_path}" # Set new location to chosen file
            else:
                self.status_message.emit("Key location change cancelled (browse cancelled).")
                return

        # Check if the location actually changed
        if new_location == current_location_norm:
            self.status_message.emit("Key location not changed.")
            return

        # Validate format (should be 'prompt' or 'file://...')
        if new_location != 'prompt' and not new_location.startswith('file://'):
            QMessageBox.warning(self, "Invalid Format", "Key location must be 'prompt' or a file URI (file:///...)."); return

        # Confirm before emitting
        reply = QMessageBox.question(
            self, "Confirm Change Location",
            f"Change key location property for '{ds_name}' to:\n'{new_location}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.status_message.emit(f"Requesting key location change for {ds_name}...")
            # Emit signal with dataset name and the final chosen location
            self.change_key_location_requested.emit(ds_name, new_location)

# --- END OF FILE widgets/encryption_widget.py ---
