# --- START OF FILE widgets/pool_editor_widget.py ---

import re
from typing import Optional, Dict, List, Any # Import necessary types

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem, QPushButton,
    QMessageBox, QInputDialog, QComboBox, QLabel, QDialog, QDialogButtonBox,
    QHeaderView, QApplication, QAbstractItemView, QSplitter, QListWidget,
    QListWidgetItem, QLineEdit, QCheckBox # <-- Added QCheckBox
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QIcon, QColor, QPalette

# Assuming models.py is in the parent directory or Python path
import sys
import os
# Use ..widgets for relative imports if structure allows, otherwise adjust path
try:
    # Assuming models, utils, zfs_manager are accessible in the Python path
    from models import Pool
    import utils
    # Import client class and errors
    from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError
except ImportError:
    # Fallback for potential path issues or running standalone
    print("Warning: Could not import models/utils/zfs_manager. Functionality may be limited.")
    # Define mocks or stubs if needed for standalone testing
    class Pool: # Dummy class for standalone testing if needed
         def __init__(self, name="dummy", status_details=""):
              self.name = name
              self.status_details = status_details
    class MockUtils:
        def format_size(self, size): return str(size)
        def parse_size(self, size_str): return int(size_str) if size_str.isdigit() else 0
    class MockZFSManagerClient: # Use Mock Client
        def list_block_devices(self): return []
        def __getattr__(self, name): return lambda *a, **k: (_ for _ in ()).throw(RuntimeError(f"MockZFSManagerClient.{name} called"))
    utils = MockUtils()
    # Assign mock client class
    ZfsManagerClient = MockZFSManagerClient
    class QColor: # Dummy QColor if Qt not fully available
        def __init__(self, *args): pass
    class QPalette: # Dummy QPalette
        ColorRole = None
        def color(self, role, group): return None


# --- Module-level Constants ---
ITEM_TYPE_ROLE = Qt.UserRole + 1
DEVICE_PATH_ROLE = Qt.UserRole + 2
VDEV_TYPE_ROLE = Qt.UserRole + 3
DEVICE_STATE_ROLE = Qt.UserRole + 4
ITEM_INDENT_ROLE = Qt.UserRole + 5
VDEV_DEVICES_ROLE = Qt.UserRole + 6 # Re-using role from CreatePoolDialog for consistency

class PoolEditorWidget(QWidget):
    """Widget for editing an existing ZFS pool's structure (Refined Text Parsing)."""
    # Signals
    status_message = Signal(str)
    attach_device_requested = Signal(str, str, str) # pool, existing_dev, new_dev
    detach_device_requested = Signal(str, str) # pool, device
    replace_device_requested = Signal(str, str, str) # pool, old_dev, new_dev (empty if mark only)
    offline_device_requested = Signal(str, str, bool) # pool, device, temporary
    online_device_requested = Signal(str, str, bool) # pool, device, expand
    add_vdev_requested = Signal(str, list, bool) # pool, vdev_specs_list, force
    remove_vdev_requested = Signal(str, str) # pool, device_or_vdev_id
    split_pool_requested = Signal(str, str, dict) # old_pool, new_pool, options

    def __init__(self, zfs_client: ZfsManagerClient, parent=None):
        super().__init__(parent)
        self._current_pool: Optional[Pool] = None
        self._current_pool_status_text: str = "" # Store the text used for parsing
        # Store the client instance
        self.zfs_client = zfs_client
        if self.zfs_client is None:
            raise ValueError("ZfsManagerClient instance is required for PoolEditorWidget.")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # --- Toolbar ---
        toolbar_layout = QHBoxLayout()
        self.attach_button = QPushButton(QIcon.fromTheme("list-add"), "Attach (Mirror)")
        self.attach_button.clicked.connect(self._attach_device)
        self.detach_button = QPushButton(QIcon.fromTheme("list-remove"), "Detach")
        self.detach_button.clicked.connect(self._detach_device)
        self.replace_button = QPushButton(QIcon.fromTheme("edit-find-replace"), "Replace")
        self.replace_button.clicked.connect(self._replace_device)
        self.offline_button = QPushButton(QIcon.fromTheme("media-playback-stop"), "Offline")
        self.offline_button.clicked.connect(self._offline_device)
        self.online_button = QPushButton(QIcon.fromTheme("media-playback-start"), "Online")
        self.online_button.clicked.connect(self._online_device)
        self.add_vdev_button = QPushButton(QIcon.fromTheme("edit-add"), "Add VDEV")
        self.add_vdev_button.clicked.connect(self._add_vdev)
        self.remove_vdev_button = QPushButton(QIcon.fromTheme("edit-delete"), "Remove")
        self.remove_vdev_button.clicked.connect(self._remove_vdev)
        self.split_button = QPushButton(QIcon.fromTheme("edit-cut"), "Split")
        self.split_button.clicked.connect(self._split_pool)

        # Add buttons to layout (adjust spacing/stretch as needed)
        toolbar_layout.addWidget(self.attach_button)
        toolbar_layout.addWidget(self.detach_button)
        toolbar_layout.addWidget(self.replace_button)
        toolbar_layout.addWidget(self.offline_button)
        toolbar_layout.addWidget(self.online_button)
        toolbar_layout.addSpacing(20) # Separator
        toolbar_layout.addWidget(self.add_vdev_button)
        toolbar_layout.addWidget(self.remove_vdev_button)
        toolbar_layout.addWidget(self.split_button)
        toolbar_layout.addStretch()
        layout.addLayout(toolbar_layout)

        # --- Tree View ---
        self.pool_tree = QTreeWidget()
        self.pool_tree.setColumnCount(5)
        self.pool_tree.setHeaderLabels(["Pool / VDEV / Device", "State", "Read", "Write", "Cksum"])
        self.pool_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.pool_tree.setAlternatingRowColors(True)
        header = self.pool_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 5):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.pool_tree.itemSelectionChanged.connect(self._update_button_states)
        layout.addWidget(self.pool_tree)

        self.setLayout(layout)
        self._update_button_states()

    def set_pool(self, pool: Optional[Pool]):
        """Populates the editor using the status_details from the Pool object."""
        self._current_pool = pool
        self.pool_tree.clear()

        if not pool:
             self._current_pool_status_text = ""
             self._update_button_states()
             return

        # --- Use the status_details directly from the Pool object ---
        status_text = getattr(pool, 'status_details', '') # Use getattr for safety

        if not status_text:
            print(f"PoolEditorWidget: Warning - Pool '{pool.name}' object provided has empty status_details.", file=sys.stderr)
            error_item = QTreeWidgetItem(self.pool_tree)
            error_item.setText(0, f"Status details unavailable for {pool.name}")
            error_item.setIcon(0, QIcon.fromTheme("dialog-warning"))
            self._current_pool_status_text = ""
            self._update_button_states()
            return
        # -------------------------------------------------------------

        # Store the text and proceed with parsing
        self._current_pool_status_text = status_text
        self.status_message.emit(f"Parsing status for {pool.name}...")
        self._parse_pool_status() # Parse the stored text
        self.status_message.emit("") # Clear status

        self.pool_tree.expandAll()
        if self.pool_tree.topLevelItemCount() > 0:
            self.pool_tree.setCurrentItem(self.pool_tree.topLevelItem(0))
        self._update_button_states()


    def _parse_pool_status(self):
        """
        Parses the 'zpool status -vP' output (stored in _current_pool_status_text)
        to populate the tree. Relies on relative indentation and pattern matching.
        """
        if not self._current_pool or not self._current_pool_status_text:
            return

        pool_name = self._current_pool.name
        lines = self._current_pool_status_text.splitlines()

        self.pool_tree.clear() # Clear previous content before parsing

        pool_item = QTreeWidgetItem(self.pool_tree)
        pool_item.setText(0, pool_name)
        pool_item.setData(0, ITEM_TYPE_ROLE, 'pool')
        pool_item.setData(0, ITEM_INDENT_ROLE, -1) # Special indent for root
        pool_item.setIcon(0, QIcon.fromTheme("drive-harddisk"))

        # Regex to capture lines with state/error columns
        item_re = re.compile(r'^(\s+)(.+?)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)')
        # Regex to capture lines *without* state/error columns (likely VDEV groups)
        group_re = re.compile(r'^(\s+)(\S+.*)')
        # Regex to identify potential device paths/names more broadly
        # linux-only: device paths like '/dev/sd*' and '/dev/nvme*' are Linux-specific naming conventions; other OSes may differ
        device_pattern_re = re.compile(r'^(/dev/\S+|ata-|wwn-|scsi-|nvme-|usb-|dm-|zd\d+|[a-z]+[0-9]+|gpt/.*|disk/by-.*)', re.IGNORECASE)
        # Regex for standard VDEV group names
        vdev_group_patterns = {
            'mirror': re.compile(r'^mirror-\d+'), 'raidz1': re.compile(r'^raidz1-\d+'),
            'raidz2': re.compile(r'^raidz2-\d+'), 'raidz3': re.compile(r'^raidz3-\d+'),
            'draid': re.compile(r'^draid\d*:'), 'log': re.compile(r'^logs$'),
            'cache': re.compile(r'^cache$'), 'spare': re.compile(r'^spares$'),
            'special': re.compile(r'^special$'),
        }

        in_config_section = False
        parent_stack: List[QTreeWidgetItem] = [pool_item] # Stack to track current parent based on indent
        app_palette = QApplication.palette() # Get palette for coloring
        pool_state = "UNKNOWN"
        scan_info = ""

        # First pass to get overall state and scan info cleanly
        for line in lines:
            line_strip = line.strip()
            if line_strip.startswith("pool:"):
                pass
            elif line_strip.startswith("state:"):
                pool_state = line_strip.split(":", 1)[1].strip()
            elif line_strip.startswith("status:"):
                pass
            elif line_strip.startswith("action:"):
                pass
            elif line_strip.startswith("scan:"):
                 scan_info = line_strip.split(":", 1)[1].strip()
            elif line_strip.startswith("config:"):
                 break

        pool_item.setToolTip(0, f"Pool: {pool_name}\nState: {pool_state}\nScan: {scan_info}")

        # Second pass for config section
        for line in lines:
            line_strip = line.strip()
            if line_strip.startswith("config:"):
                in_config_section = True
                continue
            if not in_config_section or not line_strip: # Skip empty lines within config
                continue
            if line_strip.startswith("errors:"):
                break # Stop at errors section

            # --- *** FIX: Handle both line types (with and without state/errors) *** ---
            match_item = item_re.match(line)
            match_group = group_re.match(line) # Try matching group line as well
            item = None # The QTreeWidgetItem to be created
            indent = 0
            name = ""
            state = "N/A" # Default state if not parsed
            r, w, c = ('N/A',)*3 # Default errors if not parsed

            if match_item:
                # Line has state/error columns (likely device or pool name repeat)
                indent_str, name_capture, state, r, w, c = match_item.groups()
                indent = len(indent_str)
                name = name_capture.strip()

                # Skip header row and the pool name repetition under config
                if name == "NAME" and state == "STATE": continue
                if name == pool_name and len(parent_stack) == 1 and parent_stack[-1] == pool_item: continue

            elif match_group:
                # Line does NOT have state/error columns (likely VDEV group name)
                indent_str, name_capture = match_group.groups()
                indent = len(indent_str)
                name = name_capture.strip()
                # Check if it's the pool name repetition (can happen without state cols too)
                if name == pool_name and len(parent_stack) == 1 and parent_stack[-1] == pool_item: continue
                # Leave state/errors as N/A for VDEV groups

            else:
                # Line doesn't match either pattern, skip it
                print(f"PoolEditorWidget: Skipping unparseable line: '{line.strip()}'", file=sys.stderr)
                continue

            # Adjust parent stack based on indentation
            while len(parent_stack) > 1 and indent <= parent_stack[-1].data(0, ITEM_INDENT_ROLE):
                parent_stack.pop()
            current_parent = parent_stack[-1]

            # Determine item type based on name and context
            item_type = 'unknown'
            vdev_type = 'unknown' # VDEV type (mirror, raidz1, disk, log, etc.)
            is_vdev_group = False # Is it a grouping like mirror-0?
            is_device = False     # Is it a leaf device path?
            device_path_for_role = None # Store the actual path if it's a device

            # Check if it's a known VDEV group (mirror-N, raidzN-N, logs, cache, etc.)
            for vtype, pattern in vdev_group_patterns.items():
                if pattern.match(name):
                    vdev_type = vtype
                    item_type = 'vdev'
                    is_vdev_group = True
                    break

            # If not a group, check if it looks like a device path
            # This check should happen ONLY if match_item was successful (line had state/errors)
            # OR if it's under a known VDEV group parent (mirror, raidz, log, etc.)
            parent_vdev_type = current_parent.data(0, VDEV_TYPE_ROLE) if current_parent and current_parent != pool_item else None
            is_under_known_vdev_group = parent_vdev_type and parent_vdev_type != 'unknown'

            if not is_vdev_group and (match_item or is_under_known_vdev_group):
                 if device_pattern_re.match(name):
                      item_type = 'device'
                      is_device = True
                      device_path_for_role = name # Assume name is the path
                      # Inherit vdev_type from parent if it's a known group
                      if is_under_known_vdev_group:
                           # Add this device path to the parent VDEV's device list
                           parent_devices = current_parent.data(0, VDEV_DEVICES_ROLE) or []
                           if device_path_for_role not in parent_devices:
                               parent_devices.append(device_path_for_role)
                               current_parent.setData(0, VDEV_DEVICES_ROLE, parent_devices)
                           # Set the vdev_type for the device item itself
                           if parent_vdev_type:
                                vdev_type = parent_vdev_type
                      # If it's directly under pool, it acts as a 'disk' vdev
                      elif current_parent == pool_item:
                           vdev_type = 'disk'
                           item_type = 'vdev' # Treat single disk as a VDEV conceptually
                           is_vdev_group = False # It's not a group like mirror-N
                           is_device = False # Conceptually a VDEV, not just a device leaf
                           # Store its own path in its device list
                           item_devices = [device_path_for_role]
                           # We'll set VDEV_DEVICES_ROLE later when creating the item

            # If it's directly under the pool, not a known group, and didn't match device pattern
            # it might still be a single disk VDEV (e.g., a file path used as vdev)
            elif not is_vdev_group and not is_device and current_parent == pool_item:
                 vdev_type = 'disk' # Assume disk
                 item_type = 'vdev' # Treat it as a VDEV conceptually
                 is_vdev_group = False
                 is_device = False
                 item_devices = [name] # Use the name as the 'path'
                 # Don't set device_path_for_role unless it matched device pattern

            # Log if type couldn't be determined (should be less common now)
            if item_type == 'unknown':
                 print(f"PoolEditorWidget: Warning - Unidentified item type: '{name}' under '{current_parent.text(0)}'", file=sys.stderr)


            # Create the tree item
            item = QTreeWidgetItem(current_parent)
            item.setText(0, name)
            item.setText(1, state)
            item.setText(2, r)
            item.setText(3, w)
            item.setText(4, c)

            # Store metadata in roles
            item.setData(0, ITEM_INDENT_ROLE, indent)
            item.setData(0, ITEM_TYPE_ROLE, item_type)
            item.setData(0, VDEV_TYPE_ROLE, vdev_type)
            item.setData(0, DEVICE_STATE_ROLE, state)
            if device_path_for_role:
                item.setData(0, DEVICE_PATH_ROLE, device_path_for_role)
            # Store the list of devices for VDEV items (single disk or group)
            if item_type == 'vdev':
                # Initialize with item_devices if it's a single disk vdev, else empty list for groups
                item.setData(0, VDEV_DEVICES_ROLE, item_devices if vdev_type == 'disk' else [])

            # Set tooltip and icon
            tooltip_text = f"Name: {name}\nState: {state}\nType: {item_type}"
            icon = QIcon.fromTheme("emblem-important") # Default unknown/error icon
            if item_type == 'vdev':
                 tooltip_text += f"\nVDEV Type: {vdev_type}"
                 if vdev_type == 'disk': icon = QIcon.fromTheme("drive-harddisk")
                 elif vdev_type in ['log', 'cache', 'spare', 'special']: icon = QIcon.fromTheme("drive-removable-media")
                 elif vdev_type != 'unknown': icon = QIcon.fromTheme("drive-multidisk")
            elif item_type == 'device':
                 icon = QIcon.fromTheme("media-floppy")
                 tooltip_text += f"\nPart of VDEV type: {vdev_type}"

            item.setIcon(0, icon)
            item.setToolTip(0, tooltip_text)

            # Set background color based on state
            self._set_item_state_color(item, 1, state, app_palette)

            # Push onto stack if it's a VDEV group that can have children
            # (e.g., mirror, raidz, logs, cache, spares, special)
            # Single disk VDEVs don't get pushed.
            if is_vdev_group or (item_type == 'vdev' and vdev_type != 'disk'):
                 # Check if it *could* have children based on type
                 if vdev_type not in ['disk']: # Only push actual groups
                      parent_stack.append(item)
            # --- *** END FIX *** ---

        # Set final state on the pool item itself
        pool_item.setText(1, pool_state)
        pool_item.setData(0, DEVICE_STATE_ROLE, pool_state)
        self._set_item_state_color(pool_item, 1, pool_state, app_palette)


    def _set_item_state_color(self, item: QTreeWidgetItem, column: int, state: str, palette: QPalette):
        """Sets background color based on device/pool state."""
        state_upper = state.upper() if isinstance(state, str) else "UNKNOWN"
        color = None

        # Define colors (consider making these configurable or theme-aware)
        color_online = palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.Base) # Normal background
        color_degraded = QColor("#FFFACD") # Lemon Chiffon (Yellowish)
        color_faulted = QColor("#FFA07A") # Light Salmon (Reddish)
        color_offline = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button) # Disabled color
        color_resilvering = QColor("#ADD8E6") # Light Blue
        color_scrubbing = QColor("#AFEEEE") # Pale Turquoise

        if state_upper == 'ONLINE':
            color = color_online
        elif state_upper in ['DEGRADED']:
            color = color_degraded
        elif state_upper in ['FAULTED', 'UNAVAIL', 'REMOVED']:
            color = color_faulted
        elif state_upper == 'OFFLINE':
            color = color_offline
        elif 'resilver' in state.lower():
            color = color_resilvering
        elif 'scrub' in state.lower():
            color = color_scrubbing
        # Add more states if needed (e.g., UNAVAIL, REMOVED)

        # Apply color to all columns of the row
        if color is not None:
             for c in range(self.pool_tree.columnCount()):
                 item.setBackground(c, color)
        else:
             # Reset to default if state is unknown or has no specific color
             for c in range(self.pool_tree.columnCount()):
                 item.setBackground(c, color_online)


    def _get_selected_item_data(self) -> Optional[Dict[str, Any]]:
        """Gets data associated with the selected tree item."""
        selected_items = self.pool_tree.selectedItems()
        if not selected_items:
            return None

        item = selected_items[0]
        data = {
            'item': item,
            'item_type': item.data(0, ITEM_TYPE_ROLE),
            'vdev_type': item.data(0, VDEV_TYPE_ROLE),
            'device_path': item.data(0, DEVICE_PATH_ROLE), # Might be None
            'state': item.data(0, DEVICE_STATE_ROLE),
            'text': item.text(0), # The displayed name/path
            'parent_item': item.parent(),
        }
        return data

    @Slot()
    def _update_button_states(self):
        """Enable/disable buttons based on tree selection and pool state."""
        can_add = False
        can_split = False
        can_attach = False
        can_detach = False
        can_replace = False
        can_offline = False
        can_online = False
        can_remove = False

        # Get the top-level pool item AFTER parsing/setting the pool
        pool_item = self.pool_tree.topLevelItem(0) if self.pool_tree.topLevelItemCount() > 0 else None

        if self._current_pool and pool_item: # Ensure pool is loaded and parsed
            pool_state = pool_item.data(0, DEVICE_STATE_ROLE) if pool_item else "UNKNOWN"
            can_add = True # Allow adding VDEVs if pool is loaded

            sel_data = self._get_selected_item_data()
            if sel_data:
                item = sel_data['item']
                item_type = sel_data['item_type']
                vdev_type = sel_data['vdev_type']
                state = sel_data.get('state', 'UNKNOWN')
                parent_item = sel_data['parent_item'] # This is the parent QTreeWidgetItem
                device_path = sel_data['device_path'] # Actual path if identified as device/disk vdev
                item_text = sel_data['text'] # The displayed text

                state_upper = state.upper()

                # Determine parent VDEV type if applicable
                parent_vdev_type = parent_item.data(0, VDEV_TYPE_ROLE) if parent_item else None

                is_device_in_vdev = (item_type == 'device')
                is_disk_vdev = (item_type == 'vdev' and vdev_type == 'disk') # Single disk VDEV

                # Attach: Can attach to a non-mirrored device/disk VDEV if ONLINE
                if (is_device_in_vdev and parent_vdev_type not in ['mirror', 'log', 'cache', 'spare']) or is_disk_vdev:
                    if state_upper == 'ONLINE':
                        can_attach = True

                # Detach: Can detach a device from a mirror if it has siblings and is ONLINE/DEGRADED?
                if is_device_in_vdev and parent_vdev_type == 'mirror':
                    if parent_item and parent_item.childCount() > 1: # Check if more than one device exists in mirror
                       # Allow detach even if offline/faulted? ZFS might allow it. Let's be permissive.
                       can_detach = True

                # Replace: Can replace any identified device/disk VDEV
                if device_path and (is_device_in_vdev or is_disk_vdev):
                    can_replace = True

                # Offline: Can offline an ONLINE device/disk VDEV
                if device_path and (is_device_in_vdev or is_disk_vdev) and state_upper == 'ONLINE':
                    can_offline = True

                # Online: Can online an OFFLINE device/disk VDEV
                if device_path and (is_device_in_vdev or is_disk_vdev) and state_upper == 'OFFLINE':
                    can_online = True

                # --- Remove Button Logic (Using Parent Check) ---
                # Check if the selected item is a VDEV and its parent is the pool item
                is_top_level_vdev = (item_type == 'vdev' and parent_item == pool_item)

                if is_top_level_vdev:
                    # Allow removing log/cache/spare VDEVs anytime
                    if vdev_type in ['log', 'cache', 'spare']:
                        can_remove = True
                    else: # Data VDEV (mirror, raidz, disk)
                        # Count how many *data* vdevs exist directly under the pool
                        data_vdev_count = 0
                        for i in range(pool_item.childCount()):
                            child = pool_item.child(i)
                            # Check if child is a VDEV and not log/cache/spare
                            if child.data(0, ITEM_TYPE_ROLE) == 'vdev' and \
                               child.data(0, VDEV_TYPE_ROLE) not in ['log', 'cache', 'spare']:
                                data_vdev_count += 1
                        # Allow removal only if there's more than one data vdev
                        if data_vdev_count > 1:
                            can_remove = True
                # --- End Remove Button Logic ---

                # Split: Pool must be selected, healthy/degraded, and fully mirrored
                if item_type == 'pool': # and pool_state in ['ONLINE', 'DEGRADED']:
                    is_fully_mirrored = False
                    has_data_vdev = False
                    if pool_item and pool_item.childCount() > 0:
                        is_fully_mirrored = True # Assume true initially
                        for i in range(pool_item.childCount()):
                            top_vdev = pool_item.child(i)
                            # Only check VDEVs directly under the pool
                            if top_vdev.data(0, ITEM_TYPE_ROLE) == 'vdev':
                                top_vdev_type = top_vdev.data(0, VDEV_TYPE_ROLE)
                                # Ignore non-data vdevs for split requirement
                                if top_vdev_type not in ['log', 'cache', 'spare']:
                                    has_data_vdev = True
                                    # Count devices within this top-level VDEV
                                    device_count = 0
                                    for j in range(top_vdev.childCount()):
                                        if top_vdev.child(j).data(0, ITEM_TYPE_ROLE) == 'device':
                                            device_count += 1
                                    # A data VDEV must be a mirror with exactly 2 devices for split
                                    # (ZFS might support >2, but basic split usually targets 2)
                                    # Let's relax to >= 2 devices for now
                                    if top_vdev_type != 'mirror' or device_count < 2:
                                        is_fully_mirrored = False
                                        break # Not fully mirrored
                        if not has_data_vdev: # Need at least one data vdev
                            is_fully_mirrored = False
                    can_split = is_fully_mirrored


        # Set button states
        self.attach_button.setEnabled(can_attach)
        self.detach_button.setEnabled(can_detach)
        self.replace_button.setEnabled(can_replace)
        self.offline_button.setEnabled(can_offline)
        self.online_button.setEnabled(can_online)
        self.add_vdev_button.setEnabled(can_add)
        self.remove_vdev_button.setEnabled(can_remove)
        self.split_button.setEnabled(can_split)


    # --- Action Methods ---

    def _select_device_dialog(self, title: str, message: str) -> Optional[str]:
        """Shows a dialog to select an available block device."""
        try:
            # Use the client instance to list devices
            devices = self.zfs_client.list_block_devices()
        except (ZfsCommandError, ZfsClientCommunicationError, TimeoutError) as e:
            QMessageBox.critical(self, "Error Listing Devices", f"Could not fetch block devices: {e}")
            return None
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Unexpected error listing block devices: {e}")
            return None

        if not devices:
             QMessageBox.information(self, "No Devices", "No available block devices found to use.")
             return None

        # Create mapping from display name to actual path
        device_map = {dev.get('display_name', dev['name']): dev['name'] for dev in devices}
        display_names = sorted(device_map.keys())

        # Use QInputDialog.getItem
        dev_display, ok = QInputDialog.getItem(self, title, message, display_names, 0, False)

        if ok and dev_display:
            return device_map[dev_display] # Return the actual path
        return None # User cancelled or no selection

    @Slot()
    def _attach_device(self):
        if not self._current_pool: return
        sel_data = self._get_selected_item_data()
        if not sel_data: return

        existing_device = sel_data['device_path'] # This should be the actual path now
        if not existing_device:
             # linux-only: '/dev/sdx' is a Linux block device naming convention; other OSes may use different naming
             QMessageBox.warning(self, "Invalid Selection", "Select the specific disk device you want to attach another device to (e.g., /dev/sdx).")
             return

        new_device = self._select_device_dialog("Select Device to Attach",
                                               f"Select the new device to attach as a mirror to:\n'{existing_device}'")
        if new_device:
            reply = QMessageBox.question(self, "Confirm Attach",
                                         f"Attach '{new_device}' as a mirror to '{existing_device}' in pool '{self._current_pool.name}'?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            if reply == QMessageBox.StandardButton.Yes:
                self.status_message.emit(f"Requesting attach {new_device} to {existing_device}...")
                # Emit signal with pool name, existing device path, new device path
                self.attach_device_requested.emit(self._current_pool.name, existing_device, new_device)

    @Slot()
    def _detach_device(self):
        if not self._current_pool: return
        sel_data = self._get_selected_item_data()
        if not sel_data or sel_data['item_type'] != 'device' or not sel_data['parent_item'] or sel_data['parent_item'].data(0, VDEV_TYPE_ROLE) != 'mirror':
            QMessageBox.warning(self, "Invalid Selection", "Select a device within a mirror VDEV to detach.")
            return

        device_to_detach = sel_data['device_path'] # Use the actual path
        if not device_to_detach:
             QMessageBox.warning(self, "Error", "Could not determine the device path to detach.")
             return

        reply = QMessageBox.question(self, "Confirm Detach",
                                     f"Detach device '{device_to_detach}' from its mirror in pool '{self._current_pool.name}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.Yes:
            self.status_message.emit(f"Requesting detach of {device_to_detach}...")
            self.detach_device_requested.emit(self._current_pool.name, device_to_detach)

    @Slot()
    def _replace_device(self):
        # NOTE: Frontend logic appears correct. If action fails, check backend/permissions.
        if not self._current_pool: return
        sel_data = self._get_selected_item_data()
        if not sel_data or not sel_data['device_path']:
            QMessageBox.warning(self, "Invalid Selection", "Select the specific disk device you want to replace.")
            return

        old_device = sel_data['device_path'] # Use the actual path

        # --- Use custom dialog to allow "mark only" ---
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Replacement Device")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"Select the new device to replace:\n'{old_device}'"))
        combo = QComboBox()
        combo.addItem("<Mark for replacement only (no new device)>", "") # Use empty string for 'mark only'
        available_devices = []
        device_map = {}
        try:
            available_devices = self.zfs_client.list_block_devices()
            for dev in available_devices:
                display_name = dev.get('display_name', dev['name'])
                device_map[display_name] = dev['name']
                combo.addItem(display_name, dev['name']) # Store path as data
        except Exception as e:
            QMessageBox.warning(dialog, "Device List Error", f"Could not list available devices: {e}")

        layout.addWidget(combo)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        selected_new_device_path = None # Default to None (cancel)
        if dialog.exec():
            selected_new_device_path = combo.currentData() # Get the stored path or empty string

        # Now selected_new_device_path is either None (cancelled), "" (mark only), or a device path

        if selected_new_device_path is None: # User cancelled dialog
            self.status_message.emit("Replace cancelled.")
            return

        confirm_msg = f"Replace device '{old_device}'"
        if selected_new_device_path: # Path selected
            confirm_msg += f" with '{selected_new_device_path}'"
        else: # Empty string means mark only
            confirm_msg += " (mark for replacement only)"
        confirm_msg += f" in pool '{self._current_pool.name}'?"
        # --- End of modified dialog interaction ---

        reply = QMessageBox.question(self, "Confirm Replace", confirm_msg,
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.Yes:
            self.status_message.emit(f"Requesting replacement for {old_device}...")
            self.replace_device_requested.emit(self._current_pool.name, old_device, selected_new_device_path) # Pass path or ""

    @Slot()
    def _offline_device(self):
        if not self._current_pool: return
        sel_data = self._get_selected_item_data()
        if not sel_data or not sel_data['device_path']:
            QMessageBox.warning(self, "Invalid Selection", "Select the specific disk device to take offline.")
            return

        device = sel_data['device_path'] # Use the actual path

        # Ask if temporary
        reply = QMessageBox.question(self, "Temporary Offline?",
                                     f"Take device '{device}' offline temporarily?\n\n"
                                     "(Temporary means it may automatically come online after reboot.)",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.No) # Default to permanent

        if reply == QMessageBox.StandardButton.Cancel:
            return # User cancelled the temporary question

        temporary = (reply == QMessageBox.StandardButton.Yes)

        # Confirm the action
        confirm_reply = QMessageBox.question(self, "Confirm Offline",
                                             f"Take device '{device}' offline in pool '{self._current_pool.name}'{' (temporarily)' if temporary else ''}?",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)

        if confirm_reply == QMessageBox.StandardButton.Yes:
            self.status_message.emit(f"Requesting offline for {device}...")
            self.offline_device_requested.emit(self._current_pool.name, device, temporary)

    @Slot()
    def _online_device(self):
        if not self._current_pool: return
        sel_data = self._get_selected_item_data()
        if not sel_data or not sel_data['device_path']:
            QMessageBox.warning(self, "Invalid Selection", "Select the specific disk device to bring online.")
            return

        device = sel_data['device_path'] # Use the actual path

        # Check if device is actually offline before asking to expand
        expand = False
        if sel_data.get('state','').upper() == 'OFFLINE':
             expand_reply = QMessageBox.question(self, "Expand Capacity?",
                                              f"Attempt to expand capacity if '{device}' is larger than its original size?",
                                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
             expand = (expand_reply == QMessageBox.StandardButton.Yes)

        # Confirm the action
        reply = QMessageBox.question(self, "Confirm Online",
                                     f"Bring device '{device}' online in pool '{self._current_pool.name}'{' and expand?' if expand else ''}?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)

        if reply == QMessageBox.StandardButton.Yes:
            self.status_message.emit(f"Requesting online for {device}...")
            self.online_device_requested.emit(self._current_pool.name, device, expand)

    @Slot()
    def _add_vdev(self):
        # This uses a very similar dialog structure to CreatePoolDialog
        if not self._current_pool: return

        add_dialog = QDialog(self)
        add_dialog.setWindowTitle(f"Add VDEVs to Pool '{self._current_pool.name}'")
        add_dialog.setMinimumSize(700, 550) # Adjusted size
        main_layout = QVBoxLayout(add_dialog)

        # --- Force Checkbox ---
        add_force_checkbox = QCheckBox("Force (-f)")
        add_force_checkbox.setToolTip("Allow using devices of different sizes (dangerous) or potentially override other checks.")
        main_layout.addWidget(add_force_checkbox, 0, Qt.AlignmentFlag.AlignRight) # Align right

        # --- Splitter ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter, 1) # Give splitter stretch factor

        # --- Left Pane: Available Devices ---
        left_pane_widget = QWidget()
        left_layout = QVBoxLayout(left_pane_widget)
        left_layout.addWidget(QLabel("Available Block Devices:"))
        add_available_list = QListWidget()
        add_available_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        add_available_list.setSortingEnabled(True)
        left_layout.addWidget(add_available_list)
        splitter.addWidget(left_pane_widget)

        # --- Right Pane: VDEVs to Add ---
        right_pane_widget = QWidget()
        right_layout = QVBoxLayout(right_pane_widget)
        right_layout.addWidget(QLabel("VDEVs to Add:"))
        add_vdev_tree = QTreeWidget()
        add_vdev_tree.setColumnCount(2)
        add_vdev_tree.setHeaderLabels(["VDEV / Device", "Size / Type"])
        add_vdev_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = add_vdev_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        right_layout.addWidget(add_vdev_tree)

        # --- Buttons for Right Pane ---
        button_layout = QHBoxLayout()
        add_add_vdev_button = QPushButton(QIcon.fromTheme("list-add"), "Add VDEV Type")
        add_remove_vdev_button = QPushButton(QIcon.fromTheme("list-remove"), "Remove VDEV/Device")
        add_add_device_button = QPushButton(QIcon.fromTheme("go-next"), "Add Device ->")
        button_layout.addWidget(add_add_vdev_button)
        button_layout.addWidget(add_remove_vdev_button)
        button_layout.addStretch()
        button_layout.addWidget(add_add_device_button)
        right_layout.addLayout(button_layout)
        splitter.addWidget(right_pane_widget)
        splitter.setSizes([250, 450])

        # --- Dialog Buttons ---
        dialog_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        dialog_buttons.accepted.connect(add_dialog.accept)
        dialog_buttons.rejected.connect(add_dialog.reject)
        main_layout.addWidget(dialog_buttons)

        # --- Populate Available Devices ---
        add_available_devices_map = {}
        try:
            # NOTE: This uses the same function as the main pool creation dialog.
            # If the list here is wrong, the problem is likely in the shared
            # zfs_manager.list_block_devices() function or the system state.
            devices = self.zfs_client.list_block_devices()
            for dev in devices:
                 add_available_devices_map[dev['name']] = dev
                 item_text = dev.get('display_name', dev['name'])
                 item = QListWidgetItem(item_text)
                 item.setData(Qt.ItemDataRole.UserRole, dev['name']) # Store path
                 item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable) # Ensure selectable
                 add_available_list.addItem(item)
        except Exception as e:
            print(f"Error populating devices for add: {e}")
            error_item = QListWidgetItem("Error listing devices!")
            error_item.setFlags(error_item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
            add_available_list.addItem(error_item)

        # --- Local Helper Functions for the Dialog ---
        local_VDEV_TYPE_ROLE = VDEV_TYPE_ROLE
        local_VDEV_DEVICES_ROLE = VDEV_DEVICES_ROLE
        local_DEVICE_PATH_ROLE = DEVICE_PATH_ROLE

        def _get_min_devs(vtype):
            vtype = vtype.lower()
            if vtype == 'mirror': return 2
            if vtype == 'raidz1': return 3
            if vtype == 'raidz2': return 4
            if vtype == 'raidz3': return 5
            return 1

        def _add_vdev_type_action():
            vdev_types = ['disk', 'mirror', 'raidz1', 'raidz2', 'raidz3', 'log', 'cache', 'spare']
            vdev_type, ok = QInputDialog.getItem(add_dialog, "Add VDEV", "Select VDEV Type:", vdev_types, 0, False)
            if ok and vdev_type:
                vdev_item = QTreeWidgetItem(add_vdev_tree)
                vdev_item.setText(0, f"VDEV ({vdev_type})")
                vdev_item.setText(1, vdev_type.upper())
                vdev_item.setData(0, local_VDEV_TYPE_ROLE, vdev_type)
                vdev_item.setData(0, local_VDEV_DEVICES_ROLE, []) # Store device paths here
                # Set icon based on type
                icon = QIcon.fromTheme("drive-harddisk") # Default
                if vdev_type in ['mirror', 'raidz1', 'raidz2', 'raidz3']:
                    icon = QIcon.fromTheme("drive-multidisk")
                elif vdev_type in ['log', 'cache', 'spare']:
                    icon = QIcon.fromTheme("drive-removable-media")
                vdev_item.setIcon(0, icon)

        add_add_vdev_button.clicked.connect(_add_vdev_type_action)

        def _add_device_action():
            selected_vdevs = add_vdev_tree.selectedItems()
            selected_avail = add_available_list.selectedItems()
            if not selected_vdevs or not selected_avail: return

            target_vdev_item = selected_vdevs[0]
            while target_vdev_item.parent(): target_vdev_item = target_vdev_item.parent()
            if not target_vdev_item.data(0, local_VDEV_TYPE_ROLE): return # Not a valid VDEV item

            current_devices = target_vdev_item.data(0, local_VDEV_DEVICES_ROLE) or []
            moved_count = 0
            for item in selected_avail:
                if not (item.flags() & Qt.ItemIsEnabled): continue # Skip non-enabled items
                dev_path = item.data(Qt.ItemDataRole.UserRole)
                if dev_path and dev_path not in current_devices:
                    current_devices.append(dev_path)
                    dev_info = add_available_devices_map.get(dev_path, {})
                    size_str = utils.format_size(utils.parse_size(dev_info.get('size_str', '0')))
                    label = dev_info.get('label', '')
                    child = QTreeWidgetItem(target_vdev_item)
                    child.setText(0, f"  {dev_path} {label}".strip())
                    child.setText(1, size_str)
                    child.setData(0, local_DEVICE_PATH_ROLE, dev_path)
                    child.setIcon(0, QIcon.fromTheme("media-floppy"))
                    add_available_list.takeItem(add_available_list.row(item))
                    moved_count += 1
            if moved_count > 0:
                 target_vdev_item.setData(0, local_VDEV_DEVICES_ROLE, current_devices)
                 add_vdev_tree.expandItem(target_vdev_item)

        add_add_device_button.clicked.connect(_add_device_action)

        def _return_dev_to_avail(dev_path):
            if dev_path in add_available_devices_map:
                 dev = add_available_devices_map[dev_path]
                 item_text = dev.get('display_name', dev['name'])
                 item = QListWidgetItem(item_text)
                 item.setData(Qt.ItemDataRole.UserRole, dev['name'])
                 item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable) # Ensure selectable
                 add_available_list.addItem(item)
            else:
                 item = QListWidgetItem(dev_path)
                 item.setData(Qt.ItemDataRole.UserRole, dev_path)
                 item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable) # Ensure selectable
                 add_available_list.addItem(item)
            add_available_list.sortItems() # Keep sorted

        def _remove_item_action():
            selected = add_vdev_tree.selectedItems()
            if not selected: return
            item = selected[0]
            parent = item.parent()
            if parent is None: # Removing top-level VDEV
                 for i in range(item.childCount()):
                      child = item.child(i)
                      dev_path = child.data(0, local_DEVICE_PATH_ROLE)
                      if dev_path: _return_dev_to_avail(dev_path)
                 add_vdev_tree.invisibleRootItem().removeChild(item)
            else: # Removing device from VDEV
                dev_path = item.data(0, local_DEVICE_PATH_ROLE)
                current_devices = parent.data(0, local_VDEV_DEVICES_ROLE) or []
                if dev_path in current_devices: current_devices.remove(dev_path)
                parent.setData(0, local_VDEV_DEVICES_ROLE, current_devices)
                parent.removeChild(item)
                if dev_path: _return_dev_to_avail(dev_path)

        add_remove_vdev_button.clicked.connect(_remove_item_action)

        # --- Execute Dialog and Process Result ---
        if add_dialog.exec():
            vdev_specs = []
            root = add_vdev_tree.invisibleRootItem()
            if root.childCount() == 0:
                 QMessageBox.warning(self, "No VDEVs Defined", "No VDEVs were defined in the dialog.")
                 return

            valid_layout = True
            for i in range(root.childCount()):
                vdev_item = root.child(i)
                vdev_type = vdev_item.data(0, local_VDEV_TYPE_ROLE)
                devices = vdev_item.data(0, local_VDEV_DEVICES_ROLE) or []
                min_devs = _get_min_devs(vdev_type)
                if len(devices) < min_devs:
                    QMessageBox.warning(self, "Insufficient Devices",
                                        f"The VDEV '{vdev_item.text(0)}' (type: {vdev_type}) requires {min_devs} device(s), but has {len(devices)}.")
                    valid_layout = False
                    break
                vdev_specs.append({'type': vdev_type, 'devices': devices})

            if not valid_layout: return
            if not vdev_specs:
                QMessageBox.warning(self, "No VDEVs Defined", "No valid VDEVs were defined to add.")
                return

            force_add = add_force_checkbox.isChecked() # Get force state

            self.status_message.emit(f"Requesting to add VDEVs to pool {self._current_pool.name}...")
            # Emit signal with pool name, specs list, and force flag
            self.add_vdev_requested.emit(self._current_pool.name, vdev_specs, force_add)

    @Slot()
    def _remove_vdev(self):
        if not self._current_pool: return
        sel_data = self._get_selected_item_data()
        if not sel_data:
             QMessageBox.warning(self, "Invalid Selection", "Please select an item to remove.")
             return

        # --- Use the same identification logic as _update_button_states (Reverted Parent Check) ---
        item = sel_data['item']
        item_type = sel_data['item_type']
        parent_item = sel_data['parent_item']
        pool_item = self.pool_tree.topLevelItem(0) if self.pool_tree.topLevelItemCount() > 0 else None

        is_top_level_vdev = (item_type == 'vdev' and parent_item == pool_item)
        # --- End Check ---

        if not is_top_level_vdev:
            QMessageBox.warning(self, "Invalid Selection", "Select a top-level VDEV (e.g., mirror-0, raidz1-0, logs, cache, spare, or a single disk entry directly under the pool) to remove.")
            return

        vdev_type = sel_data['vdev_type']
        vdev_id_or_device = sel_data['text'] # Default to displayed text

        if vdev_type in ['log', 'cache', 'spare']:
            device_list = sel_data['item'].data(0, VDEV_DEVICES_ROLE) or []
            if device_list:
                vdev_id_or_device = device_list[0] # Use the first device path for removal
            else:
                QMessageBox.warning(self, "Error", f"Could not find associated devices for VDEV '{sel_data['text']}'. Cannot remove.")
                return
        elif vdev_type == 'disk' and sel_data['device_path']:
            vdev_id_or_device = sel_data['device_path'] # Use actual path for single disk vdevs

        reply = QMessageBox.warning(self, "Confirm Remove",
                                     f"WARNING: Removing VDEVs can be dangerous and may be irreversible or cause data loss, especially for data VDEVs.\n\n"
                                     f"Are you sure you want to attempt to remove '{vdev_id_or_device}' from pool '{self._current_pool.name}'?\n\n"
                                     f"(Check 'zpool remove' documentation for limitations.)",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.status_message.emit(f"Requesting removal of {vdev_id_or_device}...")
            self.remove_vdev_requested.emit(self._current_pool.name, vdev_id_or_device)

    @Slot()
    def _split_pool(self):
        if not self._current_pool: return
        sel_data = self._get_selected_item_data()
        if not sel_data or sel_data['item_type'] != 'pool':
             QMessageBox.warning(self, "Invalid Selection", "Please select the top-level pool item to initiate the split operation.")
             return

        new_pool_name, ok = QInputDialog.getText(self, "Split Pool",
                                                 f"Enter the name for the new pool to be created by splitting:\n'{self._current_pool.name}'\n\n"
                                                 f"(The new pool will contain the second disk of each mirror).",
                                                 QLineEdit.EchoMode.Normal)
        if ok and new_pool_name:
             new_pool_name = new_pool_name.strip()
             if not new_pool_name or new_pool_name == self._current_pool.name:
                  QMessageBox.warning(self, "Invalid Name", "New pool name cannot be empty or the same as the original.")
                  return
             # Simple validation for pool name characters
             if not re.match(r'^[a-zA-Z][a-zA-Z0-9_\-:.%]*$', new_pool_name):
                  QMessageBox.warning(self, "Invalid Name", "New pool name must start with a letter and contain only letters, numbers, or: _ - : . %")
                  return

             reply = QMessageBox.question(self, "Confirm Split",
                                         f"Split pool '{self._current_pool.name}', creating a new pool '{new_pool_name}'?\n"
                                         f"(This detaches the second device of each top-level mirror.)",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
             if reply == QMessageBox.StandardButton.Yes:
                 self.status_message.emit(f"Requesting split of {self._current_pool.name} into {new_pool_name}...")
                 split_options = {} # Add UI for split options if needed later
                 self.split_pool_requested.emit(self._current_pool.name, new_pool_name, split_options)


# --- END OF FILE widgets/pool_editor_widget.py ---
