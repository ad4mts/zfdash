# --- START OF FILE widgets/create_pool_dialog.py ---

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QListWidget, QAbstractItemView, QPushButton, QDialogButtonBox, QMessageBox,
    QLabel, QGroupBox, QSplitter, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, # <-- Added QTreeWidgetItemIterator
    QListWidgetItem, QWidget, QHeaderView, QInputDialog, QCheckBox # <-- Added QCheckBox
)
from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtGui import QIcon, QColor # Import QColor for error item

from typing import Optional, Dict, List, Any, Tuple
import re
import uuid # For unique IDs for tree items

# Use ..widgets for relative imports if structure allows, otherwise adjust path
try:
    # Assuming models, utils, zfs_manager are accessible in the Python path
    from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError
    import utils
except ImportError:
    # Fallback for potential path issues or running standalone
    print("Warning: Failed to import zfs_manager/utils. Functionality might be limited.")
    # Define mocks or stubs if needed for standalone testing
    class MockZFSManager:
        def list_block_devices(self): return []
    class MockUtils:
        def format_size(self, size): return str(size)
        def parse_size(self, size_str): return int(size_str) if size_str.isdigit() else 0
    zfs_manager = MockZFSManager()
    utils = MockUtils()


# Constants for tree widget data roles
VDEV_TYPE_ROLE = Qt.UserRole + 1
VDEV_DEVICES_ROLE = Qt.UserRole + 2
DEVICE_PATH_ROLE = Qt.UserRole + 3

class CreatePoolDialog(QDialog):
    """Dialog for creating a new ZFS pool with multiple vdev support."""

    def __init__(self, zfs_client: ZfsManagerClient, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New ZFS Pool")
        self.setMinimumSize(700, 600) # Increased size slightly for force checkbox
        # Store the client instance
        self.zfs_client = zfs_client
        if self.zfs_client is None:
            raise ValueError("ZfsManagerClient instance is required for CreatePoolDialog.")
        if self.zfs_client is None:
            raise ValueError("ZfsManagerClient instance is required for CreatePoolDialog.")
        self._available_devices_map: Dict[str, Dict[str, Any]] = {} # Store full device info
        self._safe_devices = []
        self._all_devices = []

        layout = QVBoxLayout(self)

        # Pool Name & Force Option
        top_layout = QHBoxLayout()
        form_layout = QFormLayout()
        self.pool_name_edit = QLineEdit()
        self.pool_name_edit.setPlaceholderText("e.g., mypool, tank")
        form_layout.addRow("Pool Name:", self.pool_name_edit)
        top_layout.addLayout(form_layout, 1) # Give form layout more space

        self.force_checkbox = QCheckBox("Force (-f)")
        self.force_checkbox.setToolTip("Allow using devices of different sizes (dangerous) or potentially override other checks.")
        top_widget = QWidget() # Use a widget to align checkbox better
        top_widget_layout = QVBoxLayout(top_widget)
        top_widget_layout.addStretch() # Push checkbox down
        top_widget_layout.addWidget(self.force_checkbox)
        top_widget_layout.setContentsMargins(0,0,0,0)
        top_layout.addWidget(top_widget, 0) # Give checkbox less space

        layout.addLayout(top_layout)

        # Main Splitter (Available Devices | Configured VDEVs)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1) # Give splitter stretch factor

        # --- Left Pane: Available Devices ---
        left_pane_widget = QWidget() # Now defined
        left_layout = QVBoxLayout(left_pane_widget)
        left_layout.addWidget(QLabel("Available Block Devices:"))
        
        # Add Show All Checkbox
        self.show_all_checkbox = QCheckBox("Show All Devices")
        self.show_all_checkbox.setToolTip("Show all detected block devices (including partitions and potentially unsafe ones).")
        self.show_all_checkbox.toggled.connect(self._update_device_list_ui)
        left_layout.addWidget(self.show_all_checkbox)

        self.available_devices_list = QListWidget()
        self.available_devices_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.available_devices_list.setSortingEnabled(True)
        left_layout.addWidget(self.available_devices_list)
        splitter.addWidget(left_pane_widget)

        # --- Right Pane: Pool Configuration ---
        right_pane_widget = QWidget() # Now defined
        right_layout = QVBoxLayout(right_pane_widget)
        right_layout.addWidget(QLabel("Pool Layout (VDEVs and Devices):"))

        # Configured VDEVs Tree
        self.vdev_tree = QTreeWidget()
        self.vdev_tree.setColumnCount(2)
        self.vdev_tree.setHeaderLabels(["VDEV / Device", "Size / Type"])
        self.vdev_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.vdev_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu) # For right-click later if needed
        header = self.vdev_tree.header() # Now defined
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        right_layout.addWidget(self.vdev_tree)

        # Buttons to manage VDEVs and Devices
        button_layout = QHBoxLayout()
        self.add_vdev_button = QPushButton(QIcon.fromTheme("list-add"), "Add VDEV")
        self.add_vdev_button.setToolTip("Add a new VDEV group (mirror, raidz, log, cache, spare, disk)")
        self.add_vdev_button.clicked.connect(self._add_vdev_dialog)

        self.remove_vdev_button = QPushButton(QIcon.fromTheme("list-remove"), "Remove VDEV/Device")
        self.remove_vdev_button.setToolTip("Remove selected VDEV or device from the layout")
        self.remove_vdev_button.clicked.connect(self._remove_selected_tree_item)

        self.add_device_button = QPushButton(QIcon.fromTheme("go-next"), "Add Device ->")
        self.add_device_button.setToolTip("Add selected available device(s) to the selected VDEV")
        self.add_device_button.clicked.connect(self._add_device_to_vdev)

        button_layout.addWidget(self.add_vdev_button)
        button_layout.addWidget(self.remove_vdev_button)
        button_layout.addStretch()
        button_layout.addWidget(self.add_device_button)
        right_layout.addLayout(button_layout)

        splitter.addWidget(right_pane_widget)
        splitter.setSizes([250, 450]) # Adjust initial sizes

        # Standard Dialog Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.setLayout(layout)
        self._populate_available_devices() # Populate the list

    def _populate_available_devices(self):
        """Fetches block devices and updates the UI."""
        self._available_devices_map.clear()
        try:
            # Fetch devices
            result = self.zfs_client.list_block_devices()
            
            # Handle error
            if result.get('error'):
                self.available_devices_list.clear() # Clear specific list
                error_item = QListWidgetItem(f"Error: {result['error']}")
                error_item.setForeground(QColor(Qt.GlobalColor.red))
                error_item.setFlags(error_item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
                self.available_devices_list.addItem(error_item)
                return

            # Store lists
            self._safe_devices = result.get('devices', [])
            self._all_devices = result.get('all_devices', [])
            
            # Map ALL devices for lookup (so keys exist even if toggled)
            for dev in self._all_devices:
                self._available_devices_map[dev['name']] = dev

            # Trigger UI update
            self._update_device_list_ui()

        except (ZfsCommandError, ZfsClientCommunicationError, TimeoutError) as e:
             self.available_devices_list.clear()
             print(f"Error populating devices: {e}")
             error_item = QListWidgetItem(f"Error listing devices: {e}")
             error_item.setForeground(QColor(Qt.GlobalColor.red))
             error_item.setFlags(error_item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
             self.available_devices_list.addItem(error_item)
        except Exception as e:
             import traceback
             print(f"Unexpected error populating devices: {e}\n{traceback.format_exc()}")
             self.available_devices_list.clear()
             error_item = QListWidgetItem("Unexpected error listing devices!")
             error_item.setForeground(QColor(Qt.GlobalColor.red))
             error_item.setFlags(error_item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
             self.available_devices_list.addItem(error_item)

    def _update_device_list_ui(self):
        """Updates the available devices list based on the checkbox filter."""
        self.available_devices_list.clear()
        
        # Select source list
        devices = self._all_devices if self.show_all_checkbox.isChecked() else self._safe_devices
        
        # Filter out devices that are already used in the VDEV config
        # (This keeps the list clean if user removed a device from a VDEV) > no duplicates

        
        current_used_paths = set()
        iterator = QTreeWidgetItemIterator(self.vdev_tree)
        while iterator.value():
            item = iterator.value()
            path = item.data(0, DEVICE_PATH_ROLE) # Ensure DEVICE_PATH_ROLE is imported/avail
            if path:
                current_used_paths.add(path)
            iterator += 1
            
        if not devices:
             placeholder_item = QListWidgetItem("No suitable devices found.")
             placeholder_item.setFlags(placeholder_item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
             placeholder_item.setForeground(QColor(Qt.GlobalColor.gray))
             self.available_devices_list.addItem(placeholder_item)
             return

        for dev in devices:
             if dev['name'] in current_used_paths:
                 continue

             item_text = dev.get('display_name', f"{dev['name']}")
             item = QListWidgetItem(item_text)
             item.setData(Qt.ItemDataRole.UserRole, dev['name'])
             self.available_devices_list.addItem(item)

    def _get_min_devices_for_type(self, vdev_type: str) -> int:
        """Returns minimum number of devices for a given vdev type."""
        vdev_type = vdev_type.lower()
        if vdev_type == 'mirror': return 2
        elif vdev_type == 'raidz1': return 3 # Technically 2 data + 1 parity
        elif vdev_type == 'raidz2': return 4 # Technically 2 data + 2 parity
        elif vdev_type == 'raidz3': return 5 # Technically 3 data + 3 parity
        else: return 1 # disk, log, cache, spare

    @Slot()
    def _add_vdev_dialog(self):
        """Shows a dialog or modifies UI to add a VDEV configuration."""
        # Simple approach: Ask for VDEV type first
        vdev_types = ['disk', 'mirror', 'raidz1', 'raidz2', 'raidz3', 'log', 'cache', 'spare']
        # Ensure QInputDialog is imported
        try:
            from PySide6.QtWidgets import QInputDialog
        except ImportError:
            print("Error: QInputDialog not found.")
            return

        vdev_type, ok = QInputDialog.getItem(self, "Add VDEV", "Select VDEV Type:", vdev_types, 0, False)

        if ok and vdev_type:
            vdev_item = QTreeWidgetItem(self.vdev_tree)
            vdev_item.setText(0, f"VDEV ({vdev_type})")
            vdev_item.setText(1, vdev_type.upper())
            vdev_item.setData(0, VDEV_TYPE_ROLE, vdev_type)
            vdev_item.setData(0, VDEV_DEVICES_ROLE, []) # Store device paths here
            vdev_item.setFlags(vdev_item.flags() | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            # Choose icon based on type
            icon = QIcon.fromTheme("drive-harddisk") # Default
            if vdev_type in ['mirror', 'raidz1', 'raidz2', 'raidz3']:
                icon = QIcon.fromTheme("drive-multidisk")
            elif vdev_type in ['log', 'cache', 'spare']:
                icon = QIcon.fromTheme("drive-removable-media")
            vdev_item.setIcon(0, icon)


    @Slot()
    def _add_device_to_vdev(self):
        """Adds selected available device(s) to the selected VDEV in the tree."""
        selected_vdev_items = self.vdev_tree.selectedItems()
        selected_available_items = self.available_devices_list.selectedItems()

        if not selected_vdev_items:
            QMessageBox.warning(self, "Selection Required", "Please select a VDEV in the Pool Layout tree first.")
            return
        if not selected_available_items:
            QMessageBox.warning(self, "Selection Required", "Please select one or more devices from the Available Devices list.")
            return

        # Find the top-level VDEV item (in case a device under it was selected)
        target_vdev_item = selected_vdev_items[0]
        while target_vdev_item.parent():
            target_vdev_item = target_vdev_item.parent()

        # Check if it's actually a VDEV item
        vdev_type = target_vdev_item.data(0, VDEV_TYPE_ROLE)
        if not vdev_type:
            QMessageBox.warning(self, "Invalid Selection", "Please select the VDEV group item (e.g., VDEV (mirror)) in the tree, not a device within it.")
            return

        current_devices = target_vdev_item.data(0, VDEV_DEVICES_ROLE) or []

        items_to_move = []
        for item in selected_available_items:
            # Ensure the item is selectable and enabled (not the placeholder)
            if not (item.flags() & Qt.ItemIsEnabled):
                 continue
            device_path = item.data(Qt.ItemDataRole.UserRole)
            if device_path and device_path not in current_devices:
                 items_to_move.append(item)
                 current_devices.append(device_path)

        if not items_to_move:
             QMessageBox.information(self, "No Change", "Selected device(s) are already in the target VDEV or invalid.")
             return

        # Update VDEV data and add child items to tree
        target_vdev_item.setData(0, VDEV_DEVICES_ROLE, current_devices)
        for list_item in items_to_move:
             device_path = list_item.data(Qt.ItemDataRole.UserRole)
             device_info = self._available_devices_map.get(device_path, {})
             # Fix for size display: Use size_bytes if available, formatted correctly
             size_bytes = device_info.get('size_bytes', 0)
             # fallback to size_str if bytes not present, but parse_size expects string
             size_str = utils.format_size(utils.parse_size(str(size_bytes))) if size_bytes else utils.format_size(utils.parse_size(device_info.get('size_str', '0')))
             
             label = device_info.get('label', '')
             if not label or label == 'None': label = ''

             tree_child = QTreeWidgetItem(target_vdev_item)
             tree_child.setText(0, f"  {device_path} {label}".strip())
             tree_child.setText(1, size_str)
             tree_child.setData(0, DEVICE_PATH_ROLE, device_path)
             tree_child.setIcon(0, QIcon.fromTheme("media-floppy")) # Icon for disk device

             # Remove from available list
             self.available_devices_list.takeItem(self.available_devices_list.row(list_item))

        self.vdev_tree.expandItem(target_vdev_item)

    @Slot()
    def _remove_selected_tree_item(self):
        """Removes a selected VDEV or a device from a VDEV in the tree."""
        selected_items = self.vdev_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Selection Required", "Please select an item in the Pool Layout tree to remove.")
            return

        item_to_remove = selected_items[0]

        # Check if it's a top-level VDEV item
        if item_to_remove.parent() is None:
            # It's a VDEV, remove it and all its children (devices)
            reply = QMessageBox.question(self, "Confirm Removal",
                                         f"Remove the entire VDEV '{item_to_remove.text(0)}' and return its devices to the available list?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                # Return devices to available list
                for i in range(item_to_remove.childCount()):
                    child_item = item_to_remove.child(i)
                    device_path = child_item.data(0, DEVICE_PATH_ROLE)
                    if device_path:
                         self._return_device_to_available(device_path)
                # Remove VDEV item from tree
                (self.vdev_tree.invisibleRootItem()).removeChild(item_to_remove)
        else:
            # It's a device within a VDEV
            device_path = item_to_remove.data(0, DEVICE_PATH_ROLE)
            parent_vdev_item = item_to_remove.parent()
            if device_path and parent_vdev_item:
                reply = QMessageBox.question(self, "Confirm Removal",
                                             f"Remove device '{device_path}' from VDEV '{parent_vdev_item.text(0)}'?",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
                if reply == QMessageBox.StandardButton.Yes:
                    # Remove from parent's device list
                    current_devices = parent_vdev_item.data(0, VDEV_DEVICES_ROLE) or []
                    if device_path in current_devices:
                        current_devices.remove(device_path)
                        parent_vdev_item.setData(0, VDEV_DEVICES_ROLE, current_devices)
                    # Remove item from tree
                    parent_vdev_item.removeChild(item_to_remove)
                    # Return device to available list
                    self._return_device_to_available(device_path)

    def _return_device_to_available(self, device_path: str):
        """Adds a device back to the available list widget."""
        if device_path in self._available_devices_map:
             dev = self._available_devices_map[device_path]
             item_text = dev.get('display_name', f"{dev['name']}")
             item = QListWidgetItem(item_text)
             item.setData(Qt.ItemDataRole.UserRole, dev['name']) # Store path
             item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable) # Ensure it's enabled
             self.available_devices_list.addItem(item)
        else:
             # Fallback if info is missing (shouldn't happen often)
             item = QListWidgetItem(device_path)
             item.setData(Qt.ItemDataRole.UserRole, device_path)
             item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable) # Ensure it's enabled
             self.available_devices_list.addItem(item)
        self.available_devices_list.sortItems() # Keep list sorted

    def get_pool_details(self) -> Optional[Tuple[str, List[Dict[str, Any]], bool]]: # Changed return type
        """Gets the configured pool name, vdev structure, and force flag."""
        pool_name = self.pool_name_edit.text().strip()
        vdev_specs = []
        for i in range(self.vdev_tree.topLevelItemCount()):
            vdev_item = self.vdev_tree.topLevelItem(i)
            vdev_type = vdev_item.data(0, VDEV_TYPE_ROLE)
            devices = vdev_item.data(0, VDEV_DEVICES_ROLE) or []
            if not vdev_type or not devices:
                 continue
            vdev_specs.append({'type': vdev_type, 'devices': devices})

        force = self.force_checkbox.isChecked()

        if not pool_name or not vdev_specs:
            return None

        return pool_name, vdev_specs, force

    @Slot()
    def accept(self):
        """Validate before accepting."""
        pool_name = self.pool_name_edit.text().strip()
        if not pool_name or not re.match(r'^[a-zA-Z][a-zA-Z0-9_\-.]*$', pool_name):
            QMessageBox.warning(self, "Invalid Pool Name", "Pool name must start with a letter and contain only letters, numbers, underscores (_), hyphens (-), and periods (.).")
            return

        has_vdevs = False
        for i in range(self.vdev_tree.topLevelItemCount()):
            vdev_item = self.vdev_tree.topLevelItem(i)
            if vdev_item.data(0, VDEV_DEVICES_ROLE):
                 # Check device count vs minimum for vdev type
                 vdev_type = vdev_item.data(0, VDEV_TYPE_ROLE)
                 min_devs = self._get_min_devices_for_type(vdev_type)
                 num_devs = len(vdev_item.data(0, VDEV_DEVICES_ROLE))
                 if num_devs < min_devs:
                      QMessageBox.warning(self, "Invalid VDEV", f"VDEV type '{vdev_type}' requires at least {min_devs} device(s), but only {num_devs} were added.")
                      return
                 has_vdevs = True

        if not has_vdevs:
            QMessageBox.warning(self, "No Devices", "Please add at least one VDEV with devices to the pool layout.")
            return

        super().accept()

# Example Usage Block (if run directly)
if __name__ == '__main__':
    import sys
    from PySide6.QtWidgets import QApplication # Ensure QApplication is imported

    app = QApplication(sys.argv)
    # Mock manager for testing dialog standalone
    class MockZFSManager:
        def list_block_devices(self):
            # Return devices with display_name formatted
            # linux-only: this sample uses Linux device names ('/dev/sd*', '/dev/nvme*') - other OSes may have different device paths
            devs = [
                 {'name': '/dev/sda', 'size_str': '100G', 'type': 'disk', 'label': 'SSD1'},
                 {'name': '/dev/sdb', 'size_str': '100G', 'type': 'disk', 'label': 'SSD2'},
                 {'name': '/dev/sdc', 'size_str': '50G', 'type': 'disk', 'label': ''},
                 {'name': '/dev/nvme0n1', 'size_str': '256G', 'type': 'disk', 'label': 'NVMeSys'},
                 {'name': '/dev/nvme1n1', 'size_str': '1T', 'type': 'disk', 'label': 'NVMeData1'},
                 {'name': '/dev/nvme2n1', 'size_str': '1T', 'type': 'disk', 'label': 'NVMeData2'},
            ]
            for d in devs:
                try:
                    # Use real utils if available
                    from utils import parse_size, format_size
                    d['size'] = parse_size(d['size_str'])
                    d['display_name'] = f"{d['name']} ({format_size(d['size'])}) {d.get('label', '')}".strip()
                except ImportError:
                    # Fallback if utils not found during standalone run
                    d['size'] = d['size_str']
                    d['display_name'] = f"{d['name']} ({d['size']}) {d.get('label', '')}".strip()

            return devs

    zfs_manager_mock = MockZFSManager()
    # Inject mock manager
    dialog = CreatePoolDialog(zfs_manager_mock)
    dialog._populate_available_devices() # Need to call manually after injection

    if dialog.exec():
        pool_config = dialog.get_pool_details()
        if pool_config:
            print("Pool Configuration Accepted:")
            import json
            print(json.dumps(pool_config, indent=2))
        else:
             print("Dialog accepted but failed to get data")
    else:
        print("Pool Creation Cancelled.")
    sys.exit()
# --- END OF FILE widgets/create_pool_dialog.py ---
