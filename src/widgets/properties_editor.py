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
# --- Import Constants ---
import constants
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

# --- Add Auto Snapshot Properties ---
AUTO_SNAPSHOT_OPTIONS = ['-', 'true', 'false'] # '-' represents inherit
for prop in constants.AUTO_SNAPSHOT_PROPS:
    # Example display name: "Auto Snapshot (Hourly)" from "com.sun:auto-snapshot:hourly"
    suffix = prop.split(':')[-1] if ':' in prop else 'Default'
    # --- Make Master Switch Name More Obvious ---
    is_master_switch = (prop == "com.sun:auto-snapshot")
    display_name = "Auto Snapshot (Master Switch)" if is_master_switch else f"Auto Snapshot ({suffix.capitalize()})"
    # --- End Master Switch Name Change ---
    # Allow editing only on Datasets/Volumes (not Pools or Snapshots)
    EDITABLE_PROPERTIES[prop] = (prop, display_name, 'combobox', AUTO_SNAPSHOT_OPTIONS, lambda obj: not isinstance(obj, Dataset))


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

        # --- REVISED LOGIC: Separate editable and non-editable properties BEFORE sorting --- 
        editable_rows_data = []
        non_editable_rows_data = []
        processed_keys = set() # Keep track of keys added to either list

        # First pass: Process properties defined as editable
        for prop_name in EDITABLE_PROPERTIES.keys():
            processed_keys.add(prop_name)
            prop_data = self._properties_cache.get(prop_name)
            editable_info = EDITABLE_PROPERTIES[prop_name]
            is_readonly_for_object = False
            if len(editable_info) > 4 and editable_info[4]: # Check for read_only_func
                try:
                    is_readonly_for_object = editable_info[4](zfs_object)
                except Exception as e:
                    print(f"Warning: Error evaluating read_only_func for property '{prop_name}': {e}")
                    is_readonly_for_object = True # Treat as read-only on error

            row_data = {
                'name': prop_name,
                'display_name': editable_info[1],
                'value': prop_data.get('value', '-') if prop_data else '-', # Default to '-' if not found
                'source': prop_data.get('source') if prop_data else ( 'inherited' if '/' in zfs_object.name else 'default'),
                'editable_info': editable_info if not is_readonly_for_object else None,
            }

            if not is_readonly_for_object:
                editable_rows_data.append(row_data)
            else:
                non_editable_rows_data.append(row_data)

        # Second pass: Add other properties found in cache that weren't processed yet
        for prop_name, prop_data in self._properties_cache.items():
            if prop_name not in processed_keys:
                non_editable_rows_data.append({
                    'name': prop_name,
                    'display_name': prop_name,
                    'value': prop_data.get('value', 'N/A'),
                    'source': prop_data.get('source'),
                    'editable_info': None,
                })

        # Sort each list independently by display name, with custom sort for editable auto-snapshot props
        # Define sort key function for auto-snapshot props
        def sort_key_auto_snapshot(row):
            prop_name = row['name']
            if prop_name in constants.AUTO_SNAPSHOT_SORT_ORDER:
                try:
                    return constants.AUTO_SNAPSHOT_SORT_ORDER.index(prop_name)
                except ValueError:
                    return float('inf') # Place unknown auto-snapshot props at the end
            return float('inf') # Place non-auto-snapshot props after
            
        # Sort editable properties: auto-snapshot first by custom order, then others alphabetically
        editable_auto_snapshot = sorted([r for r in editable_rows_data if r['name'] in constants.AUTO_SNAPSHOT_PROPS], key=sort_key_auto_snapshot)
        editable_other = sorted([r for r in editable_rows_data if r['name'] not in constants.AUTO_SNAPSHOT_PROPS], key=lambda r: r['display_name'])
        sorted_editable_rows = editable_auto_snapshot + editable_other

        # Sort non-editable properties alphabetically
        non_editable_rows_data.sort(key=lambda r: r['display_name'])
        
        # Combine the lists
        final_rows_data = sorted_editable_rows + non_editable_rows_data # Use the custom-sorted editable list

        # --- Adjust row count based on headers --- 
        num_rows = len(final_rows_data)
        if sorted_editable_rows: num_rows += 1 # Add 1 for editable header
        if non_editable_rows_data: num_rows += 1 # Add 1 for non-editable header
        self.table.setRowCount(num_rows) # Set row count including headers
        
        app_palette = QApplication.palette()
        
        # --- RENDER LOGIC: Add group headers --- 
        current_row_index = 0
        if sorted_editable_rows:
             # Insert header for editable
             header_item = QTableWidgetItem("Editable Properties")
             header_item.setTextAlignment(Qt.AlignCenter)
             header_item.setBackground(app_palette.color(QPalette.Base))
             self.table.insertRow(current_row_index)
             self.table.setItem(current_row_index, 0, header_item)
             self.table.setSpan(current_row_index, 0, 1, self.table.columnCount())
             current_row_index += 1
             
             # Render editable rows
             for data in sorted_editable_rows:
                 self._render_table_row(current_row_index, data, app_palette)
                 current_row_index += 1
                 
        if non_editable_rows_data:
             # Insert header for non-editable
             header_item_non = QTableWidgetItem("Other Properties" if sorted_editable_rows else "All Properties")
             header_item_non.setTextAlignment(Qt.AlignCenter)
             header_item_non.setBackground(app_palette.color(QPalette.Base))
             self.table.insertRow(current_row_index)
             self.table.setItem(current_row_index, 0, header_item_non)
             self.table.setSpan(current_row_index, 0, 1, self.table.columnCount())
             current_row_index += 1

             # Render non-editable rows
             for data in non_editable_rows_data:
                  self._render_table_row(current_row_index, data, app_palette)
                  current_row_index += 1

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        
    # --- NEW HELPER METHOD for rendering a single row --- 
    def _render_table_row(self, row, data, app_palette):
        prop_name = data['name']
        display_name = data['display_name']
        value = data['value']
        source = data['source']
        source_comp = source.lower() if source else None
        editable_info = data['editable_info']

        # Column 0: Property Name
        name_item = QTableWidgetItem(display_name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
        name_item.setToolTip(f"Internal name: {prop_name}")
        self.table.setItem(row, 0, name_item)

        # Column 1: Value
        value_item = QTableWidgetItem(self._format_value_display(prop_name, value))
        value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)
        if source and source_comp not in ['local', 'none', '-', 'default']:
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
            # Pass the correct current value ('-' if it was default/inherited)
            edit_button.clicked.connect(
                lambda checked=False, p=prop_name, v=value, e=editable_info: self._edit_property_dialog(p, v, e)
            )
            h_layout.addWidget(edit_button)

            # Only show Inherit button if source is specifically 'local'
            if source_comp == 'local':
                inherit_button = QPushButton("Inherit")
                inherit_button.setToolTip(f"Reset '{display_name}' to inherited value")
                inherit_button.clicked.connect(
                    lambda checked=False, p=prop_name: self._inherit_property_confirm(p)
                )
                h_layout.addWidget(inherit_button)
            elif source and source_comp not in ['local', 'none', '-', 'default']:
                # Display source text only if it's not local/default (and is editable)
                source_label = QLabel(f"({source})")
                source_label.setToolTip(f"Value source: {source}")
                h_layout.addWidget(source_label)

            h_layout.addStretch()
            widget.setLayout(h_layout)
            self.table.setCellWidget(row, 2, widget)
        else:
            # For non-editable rows, just display the source if it's not local/default
            source_str = f"({source})" if source and source_comp not in ['local', 'none', '-', 'default'] else ""
            source_item = QTableWidgetItem(source_str)
            source_item.setFlags(source_item.flags() & ~Qt.ItemIsEditable)
            if source and source_comp not in ['local', 'none', '-', 'default']:
                 disabled_text_color = app_palette.color(QPalette.Disabled, QPalette.Text)
                 source_item.setForeground(disabled_text_color)
            self.table.setItem(row, 2, source_item)


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
        """Opens a dialog to edit a property."""
        if not self._current_object: return

        # editable_info = (internal_name, display_name, widget_type, options, read_only_func)
        _internal_name, display_name, widget_type, options, _read_only_func = editable_info

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit Property: {display_name}")
        layout = QVBoxLayout(dialog)

        # Add descriptive label
        label_text = f"Set value for '{display_name}' on {self._current_object.name}:"
        layout.addWidget(QLabel(label_text))

        editor_widget = None
        if widget_type == 'lineedit':
            editor_widget = QLineEdit()
            # Check if current_value is None or '-' (common representations of unset/default)
            if current_value is not None and current_value != '-':
                editor_widget.setText(current_value)
            else:
                 editor_widget.setPlaceholderText("(Inherited or default)") # Provide context if empty
        elif widget_type == 'combobox':
            editor_widget = QComboBox()
            if options:
                editor_widget.addItems(options)
                # Attempt to set current index, handle None or values not in list
                try:
                    # Handle '-' for inherit option explicitly if present
                    if prop_name in constants.AUTO_SNAPSHOT_PROPS and current_value == '-':
                         idx = options.index('-') if '-' in options else -1
                    elif current_value in options:
                        idx = options.index(current_value)
                    else:
                        # If current value not in options (e.g., inherited non-standard value),
                        # select the first option ('inherit' or '-') as a default or indicate ambiguity.
                        idx = 0
                        print(f"Warning: Current value '{current_value}' for '{prop_name}' not in options {options}. Defaulting selection.", file=sys.stderr)

                    if idx != -1:
                         editor_widget.setCurrentIndex(idx)
                    else:
                         print(f"Warning: Could not find current value '{current_value}' or default '-' for '{prop_name}' in options {options}.", file=sys.stderr)
                         if options: editor_widget.setCurrentIndex(0) # Fallback to first item

                except ValueError:
                    print(f"Error: Could not find index for value '{current_value}' in options {options} for property '{prop_name}'.", file=sys.stderr)
                    if options: editor_widget.setCurrentIndex(0) # Fallback to first item if error

        if editor_widget:
            layout.addWidget(editor_widget)
        else:
            layout.addWidget(QLabel(f"Error: Unknown widget type '{widget_type}'"))

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec():
            new_value = ""
            should_inherit = False
            if isinstance(editor_widget, QLineEdit):
                new_value = editor_widget.text().strip()
                # Treat empty string as inherit for properties where this makes sense?
                # For now, require explicit inherit via button or combo.
                # if not new_value: # Optional: Treat empty line edit as inherit request
                #     self._inherit_property_confirm(prop_name)
                #     return

            elif isinstance(editor_widget, QComboBox):
                new_value = editor_widget.currentText()
                # Check if it's an auto-snapshot property and the inherit option ('-') was selected
                if prop_name in constants.AUTO_SNAPSHOT_PROPS and new_value == '-':
                    should_inherit = True
                elif new_value.lower() == 'inherit' and prop_name not in constants.AUTO_SNAPSHOT_PROPS:
                     # Handle standard 'inherit' option for non-snapshot props
                     should_inherit = True


            # --- Save or Inherit ---
            if should_inherit:
                 # We already confirmed the object exists, directly emit inherit request
                 print(f"GUI: Requesting inherit for {prop_name} on {self._current_object.name}")
                 self.inherit_property_requested.emit(self._current_object.name, prop_name)
            elif new_value != current_value:
                 # We already confirmed the object exists, directly emit set request
                 print(f"GUI: Requesting set {prop_name}={new_value} on {self._current_object.name}")
                 self.set_property_requested.emit(self._current_object.name, prop_name, new_value)
            else:
                 print(f"GUI: Value for {prop_name} not changed.")


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
