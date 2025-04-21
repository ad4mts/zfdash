# --- START OF FILE snapshots_widget.py ---

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QPushButton, QHBoxLayout, QMessageBox, QInputDialog, QLineEdit, QLabel,
    QSpacerItem, QSizePolicy, QApplication,
    QHeaderView # Import QHeaderView
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QIcon # Import QIcon

from typing import Optional, Dict, Any # Added Dict, Any
import re # Import re

# Import client class
from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError
from models import Dataset, Snapshot
# --- CORRECTED Import ---
import utils # Import the whole module

class SnapshotsWidget(QWidget):
    """Widget to display and manage snapshots for a Dataset."""
    # --- Signals for Actions ---
    create_snapshot_requested = Signal(str, str, bool) # dataset_name, snap_name, recursive
    delete_snapshot_requested = Signal(str) # full_snapshot_name
    rollback_snapshot_requested = Signal(str) # full_snapshot_name
    clone_snapshot_requested = Signal(str, str, dict) # full_snapshot_name, target_dataset_name, options

    # Existing signals
    status_message = Signal(str)
    # snapshots_changed signal is good - MainWindow will trigger refresh after successful action
    snapshots_changed = Signal() # Keep this, maybe rename to refresh_requested? No, keep as is.

    def __init__(self, zfs_client: ZfsManagerClient, parent=None):
        super().__init__(parent)
        self._current_dataset: Optional[Dataset] = None
        # Store the client instance
        self.zfs_client = zfs_client
        if self.zfs_client is None:
            raise ValueError("ZfsManagerClient instance is required for SnapshotsWidget.")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0) # Use standard margins unless specific reason

        # Toolbar
        toolbar_layout = QHBoxLayout()
        self.create_snap_button = QPushButton(QIcon.fromTheme("list-add"), " Create Snapshot")
        self.create_snap_button.setToolTip("Create a new snapshot for the selected dataset")
        self.create_snap_button.clicked.connect(self._create_snapshot)
        self.create_snap_button.setEnabled(False)

        self.delete_snap_button = QPushButton(QIcon.fromTheme("list-remove"), " Delete Snapshot")
        self.delete_snap_button.setToolTip("Delete the selected snapshot")
        self.delete_snap_button.clicked.connect(self._delete_snapshot)
        self.delete_snap_button.setEnabled(False)

        self.rollback_button = QPushButton(QIcon.fromTheme("view-refresh", QIcon.fromTheme("go-previous")), " Rollback")
        self.rollback_button.setToolTip("Rollback the dataset to the selected snapshot (DANGEROUS!)")
        self.rollback_button.clicked.connect(self._rollback_snapshot)
        self.rollback_button.setEnabled(False)

        self.clone_button = QPushButton(QIcon.fromTheme("edit-copy"), " Clone")
        self.clone_button.setToolTip("Clone the selected snapshot into a new dataset/volume")
        self.clone_button.clicked.connect(self._clone_snapshot)
        self.clone_button.setEnabled(False)

        toolbar_layout.addWidget(self.create_snap_button)
        toolbar_layout.addWidget(self.delete_snap_button)
        toolbar_layout.addWidget(self.rollback_button)
        toolbar_layout.addWidget(self.clone_button)
        toolbar_layout.addStretch()
        layout.addLayout(toolbar_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Name", "Used", "Referenced", "Created"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows) # Use enum member
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection) # Use enum member
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers) # Use enum member
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(False) # Disable manual sorting for now

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        self.table.itemSelectionChanged.connect(self._update_button_states)
        layout.addWidget(self.table)
        self.setLayout(layout) # Set layout on the widget itself


    def set_dataset(self, dataset: Optional[Dataset]):
        """Displays snapshots for the given Dataset."""
        self._current_dataset = dataset
        self.table.setRowCount(0) # Clear table efficiently
        self.create_snap_button.setEnabled(dataset is not None)
        self._update_button_states() # Update based on selection (which is now none)

        if not dataset or not dataset.snapshots:
            return # Nothing more to do

        # Sort snapshots by creation time (using property which should hold original string)
        # ZFS creation times are usually sortable as strings (like YYYY-MM-DD-HHMM)
        try:
            snapshots = sorted(dataset.snapshots, key=lambda s: s.properties.get('creation', ''))
        except Exception as e:
            print(f"Warning: Could not sort snapshots by creation time: {e}")
            snapshots = dataset.snapshots # Use unsorted list if sorting fails

        self.table.setRowCount(len(snapshots))

        for row, snap in enumerate(snapshots):
            # Retrieve the full snapshot name stored during parsing
            full_snap_name = snap.properties.get('full_snapshot_name', f"{snap.dataset_name}@{snap.name}")

            # Column 0: Name (display only @name)
            name_item = QTableWidgetItem(f"@{snap.name}")
            # Store the *full snapshot name* in UserRole for easy retrieval
            name_item.setData(Qt.ItemDataRole.UserRole, full_snap_name)
            name_item.setToolTip(full_snap_name)

            # Column 1: Used
            used_item = QTableWidgetItem(utils.format_size(snap.used))
            used_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            # Column 2: Referenced
            ref_item = QTableWidgetItem(utils.format_size(snap.referenced))
            ref_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            # Column 3: Creation Time
            created_item = QTableWidgetItem(snap.creation_time) # Already a string

            # Set items in table
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, used_item)
            self.table.setItem(row, 2, ref_item)
            self.table.setItem(row, 3, created_item)

        # --- ADDED: Force visual update of the table --- 
        self.table.viewport().update()
        # --- END ADDED ---


    @Slot()
    def _update_button_states(self):
        """Enable/disable buttons based on table selection and dataset presence."""
        selected_rows = self.table.selectionModel().selectedRows()
        has_single_selection = len(selected_rows) == 1

        # Create is enabled only if a dataset is loaded
        self.create_snap_button.setEnabled(self._current_dataset is not None)

        # Other actions require a single snapshot row to be selected
        self.delete_snap_button.setEnabled(has_single_selection)
        self.rollback_button.setEnabled(has_single_selection)
        self.clone_button.setEnabled(has_single_selection)

    def _get_selected_snapshot_name(self) -> Optional[str]:
        """Gets the full name (dataset@snap) of the selected snapshot from UserRole data."""
        selected_indexes = self.table.selectionModel().selectedIndexes()
        if selected_indexes:
            # Get the item from the first column of the selected row
            first_col_index = selected_indexes[0].siblingAtColumn(0)
            item = self.table.item(first_col_index.row(), first_col_index.column())
            if item:
                # Retrieve the full name stored in UserRole
                return item.data(Qt.ItemDataRole.UserRole)
        return None

    @Slot()
    def _create_snapshot(self):
        """Handles the 'Create Snapshot' button click by emitting a signal."""
        if not self._current_dataset:
            QMessageBox.warning(self, "No Dataset Selected", "Please select a dataset or volume in the main tree first.")
            return

        dataset_name = self._current_dataset.name
        snap_name_part, ok = QInputDialog.getText(self, "Create Snapshot",
                                             f"Enter name for snapshot of:\n'{dataset_name}'\n\n"
                                             f"(Result: {dataset_name}@<name>)\n"
                                             "Avoid: @ / space",
                                             QLineEdit.EchoMode.Normal) # Use enum member

        if not ok: return # User cancelled
        if not snap_name_part:
             QMessageBox.warning(self, "Invalid Name", "Snapshot name cannot be empty.")
             return

        snap_name_part = snap_name_part.strip()
        # Validate name characters (allow alphanumeric, underscore, hyphen, colon, dot, percent)
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_\-:.%]*$', snap_name_part):
             QMessageBox.warning(self, "Invalid Name", "Snapshot name contains invalid characters or starts incorrectly.\nAllowed: A-Z a-z 0-9 _ - : . %")
             return
        if '@' in snap_name_part or '/' in snap_name_part or ' ' in snap_name_part:
             QMessageBox.warning(self, "Invalid Name", "Snapshot name cannot contain '@', '/', or spaces.")
             return

        recursive = False
        # Check if the current dataset has child datasets (not just snapshots)
        has_child_datasets = any(isinstance(child, Dataset) for child in self._current_dataset.children)
        if has_child_datasets:
             reply = QMessageBox.question(self, "Recursive Snapshot?",
                                             f"Create snapshots recursively for all child datasets under '{dataset_name}'?",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, # Use enum members
                                             QMessageBox.StandardButton.No)
             recursive = (reply == QMessageBox.StandardButton.Yes)

        self.status_message.emit(f"Requesting snapshot '{snap_name_part}'...")
        # --- EMIT SIGNAL ---
        self.create_snapshot_requested.emit(dataset_name, snap_name_part, recursive)


    @Slot()
    def _delete_snapshot(self):
        """Handles the 'Delete Snapshot' button click by emitting a signal."""
        selected_snap_name = self._get_selected_snapshot_name()
        if not selected_snap_name:
            QMessageBox.warning(self, "No Snapshot Selected", "Please select a snapshot to delete.")
            return

        reply = QMessageBox.warning(self, "Confirm Deletion",
                                     f"Are you sure you want to permanently delete the snapshot:\n{selected_snap_name}?\n\n"
                                     "This action cannot be undone. Cloned filesystems dependent on this snapshot may also be affected or destroyed.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, # Use enum members
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.status_message.emit(f"Requesting deletion of '{selected_snap_name}'...")
            # --- EMIT SIGNAL ---
            self.delete_snapshot_requested.emit(selected_snap_name)

    @Slot()
    def _rollback_snapshot(self):
        """Handles the 'Rollback' button click by emitting a signal."""
        selected_snap_name = self._get_selected_snapshot_name()
        if not selected_snap_name:
            QMessageBox.warning(self, "No Snapshot Selected", "Please select a snapshot to roll back to.")
            return

        dataset_name = selected_snap_name.split('@')[0]
        reply = QMessageBox.critical(self, "Confirm Rollback", # Use Critical icon for danger
                                     f"DANGER ZONE!\n\nAre you sure you want to roll back dataset '{dataset_name}' to the state of snapshot:\n{selected_snap_name}?\n\n"
                                     "This will DESTROY ALL CHANGES made to the dataset since the snapshot was created, including any intermediate snapshots.\n"
                                     "The dataset may need to be unmounted first.\n\n"
                                     "THIS ACTION CANNOT BE UNDONE.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, # Use Yes/Cancel
                                     QMessageBox.StandardButton.Cancel) # Default to Cancel

        if reply == QMessageBox.StandardButton.Yes:
            self.status_message.emit(f"Requesting rollback to '{selected_snap_name}'...")
            # --- EMIT SIGNAL ---
            self.rollback_snapshot_requested.emit(selected_snap_name)

    @Slot()
    def _clone_snapshot(self):
        """Handles the 'Clone' button click by emitting a signal."""
        selected_snap_name = self._get_selected_snapshot_name()
        if not selected_snap_name:
            QMessageBox.warning(self, "Selection Required", "Please select a snapshot in the table.")
            return

        source_dataset_name = selected_snap_name.split('@')[0]
        pool_name = source_dataset_name.split('/')[0]
        # Suggest a reasonable default clone name
        default_clone_name_suggestion = f"{source_dataset_name}-clone"
        # Ensure suggestion is valid if source is pool itself (rare)
        if '/' not in default_clone_name_suggestion:
             default_clone_name_suggestion = f"{pool_name}/clone"


        target_name, ok = QInputDialog.getText(self, "Clone Snapshot",
                                               f"Enter the name for the new dataset/volume to be created from snapshot:\n{selected_snap_name}\n\n"
                                               f"(Must be a full ZFS path, e.g., {pool_name}/myclone)",
                                               QLineEdit.EchoMode.Normal,
                                               default_clone_name_suggestion) # Suggest a default

        if not ok: return # User cancelled
        if not target_name:
             QMessageBox.warning(self, "Invalid Name", "Target name cannot be empty.")
             return

        target_name = target_name.strip()
        # Basic validation for the target name path
        if '/' not in target_name or target_name.startswith('/') or target_name.endswith('/'):
             QMessageBox.warning(self, "Invalid Name", f"Target name must be a full ZFS path within a pool (e.g., {pool_name}/myclone) and cannot start/end with '/'.")
             return
        if target_name == source_dataset_name:
              QMessageBox.warning(self, "Invalid Name", "Target name cannot be the same as the source dataset.")
              return
        # Allow standard ZFS dataset characters
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_\-:.%/]*$', target_name):
             QMessageBox.warning(self, "Invalid Name", "Target name contains invalid characters or starts/ends incorrectly.")
             return

        # TODO: Add dialog for clone options if needed later
        clone_options = {}

        self.status_message.emit(f"Requesting clone of '{selected_snap_name}' to '{target_name}'...")
        # --- EMIT SIGNAL ---
        self.clone_snapshot_requested.emit(selected_snap_name, target_name, clone_options)

# --- END OF FILE snapshots_widget.py ---
