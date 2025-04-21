# --- START OF FILE create_dataset_dialog.py ---

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QDialogButtonBox, QMessageBox, QCheckBox, QLabel, QGroupBox,
    QWidget, QHBoxLayout, QPushButton, QFileDialog
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QIcon

from typing import Optional, Dict, Any, Tuple
import re
import os

# Import client class
from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError
import utils # Import the whole module

class CreateDatasetDialog(QDialog):
    """Dialog for creating a new ZFS dataset or volume."""

    def __init__(self, parent_dataset_name, zfs_client: ZfsManagerClient, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Dataset/Volume")
        self._parent_dataset_name = parent_dataset_name
        # Store the client instance
        self.zfs_client = zfs_client
        if self.zfs_client is None:
            raise ValueError("ZfsManagerClient instance is required for CreateDatasetDialog.")

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g., mydata, images, backup")
        form_layout.addRow(f"Name (under '{parent_dataset_name}/'):", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Dataset (Filesystem)", "Volume (Block Device)"])
        self.type_combo.currentTextChanged.connect(self._update_options_visibility)
        form_layout.addRow("Type:", self.type_combo)

        self.vol_size_label = QLabel("Volume Size:")
        self.vol_size_edit = QLineEdit()
        self.vol_size_edit.setPlaceholderText("e.g., 10G, 500M (Required for volumes)")
        form_layout.addRow(self.vol_size_label, self.vol_size_edit)

        layout.addLayout(form_layout)

        # Optional Properties Group Box
        self.options_group = QGroupBox("Optional Properties")
        self.options_group.setCheckable(True)
        self.options_group.setChecked(False)
        options_layout = QFormLayout(self.options_group)

        self.mountpoint_edit = QLineEdit()
        self.mountpoint_edit.setPlaceholderText("Default: inherit or /<pool>/<path>")
        options_layout.addRow("Mount Point (-o mountpoint=):", self.mountpoint_edit)

        self.quota_edit = QLineEdit()
        self.quota_edit.setPlaceholderText("e.g., 100G, none")
        options_layout.addRow("Quota (-o quota=):", self.quota_edit)

        self.reservation_edit = QLineEdit()
        self.reservation_edit.setPlaceholderText("e.g., 5G, none")
        options_layout.addRow("Reservation (-o reservation=):", self.reservation_edit)

        self.compression_combo = QComboBox()
        self.compression_combo.addItems(['inherit', 'off', 'on', 'lz4', 'gzip', 'gzip-1', 'gzip-9', 'zle', 'lzjb', 'zstd', 'zstd-fast'])
        options_layout.addRow("Compression (-o compression=):", self.compression_combo)

        self.recordsize_combo = QComboBox()
        self.recordsize_combo.addItems(['inherit', '512'] + [f'{2**i}K' for i in range(7, 11)] + ['1M'])
        options_layout.addRow("Record Size (-o recordsize=):", self.recordsize_combo)

        layout.addWidget(self.options_group)

        # --- Encryption Options ---
        self.enc_group = QGroupBox("Encryption Options")
        self.enc_group.setCheckable(True)
        self.enc_group.setChecked(False)
        self.enc_group.toggled.connect(self._update_enc_options_state)
        enc_layout = QFormLayout(self.enc_group)

        self.enc_algorithm_combo = QComboBox()
        self.enc_algorithm_combo.addItems([
            'inherit', 'off', 'on', # 'on' usually defaults to aes-256-gcm
            'aes-128-ccm', 'aes-192-ccm', 'aes-256-ccm',
            'aes-128-gcm', 'aes-192-gcm', 'aes-256-gcm'
        ])
        self.enc_algorithm_combo.setToolTip("Select encryption algorithm ('on' defaults to aes-256-gcm). 'inherit' uses parent's setting. 'off' disables.")
        # Trigger update when algorithm changes (e.g. to 'off')
        self.enc_algorithm_combo.currentTextChanged.connect(lambda: self._update_enc_options_state(self.enc_group.isChecked()))
        enc_layout.addRow("Algorithm (-o encryption=):", self.enc_algorithm_combo)

        self.enc_key_format_combo = QComboBox()
        # Removed 'inherit' as format is usually explicit when encryption is 'on'
        self.enc_key_format_combo.addItems(['passphrase', 'raw', 'hex'])
        self.enc_key_format_combo.setToolTip("Key format: passphrase (enter below), raw/hex (specify key file location).")
        self.enc_key_format_combo.currentTextChanged.connect(lambda: self._update_enc_options_state(self.enc_group.isChecked()))
        enc_layout.addRow("Key Format (-o keyformat=):", self.enc_key_format_combo)

        # Key Location Row (Label + Combo + Button)
        self.enc_key_location_label = QLabel("Key File Location (-o keylocation=):") # Label added
        self.enc_key_location_combo = QComboBox()
        # 'prompt' is only valid for passphrase, handled implicitly by GUI now
        # self.enc_key_location_combo.addItems(['prompt']) # Remove prompt
        self.enc_key_location_combo.addItem("") # Add an empty initial item
        self.enc_key_location_combo.setEditable(True) # Allow pasting URIs
        self.enc_key_location_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert) # Don't add typed items permanently
        self.enc_key_location_browse_button = QPushButton(QIcon.fromTheme("document-open"), "")
        self.enc_key_location_browse_button.setToolTip("Browse for existing key file (required for raw/hex format)")
        self.enc_key_location_browse_button.clicked.connect(self._browse_for_keyfile)

        key_location_widget = QWidget()
        key_location_layout = QHBoxLayout(key_location_widget)
        key_location_layout.setContentsMargins(0,0,0,0)
        key_location_layout.addWidget(self.enc_key_location_combo, 1)
        key_location_layout.addWidget(self.enc_key_location_browse_button, 0)
        # Add row using the label
        enc_layout.addRow(self.enc_key_location_label, key_location_widget)

        # Passphrase Fields (Initially Hidden/Disabled)
        self.passphrase_label = QLabel("Passphrase:")
        self.passphrase_edit = QLineEdit()
        self.passphrase_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.passphrase_confirm_label = QLabel("Confirm Passphrase:")
        self.passphrase_confirm_edit = QLineEdit()
        self.passphrase_confirm_edit.setEchoMode(QLineEdit.EchoMode.Password)
        enc_layout.addRow(self.passphrase_label, self.passphrase_edit)
        enc_layout.addRow(self.passphrase_confirm_label, self.passphrase_confirm_edit)

        # PBKDF2 Iterations (Passphrase only)
        self.enc_pbkdf2iters_label = QLabel("PBKDF2 Iterations (-o pbkdf2iters=):")
        self.enc_pbkdf2iters_edit = QLineEdit()
        self.enc_pbkdf2iters_edit.setPlaceholderText("Default (e.g., 350000)")
        self.enc_pbkdf2iters_edit.setToolTip("Number of PBKDF2 iterations for passphrase keys (higher is more secure but slower). Leave blank for default.")
        enc_layout.addRow(self.enc_pbkdf2iters_label, self.enc_pbkdf2iters_edit)

        layout.addWidget(self.enc_group)
        # ----------------------------

        # Standard Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.setLayout(layout)
        self._update_options_visibility(self.type_combo.currentText())
        self._update_enc_options_state(self.enc_group.isChecked()) # Initial encryption state

    @Slot(str)
    def _update_options_visibility(self, selected_type):
        is_volume = "Volume" in selected_type
        self.vol_size_label.setVisible(is_volume)
        self.vol_size_edit.setVisible(is_volume)

    @Slot(bool)
    def _update_enc_options_state(self, checked):
        """Enable/disable encryption fields based on checkbox and format."""
        encryption_on = checked and self.enc_algorithm_combo.currentText() not in ['off', 'inherit']

        # Enable basic controls if encryption group is checked and algorithm is not 'off'/'inherit'
        self.enc_algorithm_combo.setEnabled(checked)
        self.enc_key_format_combo.setEnabled(checked and encryption_on)

        # Determine state based on key format
        key_format = self.enc_key_format_combo.currentText()
        is_passphrase = (key_format == 'passphrase' and encryption_on)
        is_file_based = (key_format in ['raw', 'hex'] and encryption_on)

        # Key Location is for file-based keys
        self.enc_key_location_label.setVisible(is_file_based)
        self.enc_key_location_combo.setVisible(is_file_based)
        self.enc_key_location_browse_button.setVisible(is_file_based)
        self.enc_key_location_label.setEnabled(is_file_based)
        self.enc_key_location_combo.setEnabled(is_file_based)
        self.enc_key_location_browse_button.setEnabled(is_file_based)

        # Passphrase fields are for passphrase format
        self.passphrase_label.setVisible(is_passphrase)
        self.passphrase_edit.setVisible(is_passphrase)
        self.passphrase_confirm_label.setVisible(is_passphrase)
        self.passphrase_confirm_edit.setVisible(is_passphrase)
        self.passphrase_label.setEnabled(is_passphrase)
        self.passphrase_edit.setEnabled(is_passphrase)
        self.passphrase_confirm_label.setEnabled(is_passphrase)
        self.passphrase_confirm_edit.setEnabled(is_passphrase)

        # PBKDF2 iterations are for passphrase format
        self.enc_pbkdf2iters_label.setVisible(is_passphrase)
        self.enc_pbkdf2iters_edit.setVisible(is_passphrase)
        self.enc_pbkdf2iters_label.setEnabled(is_passphrase)
        self.enc_pbkdf2iters_edit.setEnabled(is_passphrase)

        # If encryption group is off, disable everything inside
        if not checked:
            self.enc_key_format_combo.setEnabled(False)
            self.enc_key_location_label.setEnabled(False)
            self.enc_key_location_combo.setEnabled(False)
            self.enc_key_location_browse_button.setEnabled(False)
            self.passphrase_label.setEnabled(False)
            self.passphrase_edit.setEnabled(False)
            self.passphrase_confirm_label.setEnabled(False)
            self.passphrase_confirm_edit.setEnabled(False)
            self.enc_pbkdf2iters_label.setEnabled(False)
            self.enc_pbkdf2iters_edit.setEnabled(False)


    @Slot()
    def _browse_for_keyfile(self):
        """Opens a file dialog to select a key file and updates the location combo."""
        start_dir = os.path.expanduser("~")
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Key File", start_dir, "All Files (*)")

        if file_path:
            if not os.path.isabs(file_path):
                 QMessageBox.warning(self, "Invalid Path", "Selected key file path must be absolute.")
                 return
            file_uri = f"file://{file_path}"
            # Check if URI is already in combo, add if not
            if self.enc_key_location_combo.findText(file_uri) == -1:
                 self.enc_key_location_combo.addItem(file_uri)
            # Set the combo box to the selected file URI
            self.enc_key_location_combo.setCurrentText(file_uri)

    def get_dataset_details(self) -> Optional[Tuple[str, str, Dict[str, Any], Dict[str, Any]]]:
        """Validates input and returns details for dataset creation.

        Returns:
            Tuple[str, str, Dict[str, Any], Dict[str, Any]] or None:
                (full_name, type_str, properties_dict, encryption_options_dict) on success, None on validation failure.
        """
        name_part = self.name_edit.text().strip()
        if not name_part or '/' in name_part or '@' in name_part or ' ' in name_part or not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_\-:.%]*$', name_part):
            QMessageBox.warning(self, "Invalid Name", "Dataset/Volume name part cannot be empty, contain '/', '@', or spaces, and must start with alphanumeric.")
            return None

        full_name = f"{self._parent_dataset_name}/{name_part}"
        is_volume = "Volume" in self.type_combo.currentText()
        type_str = "volume" if is_volume else "filesystem" # Use lowercase type string

        properties = {}
        encryption_options = {}

        # --- Volume Specific Validation ---
        if is_volume:
            vol_size = self.vol_size_edit.text().strip()
            if not vol_size or vol_size.lower() == 'none':
                 QMessageBox.warning(self, "Missing Volume Size", "Volume Size is required for volumes and cannot be 'none'.")
                 return None
            try:
                 _ = utils.parse_size(vol_size) # Validate format
                 properties['volsize'] = vol_size
            except ValueError:
                 QMessageBox.warning(self, "Invalid Volume Size", f"Volume Size '{vol_size}' is not a valid size format (e.g., 10G, 500M).")
                 return None

        # --- Optional Properties ---
        if self.options_group.isChecked():
            mountpoint = self.mountpoint_edit.text().strip()
            quota = self.quota_edit.text().strip()
            reservation = self.reservation_edit.text().strip()
            compression = self.compression_combo.currentText()
            recordsize = self.recordsize_combo.currentText()

            if mountpoint: properties['mountpoint'] = mountpoint
            if quota: properties['quota'] = quota
            if reservation: properties['reservation'] = reservation
            if compression != 'inherit': properties['compression'] = compression
            if recordsize != 'inherit': properties['recordsize'] = recordsize

        # --- Encryption Options ---
        if self.enc_group.isChecked():
            algorithm = self.enc_algorithm_combo.currentText()
            if algorithm == 'inherit':
                 # If inheriting, don't send other encryption props
                 properties['encryption'] = 'inherit'
            elif algorithm == 'off':
                 properties['encryption'] = 'off'
            elif algorithm == 'on' or algorithm.startswith('aes-'):
                 properties['encryption'] = algorithm
                 key_format = self.enc_key_format_combo.currentText()
                 properties['keyformat'] = key_format

                 if key_format == 'passphrase':
                      passphrase = self.passphrase_edit.text()
                      confirm_passphrase = self.passphrase_confirm_edit.text()
                      if not passphrase:
                           QMessageBox.warning(self, "Missing Passphrase", "Passphrase is required when key format is 'passphrase'.")
                           return None
                      if passphrase != confirm_passphrase:
                           QMessageBox.warning(self, "Passphrase Mismatch", "Passphrases do not match.")
                           return None
                      # Passphrase is not sent directly, ZFS prompts
                      encryption_options['passphrase_required'] = True

                      pbkdf2iters = self.enc_pbkdf2iters_edit.text().strip()
                      if pbkdf2iters:
                           try:
                                int_iters = int(pbkdf2iters)
                                if int_iters < 100000: # ZFS minimum
                                     raise ValueError("Too low")
                                properties['pbkdf2iters'] = str(int_iters)
                           except ValueError:
                                QMessageBox.warning(self, "Invalid Iterations", f"PBKDF2 iterations ('{pbkdf2iters}') must be a number >= 100000.")
                                return None
                      # If blank, ZFS uses default, don't set property

                 elif key_format in ['raw', 'hex']:
                      key_location = self.enc_key_location_combo.currentText().strip()
                      if not key_location or not key_location.startswith('file:///'):
                           QMessageBox.warning(self, "Invalid Key Location", f"Key Location must be a valid absolute 'file:///path/to/key' URI for format '{key_format}'.")
                           return None
                      # Basic check if file seems accessible (read perms)
                      try:
                          key_path = key_location.replace('file://', '')
                          if not os.path.isfile(key_path) or not os.access(key_path, os.R_OK):
                               raise FileNotFoundError("Key file not found or not readable")
                      except Exception as e:
                           QMessageBox.warning(self, "Key File Error", f"Cannot access key file at '{key_location}'.\nError: {e}")
                           return None
                      properties['keylocation'] = key_location
            # else: Should not happen with combo box

        return full_name, type_str, properties, encryption_options

    @Slot()
    def accept(self):
        # Validation happens within get_dataset_details now
        if self.get_dataset_details() is not None:
             super().accept()

# Example Usage Block (remains the same)
if __name__ == '__main__':
    import sys
    from PySide6.QtWidgets import QApplication # Ensure import
    app = QApplication(sys.argv)
    parent_ds = "tank/data"
    dialog = CreateDatasetDialog(parent_ds)
    if dialog.exec():
        ds_config = dialog.get_dataset_details()
        if ds_config:
            print("Dataset Configuration Accepted:")
            import json
            # Censor passphrase before printing
            if ds_config[3].get('passphrase'): ds_config[3]['passphrase'] = '********'
            print(json.dumps(ds_config, indent=2))
        else:
             print("Dialog accepted but failed to get data.")
    else:
        print("Dataset Creation Cancelled.")
    sys.exit()

# --- END OF FILE create_dataset_dialog.py ---
