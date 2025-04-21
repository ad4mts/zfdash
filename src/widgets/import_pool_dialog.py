# --- START OF FILE widgets/import_pool_dialog.py ---

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QCheckBox, QLineEdit, QLabel, QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QIcon, QColor

from typing import List, Dict, Optional, Tuple, Any
import re

# Import client class
from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError

class ImportPoolDialog(QDialog):
    """Dialog to select and configure ZFS pool import."""

    def __init__(self, importable_pools: List[Dict[str, str]], zfs_client: ZfsManagerClient, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import ZFS Pools")
        self.setMinimumWidth(600)

        self._pools_data = importable_pools
        # Store the client instance (even if not used directly in this dialog)
        self.zfs_client = zfs_client
        if self.zfs_client is None:
            raise ValueError("ZfsManagerClient instance is required for ImportPoolDialog.")

        layout = QVBoxLayout(self)

        # --- Pool Table ---
        layout.addWidget(QLabel("Found Importable Pools:"))
        self.pools_table = QTableWidget()
        self.pools_table.setColumnCount(3)
        self.pools_table.setHorizontalHeaderLabels(["Name", "ID", "State"])
        self.pools_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.pools_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.pools_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pools_table.verticalHeader().setVisible(False)
        self.pools_table.setAlternatingRowColors(True)
        self.pools_table.itemSelectionChanged.connect(self._update_ui_state)

        header = self.pools_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        self.pools_table.setRowCount(len(self._pools_data))
        for row, pool_info in enumerate(self._pools_data):
            name_item = QTableWidgetItem(pool_info.get("name", "N/A"))
            id_item = QTableWidgetItem(pool_info.get("id", "N/A"))
            state_item = QTableWidgetItem(pool_info.get("state", "N/A"))

            # Store pool name/id in the name item's data role for easy access
            name_item.setData(Qt.ItemDataRole.UserRole, pool_info.get("name", pool_info.get("id")))
            name_item.setToolTip(f"ID: {pool_info.get('id', 'N/A')}\nAction: {pool_info.get('action', '')}\nConfig:\n{pool_info.get('config', '')}")

            if pool_info.get("state") != "ONLINE":
                 state_item.setForeground(QColor(Qt.GlobalColor.red))

            self.pools_table.setItem(row, 0, name_item)
            self.pools_table.setItem(row, 1, id_item)
            self.pools_table.setItem(row, 2, state_item)

        layout.addWidget(self.pools_table)

        # --- Options ---
        options_layout = QHBoxLayout()
        self.new_name_edit = QLineEdit()
        self.new_name_edit.setPlaceholderText("Leave blank to keep original name")
        self.new_name_label = QLabel("Import Selected As:")
        options_layout.addWidget(self.new_name_label)
        options_layout.addWidget(self.new_name_edit)

        self.force_checkbox = QCheckBox("Force Import (-f)")
        self.force_checkbox.setToolTip("Attempt to import even if pool appears active or has other issues.")
        options_layout.addWidget(self.force_checkbox)
        layout.addLayout(options_layout)

        # --- Action Buttons ---
        action_button_layout = QHBoxLayout()
        self.import_selected_button = QPushButton(QIcon.fromTheme("document-open"), "Import Selected")
        self.import_selected_button.clicked.connect(self._accept_selected)

        self.import_all_button = QPushButton(QIcon.fromTheme("folder-open"), "Import All (-a)")
        self.import_all_button.setToolTip("Attempt to import all found pools (use Force cautiously).")
        self.import_all_button.clicked.connect(self._accept_all)

        action_button_layout.addWidget(self.import_selected_button)
        action_button_layout.addWidget(self.import_all_button)
        action_button_layout.addStretch()
        layout.addLayout(action_button_layout)

        # --- Standard Dialog Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # Result Storage
        self._result_action: Optional[str] = None # 'selected', 'all'
        self._result_pool_id: Optional[str] = None
        self._result_new_name: Optional[str] = None
        self._result_force: bool = False

        self._update_ui_state() # Initial state

    @Slot()
    def _update_ui_state(self):
        """Enable/disable controls based on selection."""
        has_selection = len(self.pools_table.selectedItems()) > 0
        self.import_selected_button.setEnabled(has_selection)
        self.new_name_label.setEnabled(has_selection)
        self.new_name_edit.setEnabled(has_selection)
        # Force checkbox is always available for both selected and all
        # self.force_checkbox.setEnabled(has_selection or len(self._pools_data) > 0)
        # Import All is always enabled if there are pools
        self.import_all_button.setEnabled(len(self._pools_data) > 0)

    def _get_selected_pool_identifier(self) -> Optional[str]:
        """Gets the name or ID stored in the selected row's UserRole."""
        selected_indexes = self.pools_table.selectedIndexes()
        if not selected_indexes:
            return None
        # Get item from first column of selected row
        name_item = self.pools_table.item(selected_indexes[0].row(), 0)
        if name_item:
            return name_item.data(Qt.ItemDataRole.UserRole)
        return None

    @Slot()
    def _accept_selected(self):
        """Handle 'Import Selected' button click."""
        pool_id = self._get_selected_pool_identifier()
        if not pool_id:
            QMessageBox.warning(self, "Selection Required", "Please select a pool from the list.")
            return

        new_name = self.new_name_edit.text().strip()
        if new_name:
             # Simple validation for pool name characters
             if not re.match(r'^[a-zA-Z][a-zA-Z0-9_\-:.%]*$', new_name):
                  QMessageBox.warning(self, "Invalid Name", "New pool name must start with a letter and contain only letters, numbers, or: _ - : . %")
                  return
             # Could add check if new_name already exists on system? Complex.

        self._result_action = 'selected'
        self._result_pool_id = pool_id
        self._result_new_name = new_name if new_name else None
        self._result_force = self.force_checkbox.isChecked()
        self.accept()

    @Slot()
    def _accept_all(self):
        """Handle 'Import All' button click."""
        reply = QMessageBox.question(self, "Confirm Import All",
                                     "Are you sure you want to attempt to import ALL listed pools?\n"
                                     "Use the 'Force' option with caution.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._result_action = 'all'
            self._result_pool_id = None # Not applicable for 'all'
            self._result_new_name = None # Not applicable for 'all'
            self._result_force = self.force_checkbox.isChecked()
            self.accept()

    def get_import_details(self) -> Optional[Dict[str, Any]]:
        """Returns the details for the import operation."""
        if not self._result_action:
            return None

        return {
            "action": self._result_action,
            "pool_id": self._result_pool_id,
            "new_name": self._result_new_name,
            "force": self._result_force,
        }

# Example Usage
if __name__ == '__main__':
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # Sample data matching list_importable_pools output
    mock_pools = [
        {'name': 'oldpool', 'id': '1234567890123456', 'state': 'ONLINE', 'action': 'Import pool.', 'config': '...'},
        {'name': 'usbpool', 'id': '9876543210987654', 'state': 'FAULTED', 'action': 'Import pool.', 'config': '...'},
        {'name': 'another', 'id': '5555555555555555', 'state': 'EXPORTED', 'action': 'Import pool.', 'config': '...'},
    ]

    # Define a mock client class for example usage
    class MockZFSManagerClient:
        def list_importable_pools(self, search_dirs=None): return True, "Mock Search", mock_pools
        def __getattr__(self, name): return lambda *a, **k: (_ for _ in ()).throw(RuntimeError(f"MockZFSManagerClient.{name} called"))

    mock_zfs_client = MockZFSManagerClient()
    dialog = ImportPoolDialog(mock_pools, mock_zfs_client)
    if dialog.exec():
        details = dialog.get_import_details()
        print("Import Details:")
        import json
        print(json.dumps(details, indent=2))
    else:
        print("Import Cancelled.")

    sys.exit()
# --- END OF FILE widgets/import_pool_dialog.py ---
