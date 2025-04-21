from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QPushButton, QHBoxLayout, QMessageBox, QLineEdit, QComboBox, QLabel, QDialog,
    QDialogButtonBox, QApplication,
    QHeaderView
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor, QPalette

from typing import Optional, Dict, Any

import zfs_manager
from models import Pool, Dataset, Snapshot, ZfsObject
# --- CORRECTED Import ---
import utils # Import the whole module
# subprocess no longer needed here
# import subprocess
import re
import sys
import traceback

# Import client class
from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError


# Define which properties are commonly editable
EDITABLE_PROPERTIES = {
    'mountpoint': ('mountpoint', 'Mount Point', 'lineedit', None, None),
    'quota': ('quota', 'Quota', 'lineedit', None, None),
    'reservation': ('reservation', 'Reservation', 'lineedit', None, None),
    'recordsize': ('recordsize', 'Record Size', 'combobox', ['inherit', '512'] + [f'{2**i}K' for i in range(7, 11)] + ['1M'], None),
    'compression': ('compression', 'Compression', 'combobox', ['inherit', 'off', 'on', 'lz4', 'gzip', 'gzip-1', 'gzip-9', 'zle', 'lzjb', 'zstd', 'zstd-fast'], None),
    'atime': ('atime', 'Access Time (atime)', 'combobox', ['inherit', 'on', 'off'], None),
    'relatime': ('relatime', 'Relative Access Time', 'combobox', ['inherit', 'on', 'off'], None),
    'readonly': ('readonly', 'Read Only', 'combobox', ['inherit', 'on', 'off'], None),
    'dedup': ('dedup', 'Deduplication', 'combobox', ['inherit', 'on', 'off', 'verify', 'sha256', 'sha512', 'skein', 'edonr'], lambda obj: isinstance(obj, Snapshot)),
    'sharenfs': ('sharenfs', 'NFS Share Options', 'lineedit', None, lambda obj: isinstance(obj, Snapshot)),
    'sharesmb': ('sharesmb', 'SMB Share Options', 'lineedit', None, lambda obj: isinstance(obj, Snapshot)),
    'logbias': ('logbias', 'Log Bias', 'combobox', ['inherit', 'latency', 'throughput'], lambda obj: isinstance(obj, Snapshot)),
    'sync': ('sync', 'Sync Policy', 'combobox', ['inherit', 'standard', 'always', 'disabled'], lambda obj: isinstance(obj, Snapshot)),
    'volblocksize': ('volblocksize', 'Volume Block Size', 'combobox', ['inherit'] + [f'{2**i}K' for i in range(9, 18)] + ['1M'], lambda obj: not (isinstance(obj, Dataset) and obj.obj_type == 'volume')),
    'comment': ('comment', 'Pool Comment', 'lineedit', None, lambda obj: not isinstance(obj, Pool)),
    'cachefile': ('cachefile', 'Cache File', 'lineedit', None, lambda obj: not isinstance(obj, Pool)),
    'bootfs': ('bootfs', 'Boot FS', 'lineedit', None, lambda obj: not isinstance(obj, Pool)),
    'failmode': ('failmode', 'Fail Mode', 'combobox', ['wait', 'continue', 'panic'], lambda obj: not isinstance(obj, Pool)),
    'autoreplace': ('autoreplace', 'Auto Replace', 'combobox', ['on', 'off'], lambda obj: not isinstance(obj, Pool)),
    'autotrim': ('autotrim', 'Auto Trim', 'combobox', ['on', 'off'], lambda obj: not isinstance(obj, Pool)),
}

DISPLAY_ONLY_PROPERTIES = [
    'name', 'type', 'creation', 'guid', 'version',
    'health', 'size', 'alloc', 'free', 'cap', 'frag',
    'used', 'available', 'referenced', 'logicalused', 'logicalreferenced',
    'origin', 'keystatus', 'encryption', 'keyformat', 'pbkdf2iters',
    'mounted', 'removable',
]


class PropertiesEditor(QWidget):
    """Widget to display and edit ZFS object properties."""
    status_message = Signal(str)
    set_property_requested = Signal(str, str, str)
    inherit_property_requested = Signal(str, str)

    def __init__(self, zfs_client: ZfsManagerClient, parent=None):
        super().__init__(parent)
        self._current_object: Optional[ZfsObject] = None
        self._properties_cache: Dict[str, Dict[str, str]] = {}
        # Store the client instance
        self.zfs_client = zfs_client
        if self.zfs_client is None:
            raise ValueError("ZfsManagerClient instance is required for PropertiesEditor.")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Property", "Value", "Action / Source"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self.table)

    def set_object(self, zfs_object: Optional[ZfsObject]):
        """Displays properties for the given ZfsObject."""
        self._current_object = zfs_object
        self._properties_cache = {}
        self.table.clearContents()
        self.table.setRowCount(0)

        if not zfs_object:
            return

        # Determine the correct name/path to use for the API call
        object_identifier = None
        if isinstance(zfs_object, Snapshot):
            # For snapshots, use the full path stored in properties
            object_identifier = zfs_object.properties.get('full_snapshot_name')
            if not object_identifier:
                 # Fallback if property missing (should not happen)
                 object_identifier = f"{zfs_object.dataset_name}@{zfs_object.name}"
                 print(f"WARNING: PropertiesEditor using constructed name for snapshot: {object_identifier}", file=sys.stderr)
        elif isinstance(zfs_object, (Pool, Dataset)):
             # For pools and datasets, use their standard name/path
             object_identifier = zfs_object.name
        else:
            print(f"WARNING: PropertiesEditor received unknown object type: {type(zfs_object)}", file=sys.stderr)
            self.status_message.emit(f"Cannot fetch properties for unknown object type.")
            return

        if not object_identifier:
             # Should not happen if logic above is correct
             print(f"ERROR: PropertiesEditor could not determine identifier for object: {zfs_object}", file=sys.stderr)
             self.status_message.emit(f"Internal error: Could not identify object.")
             return

        self.status_message.emit(f"Fetching properties for {object_identifier}...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        success = False
        fetched_props = {}
        error_msg = ""
        try:
            # Use the determined object_identifier for the API call
            success, fetched_props, error_msg = self.zfs_client.get_all_properties_with_sources(object_identifier)
        except (ZfsCommandError, ZfsClientCommunicationError, TimeoutError) as e:
            error_msg = f"Error fetching properties: {e}"
        except Exception as e:
            error_msg = f"Unexpected error fetching properties: {e}"
            traceback.print_exc(file=sys.stderr) # Log unexpected errors
        finally:
            QApplication.restoreOverrideCursor()

        if not success:
            # Use object_identifier in the error message for clarity
            QMessageBox.warning(self, "Error Fetching Properties", f"Failed to get properties for '{object_identifier}'.\n\n{error_msg}")
            self.status_message.emit(f"Failed to fetch properties for {object_identifier}.")
            return
        else:
             self._properties_cache = fetched_props
             self.status_message.emit("") # Clear status

        display_order = list(EDITABLE_PROPERTIES.keys()) + [p for p in DISPLAY_ONLY_PROPERTIES if p not in EDITABLE_PROPERTIES]
        rows_data = []

        for prop_name in display_order:
            prop_data = self._properties_cache.get(prop_name)
            if prop_data:
                value = prop_data.get('value', 'N/A')
                source = prop_data.get('source')
                editable_info = EDITABLE_PROPERTIES.get(prop_name)
                is_readonly_for_object = False
                if editable_info and len(editable_info) > 4 and editable_info[4]:
                    try:
                        is_readonly_for_object = editable_info[4](zfs_object)
                    except Exception as e:
                        print(f"Warning: Error evaluating read_only_func for property '{prop_name}': {e}")
                        is_readonly_for_object = True

                rows_data.append({
                    'name': prop_name,
                    'display_name': editable_info[1] if editable_info else prop_name,
                    'value': value,
                    'source': source,
                    'editable_info': editable_info if not is_readonly_for_object else None,
                })

        for prop_name, prop_data in self._properties_cache.items():
            if prop_name not in [r['name'] for r in rows_data]:
                 rows_data.append({
                    'name': prop_name,
                    'display_name': prop_name,
                    'value': prop_data.get('value', 'N/A'),
                    'source': prop_data.get('source'),
                    'editable_info': None,
                })

        rows_data.sort(key=lambda r: r['display_name'])
        self.table.setRowCount(len(rows_data))

        app_palette = QApplication.palette()

        for row, data in enumerate(rows_data):
            prop_name = data['name']
            display_name = data['display_name']
            value = data['value']
            source_comp = data['source'].lower() if data['source'] else None
            editable_info = data['editable_info']
            display_source = data['source']

            # Column 0: Property Name
            name_item = QTableWidgetItem(display_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            name_item.setToolTip(f"Internal name: {prop_name}")
            self.table.setItem(row, 0, name_item)

            # Column 1: Value
            value_item = QTableWidgetItem(self._format_value_display(prop_name, value))
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)
            if display_source and source_comp not in ['local', 'none', '-']:
                 disabled_text_color = app_palette.color(QPalette.Disabled, QPalette.Text)
                 value_item.setForeground(disabled_text_color)
            self.table.setItem(row, 1, value_item)

            # Column 2: Action / Source
            if editable_info:
                widget = QWidget()
                h_layout = QHBoxLayout(widget)
                h_layout.setContentsMargins(2, 2, 2, 2)
                h_layout.setSpacing(4)
                edit_button = QPushButton("Edit")
                edit_button.setToolTip(f"Edit '{display_name}' property")
                edit_button.clicked.connect(
                    lambda checked=False, p=prop_name, v=value, e=editable_info: self._edit_property_dialog(p, v, e)
                )
                h_layout.addWidget(edit_button)

                if source_comp == 'local':
                    inherit_button = QPushButton("Inherit")
                    inherit_button.setToolTip(f"Reset '{display_name}' to inherited value")
                    inherit_button.clicked.connect(
                        lambda checked=False, p=prop_name: self._inherit_property_confirm(p)
                    )
                    h_layout.addWidget(inherit_button)
                elif display_source and display_source not in ['none', '-']:
                    source_label = QLabel(f"({display_source})")
                    source_label.setToolTip(f"Value source: {display_source}")
                    h_layout.addWidget(source_label)

                h_layout.addStretch()
                widget.setLayout(h_layout)
                self.table.setCellWidget(row, 2, widget)
            else:
                source_str = f"({display_source})" if display_source and source_comp not in ['local', 'none', '-'] else ""
                source_item = QTableWidgetItem(source_str)
                source_item.setFlags(source_item.flags() & ~Qt.ItemIsEditable)
                if display_source and source_comp not in ['local', 'none', '-']:
                     disabled_text_color = app_palette.color(QPalette.Disabled, QPalette.Text)
                     source_item.setForeground(disabled_text_color)
                self.table.setItem(row, 2, source_item)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)


    def _format_value_display(self, prop_name, value):
        """Format certain property values for better display."""
        # Uses utils directly now, no local import needed
        size_props = ['quota', 'reservation', 'volsize', 'used', 'available', 'referenced', 'size', 'alloc', 'free', 'logicalused', 'logicalreferenced', 'recordsize', 'volblocksize']
        if prop_name in size_props and value not in ['-', 'none']:
            try:
                 byte_val = utils.parse_size(value)
                 if byte_val > 0 or value in ('0', '0B'):
                      formatted_size = utils.format_size(byte_val)
                      if formatted_size == "0B" and value != "0B":
                          display_text = f"{formatted_size} ({value})"
                      elif formatted_size != "0B":
                           display_text = f"{formatted_size} ({value})"
                      else:
                          display_text = formatted_size
                      return display_text
                 else:
                      return value
            except ValueError:
                 return value
        return value

    @Slot()
    def _edit_property_dialog(self, prop_name, current_value, editable_info):
        """Shows the dialog to get the new property value."""
        # Uses utils directly now, no local import needed

        if not self._current_object: return

        obj_name = self._current_object.name
        if len(editable_info) < 3:
             self.status_message.emit(f"Internal error: Invalid editable info for {prop_name}")
             return
        display_name = editable_info[1]
        editor_type = editable_info[2]
        options = editable_info[3] if len(editable_info) > 3 else None

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit Property: {display_name}")
        layout = QVBoxLayout(dialog)
        label = QLabel(f"Set '{display_name}' for '{obj_name}':")
        layout.addWidget(label)
        editor_widget = None

        if editor_type == 'lineedit':
            editor_widget = QLineEdit(current_value)
            if prop_name in ['quota', 'reservation', 'volsize']:
                editor_widget.setPlaceholderText("e.g., 10G, 500M, none")
        elif editor_type == 'combobox' and options:
            editor_widget = QComboBox()
            editor_widget.addItems(options)
            current_value_str = str(current_value)
            try:
                idx = options.index(current_value_str)
                editor_widget.setCurrentIndex(idx)
            except ValueError:
                 if current_value_str not in options:
                      editor_widget.addItem(current_value_str)
                 editor_widget.setCurrentText(current_value_str)
        else:
             QMessageBox.warning(self, "Error", f"Unsupported editor type '{editor_type}' for property '{prop_name}'.")
             return

        if editor_widget:
            layout.addWidget(editor_widget)
        else:
             label_error = QLabel("Error: Could not create editor.")
             layout.addWidget(label_error)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec():
            new_value = ""
            if isinstance(editor_widget, QLineEdit):
                new_value = editor_widget.text().strip()
            elif isinstance(editor_widget, QComboBox):
                new_value = editor_widget.currentText()

            if not editor_widget or new_value == current_value:
                self.status_message.emit("Value not changed." if editor_widget else "Edit cancelled.")
                return

            # Client-side validation BEFORE emitting signal
            try:
                if prop_name in ['quota', 'reservation', 'volsize'] and new_value.lower() != 'none':
                     if not new_value.isdigit():
                         parsed = utils.parse_size(new_value)
                         if parsed == 0 and new_value not in ('0', '0B'):
                              raise ValueError(f"Invalid size format")
            except ValueError as ve:
                 QMessageBox.warning(self, "Invalid Input", f"Invalid size format: '{new_value}'. Use numbers or units like K, M, G, T, or 'none'.")
                 self.status_message.emit("Invalid input provided.")
                 return

            # Emit signal to request the action
            self.status_message.emit(f"Requesting to set {prop_name} to '{new_value}'...")
            self.set_property_requested.emit(obj_name, prop_name, new_value)


    @Slot()
    def _inherit_property_confirm(self, prop_name):
        """Confirms and emits signal to inherit a property."""
        if not self._current_object: return

        obj_name = self._current_object.name
        display_name = prop_name
        if prop_name in EDITABLE_PROPERTIES:
            display_name = EDITABLE_PROPERTIES[prop_name][1]

        reply = QMessageBox.question(self, "Confirm Inherit",
                                     f"Are you sure you want to reset the property '{display_name}' for '{obj_name}' to its inherited value?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            self.status_message.emit(f"Requesting to inherit {prop_name}...")
            self.inherit_property_requested.emit(obj_name, prop_name)
