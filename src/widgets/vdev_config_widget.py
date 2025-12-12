# --- START OF FILE widgets/vdev_config_widget.py ---
"""
Shared VDEV Configuration Widget for Create Pool and Add VDEV dialogs.
Provides a 3-column layout: Available Devices | Action Buttons | VDEV Layout.
Supports 'create_pool' and 'add_vdev' modes.
"""

from PySide6.QtCore import Qt, Signal, Slot, QRect, QSize, QEvent, QModelIndex
from PySide6.QtGui import QIcon, QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QPushButton,
    QComboBox, QCheckBox, QAbstractItemView, QHeaderView, QMessageBox,
    QInputDialog, QApplication, QSizePolicy, QFrame, QLineEdit, QFormLayout,
    QDialog, QDialogButtonBox, QStyledItemDelegate, QStyle, QStyleOptionButton
)

from typing import Optional, Dict, List, Any, Tuple
import re

try:
    import utils
except ImportError:
    class MockUtils:
        def format_size(self, size): return str(size)
        def parse_size(self, size_str): return int(size_str) if str(size_str).isdigit() else 0
    utils = MockUtils()

try:
    from help_strings import HELP, get_vdev_help, get_empty_state
except ImportError:
    HELP = {}
    def get_vdev_help(t): return {}
    def get_empty_state(c): return {}

# Data roles for tree items
VDEV_TYPE_ROLE = Qt.UserRole + 1
VDEV_DEVICES_ROLE = Qt.UserRole + 2
DEVICE_PATH_ROLE = Qt.UserRole + 3

# VDEV types available for selection
VDEV_TYPES = ['disk', 'mirror', 'raidz1', 'raidz2', 'raidz3', 'log', 'cache', 'spare', 'special', 'special mirror', 'dedup', 'dedup mirror']

# Minimum devices per VDEV type
MIN_DEVICES = {
    'mirror': 2, 'raidz1': 3, 'raidz2': 4, 'raidz3': 5,
    'special mirror': 2, 'dedup mirror': 2
}

# Icon size for trash button
TRASH_ICON_SIZE = 16
TRASH_BUTTON_MARGIN = 4


class VdevItemDelegate(QStyledItemDelegate):
    """
    Custom delegate that paints a trash icon on VDEV rows (top-level items only).
    Clicking the trash icon triggers removal of the VDEV.
    """

    # Signal emitted when trash icon is clicked, passes the QTreeWidgetItem
    remove_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._trash_icon = QIcon.fromTheme("edit-delete", QIcon.fromTheme("user-trash"))
        self._hover_index = None

    def _get_trash_rect(self, option: 'QStyleOptionViewItem') -> QRect:
        """Calculate the rectangle for the trash icon."""
        icon_size = TRASH_ICON_SIZE
        margin = TRASH_BUTTON_MARGIN
        # Position on the right side of the cell
        x = option.rect.right() - icon_size - margin
        y = option.rect.center().y() - icon_size // 2
        return QRect(x, y, icon_size, icon_size)

    def paint(self, painter: QPainter, option: 'QStyleOptionViewItem', index: QModelIndex):
        """Paint the item with an optional trash icon for top-level items."""
        # Call base paint first
        super().paint(painter, option, index)

        # Only show trash icon for column 1 (Size/Type) and top-level items (VDEVs)
        if index.column() != 1:
            return

        # Get the tree widget and item
        tree_widget = option.widget
        if not tree_widget:
            return

        item = tree_widget.itemFromIndex(index)
        if not item or item.parent() is not None:
            # Not a top-level item (VDEV), skip
            return

        # Draw trash icon
        trash_rect = self._get_trash_rect(option)
        
        # Draw a subtle background if hovered
        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            hover_color = QColor(255, 100, 100, 40)  # Light red tint
            painter.fillRect(trash_rect.adjusted(-2, -2, 2, 2), hover_color)
            painter.restore()

        # Draw the icon
        self._trash_icon.paint(painter, trash_rect)

    def editorEvent(self, event: QEvent, model, option: 'QStyleOptionViewItem', index: QModelIndex) -> bool:
        """Handle mouse clicks on the trash icon."""
        if event.type() == QEvent.Type.MouseButtonRelease and index.column() == 1:
            tree_widget = option.widget
            if tree_widget:
                item = tree_widget.itemFromIndex(index)
                # Only handle clicks on top-level items (VDEVs)
                if item and item.parent() is None:
                    trash_rect = self._get_trash_rect(option)
                    if trash_rect.contains(event.pos()):
                        self.remove_requested.emit(item)
                        return True
        return super().editorEvent(event, model, option, index)

    def sizeHint(self, option: 'QStyleOptionViewItem', index: QModelIndex) -> QSize:
        """Add extra space for the trash icon."""
        size = super().sizeHint(option, index)
        if index.column() == 1:
            size.setWidth(size.width() + TRASH_ICON_SIZE + TRASH_BUTTON_MARGIN * 2)
        return size

class VdevConfigWidget(QWidget):
    """
    Reusable widget for configuring VDEVs with device selection.
    Provides a 3-column layout matching the WebUI design.
    
    Modes:
        'create_pool': Shows pool name input and force checkbox at top
        'add_vdev': Just the VDEV configuration (default)
    """

    # Signal emitted when configuration changes (for parent validation)
    configuration_changed = Signal()

    def __init__(self, parent=None, mode: str = 'add_vdev', pool_name: str = ''):
        super().__init__(parent)
        self._mode = mode
        self._pool_name_for_add_vdev = pool_name  # Used in 'add_vdev' mode for display
        
        # Determine empty state context
        if mode == 'create_pool':
            self._empty_state_context = 'create_pool_vdev_tree'
        else:
            self._empty_state_context = 'add_vdev_modal'
        
        self._available_devices_map: Dict[str, Dict[str, Any]] = {}
        self._safe_devices: List[Dict] = []
        self._all_devices: List[Dict] = []

        self._setup_ui()

    def _setup_ui(self):
        """Set up the layout."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # === TOP ROW: Pool Name & Force (only in create_pool mode) ===
        if self._mode == 'create_pool':
            top_row = QHBoxLayout()
            
            form_layout = QFormLayout()
            self.pool_name_edit = QLineEdit()
            self.pool_name_edit.setPlaceholderText("e.g., mypool, tank")
            form_layout.addRow("Pool Name:", self.pool_name_edit)
            top_row.addLayout(form_layout, 1)
            
            self.force_checkbox = QCheckBox("Force (-f)")
            self.force_checkbox.setToolTip(HELP.get("tooltips", {}).get("force_checkbox", "Override safety checks."))
            top_row.addWidget(self.force_checkbox, 0, Qt.AlignmentFlag.AlignBottom)
            
            outer_layout.addLayout(top_row)
            outer_layout.addSpacing(10)
        else:
            # For add_vdev mode, add a header if pool name provided
            if self._pool_name_for_add_vdev:
                header_label = QLabel(f"<b>Add VDEVs to Pool: {self._pool_name_for_add_vdev}</b>")
                outer_layout.addWidget(header_label)
            
            # Force checkbox for add_vdev mode too
            force_row = QHBoxLayout()
            force_row.addStretch()
            self.force_checkbox = QCheckBox("Force (-f)")
            self.force_checkbox.setToolTip(HELP.get("tooltips", {}).get("force_checkbox", "Override safety checks."))
            force_row.addWidget(self.force_checkbox)
            outer_layout.addLayout(force_row)

        # === MAIN 3-COLUMN LAYOUT ===
        main_layout = QHBoxLayout()

        # === LEFT PANE: Available Devices ===
        left_pane = QVBoxLayout()

        left_header = QHBoxLayout()
        left_header.addWidget(QLabel("<b>Available Devices:</b>"))
        left_header.addStretch()
        self.show_all_checkbox = QCheckBox("Show All")
        self.show_all_checkbox.setToolTip("Show all block devices including partitions")
        self.show_all_checkbox.toggled.connect(self._update_device_list_ui)
        left_header.addWidget(self.show_all_checkbox)
        left_pane.addLayout(left_header)

        self.available_devices_list = QListWidget()
        self.available_devices_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.available_devices_list.setSortingEnabled(True)
        self.available_devices_list.setMinimumWidth(200)
        left_pane.addWidget(self.available_devices_list)

        main_layout.addLayout(left_pane, 2)

        # === CENTER PANE: Action Buttons ===
        center_pane = QVBoxLayout()
        center_pane.addStretch()

        self.add_device_button = QPushButton(QIcon.fromTheme("go-next"), "")
        self.add_device_button.setToolTip("Add selected device(s) to the selected VDEV")
        self.add_device_button.setFixedSize(40, 40)
        self.add_device_button.clicked.connect(self._add_device_to_vdev)
        center_pane.addWidget(self.add_device_button, 0, Qt.AlignmentFlag.AlignCenter)

        center_pane.addSpacing(20)

        self.remove_device_button = QPushButton(QIcon.fromTheme("go-previous"), "")
        self.remove_device_button.setToolTip("Remove selected device or VDEV")
        self.remove_device_button.setFixedSize(40, 40)
        self.remove_device_button.clicked.connect(self._remove_selected_tree_item)
        center_pane.addWidget(self.remove_device_button, 0, Qt.AlignmentFlag.AlignCenter)

        center_pane.addStretch()
        main_layout.addLayout(center_pane, 0)

        # === RIGHT PANE: VDEV Layout ===
        right_pane = QVBoxLayout()
        right_pane.addWidget(QLabel("<b>VDEV Layout:</b>"))

        # Use QStackedWidget for consistent sizing between empty state and tree
        from PySide6.QtWidgets import QStackedWidget
        self.vdev_stack = QStackedWidget()
        self.vdev_stack.setMinimumHeight(300)

        # Page 0: Empty state
        empty_state_widget = QWidget()
        empty_state_layout = QVBoxLayout(empty_state_widget)
        empty_state_layout.setContentsMargins(10, 10, 10, 10)
        
        empty_state_help = get_empty_state(self._empty_state_context)
        steps_html = ""
        if "steps" in empty_state_help:
            steps_items = "".join([f"<li>{step}</li>" for step in empty_state_help.get("steps", [])])
            steps_html = f"<ol style='text-align:left; padding-left:20px;'>{steps_items}</ol>"

        self.empty_state_label = QLabel(f"""
            <div style='text-align:center; color:gray; padding: 20px;'>
            <b>{empty_state_help.get("title", "No VDEVs configured")}</b><br>
            {empty_state_help.get("message", "Add a VDEV to start.")}<br>
            {steps_html}
            </div>
        """)
        self.empty_state_label.setAlignment(Qt.AlignCenter)
        self.empty_state_label.setWordWrap(True)
        empty_state_layout.addWidget(self.empty_state_label)
        empty_state_widget.setStyleSheet("background: palette(base); border: 1px solid palette(mid); border-radius: 4px;")
        self.vdev_stack.addWidget(empty_state_widget)

        # Page 1: VDEV Tree
        self.vdev_tree = QTreeWidget()
        self.vdev_tree.setColumnCount(2)
        self.vdev_tree.setHeaderLabels(["VDEV / Device", "Size / Type"])
        self.vdev_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.vdev_tree.setMouseTracking(True)
        self.vdev_tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        header = self.vdev_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        # Apply custom delegate for trash icon on VDEV rows
        self._item_delegate = VdevItemDelegate(self.vdev_tree)
        self._item_delegate.remove_requested.connect(self._on_trash_icon_clicked)
        self.vdev_tree.setItemDelegate(self._item_delegate)

        self.vdev_stack.addWidget(self.vdev_tree)

        right_pane.addWidget(self.vdev_stack, 1)  # Stretch factor 1

        # VDEV Info label
        self.vdev_info_label = QLabel("")
        self.vdev_info_label.setWordWrap(True)
        self.vdev_info_label.setStyleSheet("color: gray; font-style: italic; padding: 5px;")
        self.vdev_info_label.setVisible(False)
        right_pane.addWidget(self.vdev_info_label)

        # Bottom row: VDEV Type ComboBox + Add VDEV button
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()

        self.vdev_type_combo = QComboBox()
        for vtype in VDEV_TYPES:
            self.vdev_type_combo.addItem(vtype)
        self.vdev_type_combo.addItem("Custom...")
        self.vdev_type_combo.currentTextChanged.connect(self._on_vdev_type_changed)
        self.vdev_type_combo.setMinimumWidth(120)
        bottom_row.addWidget(self.vdev_type_combo)

        self.add_vdev_button = QPushButton(QIcon.fromTheme("list-add"), "Add VDEV")
        self.add_vdev_button.clicked.connect(self._add_vdev)
        bottom_row.addWidget(self.add_vdev_button)

        right_pane.addLayout(bottom_row)

        main_layout.addLayout(right_pane, 3)
        outer_layout.addLayout(main_layout, 1)

        self._update_empty_state()

    def _update_empty_state(self):
        """Toggle between empty state (page 0) and tree (page 1)."""
        has_items = self.vdev_tree.topLevelItemCount() > 0
        self.vdev_stack.setCurrentIndex(1 if has_items else 0)

    def _on_vdev_type_changed(self, vdev_type: str):
        """Update info label when VDEV type selection changes."""
        if vdev_type == "Custom...":
            self.vdev_info_label.setVisible(False)
            return

        info = get_vdev_help(vdev_type)
        if not info:
            self.vdev_info_label.setVisible(False)
            return

        text = f"<b>{info.get('name', vdev_type)}</b>: {info.get('short', '')}"
        if info.get("warning"):
            text += f"<br><span style='color:red;'>⚠️ {info['warning']}</span>"
        elif info.get("tip"):
            text += f"<br><span style='color:green;'>💡 {info['tip']}</span>"

        self.vdev_info_label.setText(text)
        self.vdev_info_label.setVisible(True)

    def set_devices(self, safe_devices: List[Dict], all_devices: List[Dict]):
        """Set the available devices."""
        self._safe_devices = safe_devices
        self._all_devices = all_devices
        self._available_devices_map.clear()
        for dev in all_devices:
            self._available_devices_map[dev['name']] = dev
        self._update_device_list_ui()

    def _update_device_list_ui(self):
        """Refresh the available devices list."""
        self.available_devices_list.clear()

        devices = self._all_devices if self.show_all_checkbox.isChecked() else self._safe_devices

        used_paths = set()
        iterator = QTreeWidgetItemIterator(self.vdev_tree)
        while iterator.value():
            item = iterator.value()
            path = item.data(0, DEVICE_PATH_ROLE)
            if path:
                used_paths.add(path)
            iterator += 1

        if not devices:
            placeholder = QListWidgetItem("No suitable devices found.")
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
            placeholder.setForeground(QColor(Qt.GlobalColor.gray))
            self.available_devices_list.addItem(placeholder)
            return

        for dev in devices:
            if dev['name'] in used_paths:
                continue
            display_name = dev.get('display_name', dev['name'])
            item = QListWidgetItem(display_name)
            item.setData(Qt.ItemDataRole.UserRole, dev['name'])
            self.available_devices_list.addItem(item)

    def _add_vdev(self):
        """Add a new VDEV to the tree."""
        vdev_type = self.vdev_type_combo.currentText()

        if vdev_type == "Custom...":
            vdev_type, ok = QInputDialog.getText(self, "Custom VDEV Type", "Enter VDEV type:")
            if not ok or not vdev_type.strip():
                return
            vdev_type = vdev_type.strip().lower()

        self._on_vdev_type_changed(vdev_type)

        vdev_item = QTreeWidgetItem(self.vdev_tree)
        vdev_item.setText(0, f"VDEV ({vdev_type})")
        vdev_item.setText(1, vdev_type.upper())
        vdev_item.setData(0, VDEV_TYPE_ROLE, vdev_type)
        vdev_item.setData(0, VDEV_DEVICES_ROLE, [])
        vdev_item.setFlags(vdev_item.flags() | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)

        if vdev_type in ['mirror', 'raidz1', 'raidz2', 'raidz3', 'special mirror', 'dedup mirror']:
            vdev_item.setIcon(0, QIcon.fromTheme("drive-multidisk"))
        elif vdev_type in ['log', 'cache', 'spare', 'special', 'dedup']:
            vdev_item.setIcon(0, QIcon.fromTheme("drive-removable-media"))
        else:
            vdev_item.setIcon(0, QIcon.fromTheme("drive-harddisk"))

        self._update_empty_state()
        self.configuration_changed.emit()

    def _add_device_to_vdev(self):
        """Add selected available devices to the selected VDEV."""
        selected_vdev_items = self.vdev_tree.selectedItems()
        selected_available_items = self.available_devices_list.selectedItems()

        if not selected_vdev_items:
            QMessageBox.warning(self, "Selection Required", "Please select a VDEV in the layout first.")
            return
        if not selected_available_items:
            QMessageBox.warning(self, "Selection Required", "Please select device(s) from the Available Devices list.")
            return

        target_vdev_item = selected_vdev_items[0]
        while target_vdev_item.parent():
            target_vdev_item = target_vdev_item.parent()

        vdev_type = target_vdev_item.data(0, VDEV_TYPE_ROLE)
        if not vdev_type:
            QMessageBox.warning(self, "Invalid Selection", "Please select a VDEV group, not a device.")
            return

        current_devices = target_vdev_item.data(0, VDEV_DEVICES_ROLE) or []

        for item in selected_available_items:
            if not (item.flags() & Qt.ItemIsEnabled):
                continue
            device_path = item.data(Qt.ItemDataRole.UserRole)
            if device_path and device_path not in current_devices:
                current_devices.append(device_path)

                device_info = self._available_devices_map.get(device_path, {})
                size_bytes = device_info.get('size_bytes', 0)
                size_str = utils.format_size(utils.parse_size(str(size_bytes))) if size_bytes else "?"
                label = device_info.get('label', '')
                if not label or label == 'None':
                    label = ''

                tree_child = QTreeWidgetItem(target_vdev_item)
                tree_child.setText(0, f"  {device_path} {label}".strip())
                tree_child.setText(1, size_str)
                tree_child.setData(0, DEVICE_PATH_ROLE, device_path)
                tree_child.setIcon(0, QIcon.fromTheme("media-floppy"))

                self.available_devices_list.takeItem(self.available_devices_list.row(item))

        target_vdev_item.setData(0, VDEV_DEVICES_ROLE, current_devices)
        self.vdev_tree.expandItem(target_vdev_item)
        self.configuration_changed.emit()

    def _remove_selected_tree_item(self):
        """Remove selected VDEV or device from tree."""
        selected_items = self.vdev_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Selection Required", "Please select an item to remove.")
            return

        item_to_remove = selected_items[0]

        if item_to_remove.parent() is None:
            reply = QMessageBox.question(
                self, "Confirm Removal",
                f"Remove the entire VDEV '{item_to_remove.text(0)}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                for i in range(item_to_remove.childCount()):
                    child = item_to_remove.child(i)
                    device_path = child.data(0, DEVICE_PATH_ROLE)
                    if device_path:
                        self._return_device_to_available(device_path)
                self.vdev_tree.invisibleRootItem().removeChild(item_to_remove)
        else:
            device_path = item_to_remove.data(0, DEVICE_PATH_ROLE)
            parent_vdev = item_to_remove.parent()
            if device_path and parent_vdev:
                current_devices = parent_vdev.data(0, VDEV_DEVICES_ROLE) or []
                if device_path in current_devices:
                    current_devices.remove(device_path)
                    parent_vdev.setData(0, VDEV_DEVICES_ROLE, current_devices)
                parent_vdev.removeChild(item_to_remove)
                self._return_device_to_available(device_path)

        self._update_empty_state()
        self.configuration_changed.emit()

    @Slot(object)
    def _on_trash_icon_clicked(self, vdev_item: QTreeWidgetItem):
        """Handle trash icon click - remove VDEV without confirmation for quicker workflow."""
        if vdev_item is None or vdev_item.parent() is not None:
            return  # Only handle top-level VDEV items

        # Return all devices to available list
        for i in range(vdev_item.childCount()):
            child = vdev_item.child(i)
            device_path = child.data(0, DEVICE_PATH_ROLE)
            if device_path:
                self._return_device_to_available(device_path)

        # Remove the VDEV
        self.vdev_tree.invisibleRootItem().removeChild(vdev_item)
        self._update_empty_state()
        self.configuration_changed.emit()

    def _return_device_to_available(self, device_path: str):
        """Add a device back to the available list."""
        if device_path in self._available_devices_map:
            dev = self._available_devices_map[device_path]
            display_name = dev.get('display_name', dev['name'])
            item = QListWidgetItem(display_name)
            item.setData(Qt.ItemDataRole.UserRole, dev['name'])
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.available_devices_list.addItem(item)
        else:
            item = QListWidgetItem(device_path)
            item.setData(Qt.ItemDataRole.UserRole, device_path)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.available_devices_list.addItem(item)
        self.available_devices_list.sortItems()

    def get_vdev_specs(self) -> List[Dict[str, Any]]:
        """Return the list of VDEV specs."""
        specs = []
        for i in range(self.vdev_tree.topLevelItemCount()):
            vdev_item = self.vdev_tree.topLevelItem(i)
            vdev_type = vdev_item.data(0, VDEV_TYPE_ROLE)
            devices = vdev_item.data(0, VDEV_DEVICES_ROLE) or []
            if vdev_type and devices:
                specs.append({'type': vdev_type, 'devices': devices})
        return specs

    def get_pool_name(self) -> str:
        """Get the pool name (only valid in create_pool mode)."""
        if self._mode == 'create_pool' and hasattr(self, 'pool_name_edit'):
            return self.pool_name_edit.text().strip()
        return ""

    def get_force_flag(self) -> bool:
        """Get the force checkbox state."""
        return self.force_checkbox.isChecked() if hasattr(self, 'force_checkbox') else False

    def get_pool_details(self) -> Optional[Tuple[str, List[Dict[str, Any]], bool]]:
        """Get pool name, vdev specs, and force flag (for create_pool mode)."""
        pool_name = self.get_pool_name()
        vdev_specs = self.get_vdev_specs()
        force = self.get_force_flag()

        if not pool_name or not vdev_specs:
            return None

        return pool_name, vdev_specs, force

    def validate_configuration(self, require_data_vdev: bool = True) -> Tuple[bool, str]:
        """Validate the current configuration."""
        # Validate pool name in create_pool mode
        if self._mode == 'create_pool':
            pool_name = self.get_pool_name()
            if not pool_name:
                return False, "Pool name is required."
            if not re.match(r'^[a-zA-Z][a-zA-Z0-9_\-.]*$', pool_name):
                return False, "Pool name must start with a letter and contain only letters, numbers, underscores, hyphens, and periods."

        specs = self.get_vdev_specs()
        if not specs:
            return False, "Please add at least one VDEV with devices."

        for spec in specs:
            vdev_type = spec['type']
            devices = spec['devices']
            min_required = MIN_DEVICES.get(vdev_type, 1)
            if len(devices) < min_required:
                return False, f"VDEV type '{vdev_type}' requires at least {min_required} device(s), but only {len(devices)} were added."

        # Check for data VDEV
        if require_data_vdev:
            has_data_vdev = any(
                spec['type'] not in ['log', 'cache', 'spare']
                for spec in specs
            )
            if not has_data_vdev:
                return False, "Pool must contain at least one data VDEV (disk, mirror, raidz)."

        return True, ""

    def clear(self):
        """Clear all VDEVs and reset the widget."""
        self.vdev_tree.clear()
        self._update_empty_state()
        self._update_device_list_ui()


def show_vdev_config_dialog(
    parent,
    zfs_client,
    mode: str = 'add_vdev',
    pool_name: str = ''
) -> Optional[Tuple[str, List[Dict], bool]]:
    """
    Show a dialog with VdevConfigWidget and return the result.
    
    Args:
        parent: Parent widget
        zfs_client: ZfsManagerClient instance
        mode: 'create_pool' or 'add_vdev'
        pool_name: Pool name (for add_vdev mode display)
    
    Returns:
        Tuple of (pool_name, vdev_specs, force) or None if cancelled
    """
    dialog = QDialog(parent)
    if mode == 'create_pool':
        dialog.setWindowTitle("Create New ZFS Pool")
    else:
        dialog.setWindowTitle(f"Add VDEVs to Pool '{pool_name}'")
    
    dialog.setMinimumSize(850, 600)
    layout = QVBoxLayout(dialog)

    widget = VdevConfigWidget(parent=dialog, mode=mode, pool_name=pool_name)
    layout.addWidget(widget, 1)

    # Load devices
    try:
        result = zfs_client.list_block_devices()
        if not result.get('error'):
            widget.set_devices(result.get('devices', []), result.get('all_devices', []))
        else:
            QMessageBox.warning(dialog, "Error", f"Failed to list devices: {result['error']}")
    except Exception as e:
        QMessageBox.warning(dialog, "Error", f"Failed to list devices: {e}")

    # Dialog buttons
    button_box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    button_box.rejected.connect(dialog.reject)
    layout.addWidget(button_box)

    # Custom accept handler that validates first
    def on_accept():
        require_data = (mode == 'create_pool')
        is_valid, error_msg = widget.validate_configuration(require_data_vdev=require_data)
        if not is_valid:
            QMessageBox.warning(dialog, "Invalid Configuration", error_msg)
            return  # Don't close the dialog
        dialog.accept()

    button_box.accepted.connect(on_accept)

    if dialog.exec() == QDialog.DialogCode.Accepted:
        if mode == 'create_pool':
            return widget.get_pool_details()
        else:
            return (pool_name, widget.get_vdev_specs(), widget.get_force_flag())

    return None


# === Standalone Test ===
if __name__ == '__main__':
    import sys

    app = QApplication(sys.argv)

    # Test create_pool mode
    widget = VdevConfigWidget(mode='create_pool')
    widget.setWindowTitle("Create Pool Mode Test")
    widget.resize(850, 600)

    mock_safe = [
        {'name': '/dev/sda', 'display_name': '/dev/sda (100 GB) SSD1', 'size_bytes': 107374182400, 'label': 'SSD1'},
        {'name': '/dev/sdb', 'display_name': '/dev/sdb (100 GB) SSD2', 'size_bytes': 107374182400, 'label': 'SSD2'},
    ]
    mock_all = mock_safe + [
        {'name': '/dev/sdc', 'display_name': '/dev/sdc (50 GB)', 'size_bytes': 53687091200, 'label': ''},
        {'name': '/dev/nvme0n1', 'display_name': '/dev/nvme0n1 (256 GB) NVMe', 'size_bytes': 274877906944, 'label': 'NVMe'},
    ]

    widget.set_devices(mock_safe, mock_all)
    widget.show()

    sys.exit(app.exec())
# --- END OF FILE widgets/vdev_config_widget.py ---
