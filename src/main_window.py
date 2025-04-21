# --- START OF FILE src/main_window.py ---

import sys
import traceback
import re
from typing import Optional, List, Dict, Any

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTreeView, QSplitter,
    QTabWidget, QLabel, QStatusBar, QMessageBox, QToolBar, QSizePolicy,
    QPlainTextEdit, QDialog, QDialogButtonBox, QApplication,
    QHeaderView, QPushButton, QInputDialog, QLineEdit
)
from PySide6.QtGui import QAction, QIcon, QKeySequence, QFont
from PySide6.QtCore import Qt, Slot, QModelIndex, QItemSelection, QMetaObject

# Local imports
try:
    import zfs_manager
    from models import Pool, Dataset, Snapshot, ZfsObject # Uses updated models.py now
    from worker import Worker
    from widgets.zfs_tree_model import ZfsTreeModel
    from widgets.properties_editor import PropertiesEditor
    from widgets.snapshots_widget import SnapshotsWidget
    from widgets.create_pool_dialog import CreatePoolDialog
    from widgets.create_dataset_dialog import CreateDatasetDialog
    from widgets.log_viewer_dialog import LogViewerDialog
    from widgets.pool_editor_widget import PoolEditorWidget
    from widgets.import_pool_dialog import ImportPoolDialog
    from widgets.encryption_widget import EncryptionWidget
    import utils
    import config_manager
    from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError
except ImportError as import_err:
    print(
        f"FATAL: Failed to import necessary modules: {import_err}\n"
        f"{traceback.format_exc()}", file=sys.stderr
    )
    try:
        # Use existing QApplication if available, otherwise create a temporary one
        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(
            None,
            "Import Error",
            f"Failed to load required components:\n{import_err}\n\n"
            "The application cannot start."
        )
    except Exception as e:
        print(f"ERROR: Could not display GUI error message: {e}", file=sys.stderr)
    sys.exit(1)


class MainWindow(QMainWindow):
    APP_NAME = "ZfDash"

    def __init__(self, zfs_client: ZfsManagerClient):
        super().__init__()
        self._worker: Optional[Worker] = None
        self._current_selection: Optional[ZfsObject] = None
        self.zfs_client = zfs_client
        self._action_in_progress = False

        # Tab indices
        self.properties_tab_index = -1
        self.snapshots_tab_index = -1
        self.pool_status_tab_index = -1
        self.pool_editor_tab_index = -1
        self.encryption_tab_index = -1

        self.setWindowTitle(self.APP_NAME)
        self.setGeometry(100, 100, 1200, 800) # Set default size

        # UI elements (initialize to None)
        self.tree_view: Optional[QTreeView] = None
        self.tree_model: Optional[ZfsTreeModel] = None
        self.details_tabs: Optional[QTabWidget] = None
        self.properties_widget: Optional[PropertiesEditor] = None
        self.snapshots_widget: Optional[SnapshotsWidget] = None
        self.pool_status_text: Optional[QPlainTextEdit] = None
        self.pool_editor_widget: Optional[PoolEditorWidget] = None
        self.encryption_widget: Optional[EncryptionWidget] = None
        self.status_bar: Optional[QStatusBar] = None

        # Create UI components
        self._create_actions()
        self._create_menus()
        self._create_toolbars()
        self._create_central_widget()
        self._create_status_bar()
        self._update_action_states() # Initialize action states

        # Schedule initial data refresh after event loop starts
        QMetaObject.invokeMethod(
            self, "refresh_all_data", Qt.ConnectionType.QueuedConnection
        )

    # --- UI Creation Methods ---

    def _create_actions(self):
        """Create QAction objects for menus and toolbars."""
        self.log_viewer_action = QAction(
            QIcon.fromTheme("document-print-preview"), "View &Logs...", self
        )
        self.log_viewer_action.triggered.connect(self._show_log_viewer)

        self.exit_action = QAction(QIcon.fromTheme("application-exit"), "&Exit", self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.exit_action.triggered.connect(self.close)

        self.refresh_action = QAction(QIcon.fromTheme("view-refresh"), "&Refresh", self)
        self.refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.refresh_action.triggered.connect(self.refresh_all_data)

        self.create_pool_action = QAction(
            QIcon.fromTheme("list-add"), "Create &Pool...", self
        )
        self.create_pool_action.triggered.connect(self._create_pool)

        self.destroy_pool_action = QAction(
            QIcon.fromTheme("list-remove"), "&Destroy Pool...", self
        )
        self.destroy_pool_action.triggered.connect(self._destroy_pool)

        self.import_pool_action = QAction(
            QIcon.fromTheme("document-import"), "&Import Pool...", self
        )
        self.import_pool_action.triggered.connect(self._import_pool)

        self.export_pool_action = QAction(
            QIcon.fromTheme("document-export"), "&Export Pool...", self
        )
        self.export_pool_action.triggered.connect(self._export_pool)

        self.scrub_pool_action = QAction(
            QIcon.fromTheme("tools-check-spelling"), "Start S&crub", self
        )
        self.scrub_pool_action.triggered.connect(
            lambda checked=False: self._pool_scrub_action(stop=False)
        )

        self.stop_scrub_action = QAction(
            QIcon.fromTheme("process-stop"), "S&top Scrub", self
        )
        self.stop_scrub_action.triggered.connect(
            lambda checked=False: self._pool_scrub_action(stop=True)
        )

        self.clear_errors_action = QAction(
            QIcon.fromTheme("edit-clear"), "Clear Pool Errors", self
        )
        self.clear_errors_action.triggered.connect(self._clear_pool_errors_action)

        self.create_dataset_action = QAction(
            QIcon.fromTheme("folder-add"), "Create &Dataset/Volume...", self
        )
        self.create_dataset_action.triggered.connect(self._create_dataset)

        self.destroy_dataset_action = QAction(
            QIcon.fromTheme("edit-delete"), "D&estroy Dataset/Volume...", self
        )
        self.destroy_dataset_action.triggered.connect(self._destroy_dataset)

        self.rename_dataset_action = QAction(
            QIcon.fromTheme("edit-rename"), "&Rename Dataset/Volume...", self
        )
        self.rename_dataset_action.triggered.connect(self._rename_dataset)

        mount_icon = QIcon.fromTheme("drive-removable-media", QIcon.fromTheme("mount"))
        self.mount_dataset_action = QAction(mount_icon, "&Mount Dataset", self)
        self.mount_dataset_action.triggered.connect(
            lambda checked=False: self._mount_unmount_dataset(mount=True)
        )

        unmount_icon = QIcon.fromTheme("media-eject", QIcon.fromTheme("unmount"))
        self.unmount_dataset_action = QAction(unmount_icon, "&Unmount Dataset", self)
        self.unmount_dataset_action.triggered.connect(
            lambda checked=False: self._mount_unmount_dataset(mount=False)
        )

        self.promote_dataset_action = QAction(
            QIcon.fromTheme("go-up"), "&Promote Clone", self
        )
        self.promote_dataset_action.triggered.connect(self._promote_dataset)

    def _create_menus(self):
        """Create the main menu bar."""
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.log_viewer_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.refresh_action)

        pool_menu = self.menuBar().addMenu("&Pool")
        pool_menu.addAction(self.create_pool_action)
        pool_menu.addAction(self.destroy_pool_action)
        pool_menu.addSeparator()
        pool_menu.addAction(self.import_pool_action)
        pool_menu.addAction(self.export_pool_action)
        pool_menu.addSeparator()
        pool_menu.addAction(self.scrub_pool_action)
        pool_menu.addAction(self.stop_scrub_action)
        pool_menu.addAction(self.clear_errors_action)

        dataset_menu = self.menuBar().addMenu("&Dataset")
        dataset_menu.addAction(self.create_dataset_action)
        dataset_menu.addAction(self.destroy_dataset_action)
        dataset_menu.addAction(self.rename_dataset_action)
        dataset_menu.addSeparator()
        dataset_menu.addAction(self.mount_dataset_action)
        dataset_menu.addAction(self.unmount_dataset_action)
        dataset_menu.addSeparator()
        dataset_menu.addAction(self.promote_dataset_action)

    def _create_toolbars(self):
        """Create the main application toolbar."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addAction(self.refresh_action)
        toolbar.addSeparator()
        toolbar.addAction(self.create_pool_action)
        toolbar.addAction(self.destroy_pool_action)
        toolbar.addAction(self.import_pool_action)
        toolbar.addAction(self.export_pool_action)
        toolbar.addSeparator()
        toolbar.addAction(self.create_dataset_action)
        toolbar.addAction(self.destroy_dataset_action)
        toolbar.addAction(self.rename_dataset_action)
        toolbar.addSeparator()
        toolbar.addAction(self.mount_dataset_action)
        toolbar.addAction(self.unmount_dataset_action)

    def _create_central_widget(self):
        """Create the main central widget containing the tree view and details tabs."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # --- Left Pane (Tree View) ---
        self.tree_view = QTreeView()
        self.tree_model = ZfsTreeModel(self)
        self.tree_view.setModel(self.tree_model)
        self.tree_view.setHeaderHidden(False)
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.setSortingEnabled(False) # Manual control or model-based sorting
        self.tree_view.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self.tree_view.setAlternatingRowColors(True)
        # Allow tree view to expand horizontally within its splitter pane
        self.tree_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Connect selection model *after* it's guaranteed to exist
        selection_model = self.tree_view.selectionModel()
        if selection_model:
            selection_model.selectionChanged.connect(self._on_tree_selection_changed)

        header = self.tree_view.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive) # Name column (User resizable)
        # Make all columns interactive (user resizable)
        for i in range(1, self.tree_model.columnCount()):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        # Set a larger default width for the Name column
        # Initial resize mode set, width will be adjusted after layout finalized

        splitter.addWidget(self.tree_view)

        # --- Right Pane (Details Tabs) ---
        self.details_tabs = QTabWidget()
        self.details_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Set minimum width for details pane to indirectly limit tree pane expansion
        self.details_tabs.setMinimumWidth(400)

        # Pass zfs_client to child widgets that need it
        self.properties_widget = PropertiesEditor(zfs_client=self.zfs_client)
        self.properties_widget.status_message.connect(self._update_status_bar)
        self.properties_widget.set_property_requested.connect(self._set_property_action)
        self.properties_widget.inherit_property_requested.connect(self._inherit_property_action)
        self.properties_tab_index = self.details_tabs.addTab(
            self.properties_widget, QIcon.fromTheme("document-properties"), "Properties"
        )

        self.snapshots_widget = SnapshotsWidget(zfs_client=self.zfs_client)
        self.snapshots_widget.status_message.connect(self._update_status_bar)
        self.snapshots_widget.create_snapshot_requested.connect(self._create_snapshot_action)
        self.snapshots_widget.delete_snapshot_requested.connect(self._delete_snapshot_action)
        self.snapshots_widget.rollback_snapshot_requested.connect(self._rollback_snapshot_action)
        self.snapshots_widget.clone_snapshot_requested.connect(self._clone_snapshot_action)
        self.snapshots_tab_index = self.details_tabs.addTab(
            self.snapshots_widget, QIcon.fromTheme("camera-photo"), "Snapshots"
        )

        self.pool_status_text = QPlainTextEdit()
        self.pool_status_text.setReadOnly(True)
        monospace_font = QFont("Monospace")
        monospace_font.setStyleHint(QFont.StyleHint.TypeWriter)
        monospace_font.setPointSize(10) # Adjust size as needed
        self.pool_status_text.setFont(monospace_font)
        self.pool_status_tab_index = self.details_tabs.addTab(
            self.pool_status_text, QIcon.fromTheme("dialog-information"), "Pool Status"
        )

        self.pool_editor_widget = PoolEditorWidget(zfs_client=self.zfs_client)
        self.pool_editor_widget.status_message.connect(self._update_status_bar)
        self.pool_editor_widget.attach_device_requested.connect(self._pool_attach_device_action)
        self.pool_editor_widget.detach_device_requested.connect(self._pool_detach_device_action)
        self.pool_editor_widget.replace_device_requested.connect(self._pool_replace_device_action)
        self.pool_editor_widget.offline_device_requested.connect(self._pool_offline_device_action)
        self.pool_editor_widget.online_device_requested.connect(self._pool_online_device_action)
        self.pool_editor_widget.add_vdev_requested.connect(self._pool_add_vdev_action)
        self.pool_editor_widget.remove_vdev_requested.connect(self._pool_remove_vdev_action)
        self.pool_editor_widget.split_pool_requested.connect(self._pool_split_action)
        pool_editor_icon = QIcon.fromTheme("drive-multidisk", QIcon.fromTheme("preferences-system"))
        self.pool_editor_tab_index = self.details_tabs.addTab(
            self.pool_editor_widget, pool_editor_icon, "Edit Pool"
        )

        self.encryption_widget = EncryptionWidget(zfs_client=self.zfs_client)
        self.encryption_widget.status_message.connect(self._update_status_bar)
        self.encryption_widget.load_key_requested.connect(self._load_key_action)
        self.encryption_widget.unload_key_requested.connect(self._unload_key_action)
        self.encryption_widget.change_key_requested.connect(self._change_key_action)
        self.encryption_widget.change_key_location_requested.connect(self._change_key_location_action)
        encryption_icon = QIcon.fromTheme("dialog-password", QIcon.fromTheme("security-high"))
        self.encryption_tab_index = self.details_tabs.addTab(
            self.encryption_widget, encryption_icon, "Encryption"
        )

        # Finalize Splitter
        splitter.addWidget(self.details_tabs)
        initial_width = self.geometry().width()
        # Set initial splitter sizes (e.g., 1/3 for tree, 2/3 for details)
        splitter.setSizes([max(250, initial_width // 3), initial_width * 2 // 3])

        # Initialize details view (empty)
        self._update_details_view(None)

        # Set initial width of Name column to 35% of tree view width
        QMetaObject.invokeMethod(self, "_adjust_initial_name_column_width", Qt.ConnectionType.QueuedConnection)

    def _create_status_bar(self):
        """Create the application status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Initializing...")

    @Slot()
    def _adjust_initial_name_column_width(self):
        """Set the initial width of the Name column based on tree view size."""
        if self.tree_view and self.tree_view.header():
            try:
                tree_width = self.tree_view.viewport().width()
                name_col_width = int(tree_width * 0.35)
                self.tree_view.header().resizeSection(0, name_col_width)
                #print(f"Adjusted initial Name column width to: {name_col_width}") # Debug
            except Exception as e:
                print(f"Warning: Could not adjust initial Name column width: {e}", file=sys.stderr)

    # --- Data Handling and Refresh ---

    def _get_expanded_items(self) -> List[str]:
        """Return a list of paths of currently expanded items in the tree view."""
        expanded_paths = []
        if not self.tree_model or not self.tree_view:
            return expanded_paths

        root_index = self.tree_view.rootIndex() # Get root index for iteration
        for i in range(self.tree_model.rowCount(root_index)):
            index = self.tree_model.index(i, 0, root_index)
            if self.tree_view.isExpanded(index):
                item = self.tree_model.get_zfs_object(index)
                if item:
                    expanded_paths.append(item.name)
                    # Recursively check children
                    self._get_expanded_children(index, expanded_paths)
        return expanded_paths

    def _get_expanded_children(self, parent_index: QModelIndex, expanded_list: List[str]):
        """Recursively find expanded children under a given parent index."""
        if not self.tree_model or not self.tree_view:
            return

        for i in range(self.tree_model.rowCount(parent_index)):
            index = self.tree_model.index(i, 0, parent_index)
            if self.tree_view.isExpanded(index):
                item = self.tree_model.get_zfs_object(index)
                if item:
                    expanded_list.append(item.name)
                    self._get_expanded_children(index, expanded_list)

    def _restore_expanded_items(self, expanded_paths: List[str]):
        """Expand items in the tree view based on a list of paths."""
        if not self.tree_model or not self.tree_view:
            return

        # No need to block signals here, done in the calling function
        for path in expanded_paths:
            index = self.tree_model.find_index_by_path(path)
            if index.isValid():
                self.tree_view.expand(index)

    @Slot()
    def refresh_all_data(self):
        """Initiate a background refresh of all ZFS data."""
        if self._action_in_progress:
            self._update_status_bar("Action in progress, refresh skipped.")
            return
        if self._worker and self._worker.isRunning():
            self._update_status_bar("Refresh already in progress.")
            return
        if not self.tree_view or not self.details_tabs:
            print("WARN: Refresh skipped, UI not fully initialized.")
            return

        self._update_status_bar("Refreshing ZFS data...")
        selected_path = self._current_selection.name if self._current_selection else None
        expanded_paths = self._get_expanded_items()
        current_tab_index = self.details_tabs.currentIndex()

        # Disable UI during refresh
        self.refresh_action.setEnabled(False)
        self.tree_view.setEnabled(False)
        self._update_details_view(None) # Clear details view
        self._update_action_states() # Update disabled states

        self._worker = Worker(self.zfs_client.get_all_zfs_data)
        # Use lambda to ensure arguments are captured correctly at call time
        self._worker.result_ready.connect(
            lambda result, sp=selected_path, ep=expanded_paths, cti=current_tab_index:
                self._handle_refresh_result(result, sp, ep, cti)
        )
        self._worker.error_occurred.connect(self._handle_worker_error)
        self._worker.finished.connect(self._on_refresh_worker_finished)
        self._worker.start()

    @Slot(object, str, list, int)
    def _handle_refresh_result(
        self, pools_data, selected_path, expanded_paths, current_tab_index
    ):
        """Process the data received from the refresh worker."""
        # --- Start of _handle_refresh_result ---
        selection_model = self.tree_view.selectionModel() # Get selection model early
        signals_blocked = False

        # Validate incoming data structure (same as before)
        if not isinstance(pools_data, list):
            # ... (error handling)
            self._finalize_refresh_ui_state()
            return
        if pools_data and not isinstance(pools_data[0], Pool):
            # ... (error handling)
            self._finalize_refresh_ui_state()
            return

        # --- Data seems valid, proceed ---
        self._update_status_bar("Processing ZFS data...")
        try:
            if not self.tree_model or not self.tree_view or not self.details_tabs:
                raise RuntimeError("UI components (tree model/view or tabs) not initialized.")

            # --- Temporarily block signals for bulk update ---
            if selection_model:
                selection_model.blockSignals(True)
                signals_blocked = True

            # 1. Load data into the model (triggers reset)
            self.tree_model.load_data(pools_data)

            # 2. Restore expansion state FIRST
            self._restore_expanded_items(expanded_paths)

            # 3. Find and restore selection
            index_to_select = self.tree_model.find_index_by_path(selected_path) if selected_path else QModelIndex()
            restored_selection_obj = None
            if index_to_select.isValid():
                self.tree_view.setCurrentIndex(index_to_select)
                # Explicitly ensure the selected item is scrolled to and visible
                self.tree_view.scrollTo(index_to_select, QTreeView.ScrollHint.EnsureVisible)
                # --- *********************** ---
                restored_selection_obj = self.tree_model.get_zfs_object(index_to_select)
               # print(f"Refresh: Restored selection to {restored_selection_obj.name}") # Debug
            else:
                self.tree_view.clearSelection()
               # print("Refresh: Selection cleared as previous path not found.") # Debug

            # --- Unblock signals *before* manual state update ---
            # It's generally safer to unblock before triggering further UI updates
            if selection_model and signals_blocked:
                selection_model.blockSignals(False)
                signals_blocked = False # Mark as unblocked

            # --- MODIFIED: Update _current_selection and ALWAYS call _update_details_view that solved the snapshot tab refresh issue--- 
            self._current_selection = restored_selection_obj
            self._update_details_view(self._current_selection)
            # print(f"Refresh: Set _current_selection to {self._current_selection.name if self._current_selection else 'None'} and called _update_details_view") # Debug
            # --- END MODIFICATION ---

            # 5. Restore Tab (same logic as before)
            if 0 <= current_tab_index < self.details_tabs.count() and self.details_tabs.isTabEnabled(current_tab_index):
                self.details_tabs.setCurrentIndex(current_tab_index)
            elif self._current_selection:
                self._switch_to_appropriate_tab(self._current_selection)
            elif self.details_tabs.isTabEnabled(self.properties_tab_index):
                self.details_tabs.setCurrentIndex(self.properties_tab_index)
            else:
                if self.details_tabs.count() > 0: self.details_tabs.setCurrentIndex(0)

            # 6. Resize columns (same as before)
            # Let user adjustments persist.

            self._update_status_bar("Refresh complete.")

        except Exception as e: # Catch potential errors during processing
            print(f"Error processing refresh results: {e}\n{traceback.format_exc()}", file=sys.stderr)
            QMessageBox.critical(
                self, "Processing Error", f"Failed to process ZFS data after refresh:\n{e}"
            )
            self._update_status_bar("Error processing refresh data.")
        finally:
            # Ensure signals are unblocked if an error occurred mid-process
            if selection_model and signals_blocked:
                selection_model.blockSignals(False)

        # --- Always re-enable UI ---
        self._finalize_refresh_ui_state()


    def _finalize_refresh_ui_state(self):
        """Re-enables UI elements after refresh attempt (success or failure)."""
        self.refresh_action.setEnabled(True)
        if self.tree_view:
            self.tree_view.setEnabled(True)
        # Crucially, update action states based on the *final* selection state
        self._update_action_states()

    @Slot()
    def _on_refresh_worker_finished(self):
        """Called when the refresh worker thread finishes."""
        print("Refresh worker finished.")
        self._worker = None
        # UI state finalized in _handle_refresh_result or _handle_worker_error via _finalize_refresh_ui_state

    # --- UI Update Methods ---

    @Slot(str)
    def _update_status_bar(self, message: str):
        """Display a message in the status bar."""
        if self.status_bar:
            self.status_bar.showMessage(message, 5000) # Show for 5 seconds

    @Slot(QItemSelection, QItemSelection)
    def _on_tree_selection_changed(self, selected: QItemSelection, deselected: QItemSelection):
        """Update the details view when the tree selection changes."""
        selected_object: Optional[ZfsObject] = None
        indexes = selected.indexes()

        # Get the object from the first column of the selected row
        if indexes and self.tree_model:
            selected_object = self.tree_model.get_zfs_object(indexes[0])

        # Avoid redundant updates if the same object is re-selected
        # This check uses the corrected __eq__ from models.py
        if selected_object == self._current_selection:
            # print(f"Selection changed signal ignored, object is the same: {selected_object.name if selected_object else 'None'}") # Debug
            return

        #print(f"Selection changed to: {selected_object.name if selected_object else 'None'}") # Debug print
        self._current_selection = selected_object
        self._update_details_view(selected_object)
        self._update_action_states()

    def _update_details_view(self, selected_object: Optional[ZfsObject]):
        """Update the content and enabled state of the details tabs."""
        if not all([self.details_tabs, self.properties_widget, self.snapshots_widget,
                    self.pool_status_text, self.pool_editor_widget, self.encryption_widget]):
            print("Warning: Details view update skipped, widgets not ready.")
            return

        is_pool = isinstance(selected_object, Pool)
        is_dataset_or_vol = isinstance(selected_object, Dataset)
        is_encrypted_dataset = is_dataset_or_vol and getattr(selected_object, 'is_encrypted', False)

        # --- Enable/disable tabs based on selection type ---
        self.details_tabs.setTabEnabled(
            self.properties_tab_index, selected_object is not None
        )
        self.details_tabs.setTabEnabled(
            self.snapshots_tab_index, is_dataset_or_vol
        )
        self.details_tabs.setTabEnabled(
            self.pool_status_tab_index, is_pool
        )
        self.details_tabs.setTabEnabled(
            self.pool_editor_tab_index, is_pool
        )
        self.details_tabs.setTabEnabled(
            self.encryption_tab_index, is_encrypted_dataset
        )

        # --- Update content of each widget ---
        self.properties_widget.set_object(selected_object)
        self.snapshots_widget.set_dataset(selected_object if is_dataset_or_vol else None)
        pool_status = getattr(selected_object, 'status_details', '') if is_pool else ""
        self.pool_status_text.setPlainText(pool_status)
        self.pool_editor_widget.set_pool(selected_object if is_pool else None)
        self.encryption_widget.set_dataset(selected_object if is_encrypted_dataset else None)

        # --- Switch tab if current one becomes disabled ---
        current_index = self.details_tabs.currentIndex()
        if not self.details_tabs.isTabEnabled(current_index):
            # Only switch if the current tab *becomes* invalid due to the *new* selection
            self._switch_to_appropriate_tab(selected_object)

    def _switch_to_appropriate_tab(self, selected_object: Optional[ZfsObject]):
        """Switches to the most relevant enabled tab based on the selected object type."""
        if not self.details_tabs: return

        is_pool = isinstance(selected_object, Pool)
        is_dataset_or_vol = isinstance(selected_object, Dataset)
        is_encrypted_dataset = is_dataset_or_vol and getattr(selected_object, 'is_encrypted', False)

        # Check tabs in preferred order and if they are currently enabled
        if is_encrypted_dataset and self.details_tabs.isTabEnabled(self.encryption_tab_index):
            self.details_tabs.setCurrentIndex(self.encryption_tab_index)
        elif is_pool and self.details_tabs.isTabEnabled(self.pool_editor_tab_index): # Prioritize editor for pools?
            self.details_tabs.setCurrentIndex(self.pool_editor_tab_index)
        elif is_pool and self.details_tabs.isTabEnabled(self.pool_status_tab_index):
            self.details_tabs.setCurrentIndex(self.pool_status_tab_index)
        elif is_dataset_or_vol and self.details_tabs.isTabEnabled(self.snapshots_tab_index):
            self.details_tabs.setCurrentIndex(self.snapshots_tab_index)
        elif self.details_tabs.isTabEnabled(self.properties_tab_index):
            self.details_tabs.setCurrentIndex(self.properties_tab_index)
        else:
             # Fallback if somehow no primary tab is enabled (e.g., index 0)
             if self.details_tabs.count() > 0:
                 self.details_tabs.setCurrentIndex(0)


    def _update_action_states(self):
        """Enable/disable actions based on the current selection and application state."""
        sel = self._current_selection
        is_pool = isinstance(sel, Pool)
        is_dataset = isinstance(sel, Dataset) and sel.obj_type == 'dataset'
        is_volume = isinstance(sel, Dataset) and sel.obj_type == 'volume'
        is_filesystem = is_dataset or is_volume # Includes both datasets and volumes
        is_clone = is_filesystem and getattr(sel, 'properties', {}).get('origin', '-') not in ['-', '', None]
        is_mounted = is_dataset and getattr(sel, 'is_mounted', False) # Only datasets can be mounted

        # Check if any background task is running
        can_run_action = not self._action_in_progress and (
            self._worker is None or not self._worker.isRunning()
        )

        # General Actions
        self.create_pool_action.setEnabled(can_run_action)
        self.import_pool_action.setEnabled(can_run_action)
        self.refresh_action.setEnabled(can_run_action)
        self.log_viewer_action.setEnabled(True) # Always enabled

        # Pool Actions
        self.destroy_pool_action.setEnabled(is_pool and can_run_action)
        self.export_pool_action.setEnabled(is_pool and can_run_action)
        self.clear_errors_action.setEnabled(is_pool and can_run_action)

        scrub_running = False
        # Determine scrub/resilver state *only* from pool status details (zpool status output)
        if is_pool and hasattr(sel, 'status_details') and sel.status_details:
            status_lower = sel.status_details.lower()
            # Look for specific phrases indicating an *active* scan is running.
            # These phrases should be specific enough not to match finished/cancelled states.
            # Examples: "scrub in progress since...", "resilver in progress since..."
            # Avoid overly broad matches like "scan: scrub" which might appear in finished messages.
            if 'scrub in progress' in status_lower:
                scrub_running = True
            elif 'resilver in progress' in status_lower:
                scrub_running = True
            # Add other specific "in progress" phrases if needed for different zpool versions,
            # ensuring they don't match completed states like "scrub repaired..."

        # Enable Start Scrub only if a pool is selected, no scrub is *actively* running,
        # and no other general action is running.
        self.scrub_pool_action.setEnabled(is_pool and not scrub_running and can_run_action)
        # Enable Stop Scrub only if a pool is selected, a scrub *is* actively running,
        # and no other general action is running.
        self.stop_scrub_action.setEnabled(is_pool and scrub_running and can_run_action)

        # Dataset/Volume Actions
        self.create_dataset_action.setEnabled((is_pool or is_filesystem) and can_run_action)
        self.destroy_dataset_action.setEnabled(is_filesystem and can_run_action)
        self.rename_dataset_action.setEnabled(is_filesystem and can_run_action)
        self.mount_dataset_action.setEnabled(is_dataset and not is_mounted and can_run_action)
        self.unmount_dataset_action.setEnabled(is_dataset and is_mounted and can_run_action)
        self.promote_dataset_action.setEnabled(is_clone and can_run_action)

        # Update button states within detail widgets if they exist and have the method
        if self.pool_editor_widget and hasattr(self.pool_editor_widget, '_update_button_states'):
            self.pool_editor_widget._update_button_states()
        if self.snapshots_widget and hasattr(self.snapshots_widget, '_update_button_states'):
            self.snapshots_widget._update_button_states()
        if self.encryption_widget and hasattr(self.encryption_widget, '_update_ui'): # Encryption uses _update_ui
            # Update encryption widget based on its *own* current dataset, which should match _current_selection if relevant
            self.encryption_widget._update_ui(self.encryption_widget._current_dataset)


    # --- Action Handling (Worker Threads) ---

    def _run_worker_task(self, task_func, *args, op_name: str = "ZFS Operation", **kwargs):
        """Generic helper to run a background task using Worker."""
        if self._action_in_progress:
            self._update_status_bar(f"Action already in progress, '{op_name}' skipped.")
            return
        if not self.tree_view or not self.details_tabs:
            print(f"WARN: '{op_name}' skipped, UI not fully initialized.")
            return

        self._action_in_progress = True
        self._update_status_bar(f"Starting {op_name}...")
        # Disable UI elements
        self.refresh_action.setEnabled(False)
        self.tree_view.setEnabled(False)
        self.details_tabs.setEnabled(False)
        self._update_action_states() # Update actions based on disabled state

        # Create and connect worker
        self._worker = Worker(task_func, *args, **kwargs)

        # --- CORRECTED Signal Connections --- #
        self._worker.result_ready.connect(self._handle_action_result)
        self._worker.error_occurred.connect(self._handle_worker_error)
        self._worker.finished.connect(self._on_action_worker_finished)
        # ------------------------------------ #

        self._worker.start()

    @Slot(object)
    def _handle_action_result(self, result):
        """Handle the result from a successful action worker."""
        success = False
        msg = "Operation completed."

        if isinstance(result, tuple) and len(result) >= 2 and isinstance(result[0], bool):
            success = result[0]
            msg = str(result[1]) if result[1] is not None else "Operation completed successfully."
            if not success:
                 QMessageBox.critical(self, "Action Failed", msg)
                 self._on_action_worker_finished()
                 return
        else:
            print(f"Warning: Unexpected result format from worker: {result!r}", file=sys.stderr)
            msg = f"Action finished (unexpected result format)"
            success = True

        self._update_status_bar(f"Success: {msg}")
        QMetaObject.invokeMethod(self, "refresh_all_data", Qt.ConnectionType.QueuedConnection)
        # _on_action_worker_finished called by worker signal

    @Slot(str, str)
    def _handle_worker_error(self, error_message: str, details: str):
        """Handle errors reported by any background worker."""
        print(f"Worker Error: {error_message}\nDetails:\n{details}", file=sys.stderr)
        self._update_status_bar(f"Error: {error_message}")

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle("Operation Error")

        final_error_message = f"An error occurred during the background operation:\n{error_message}"
        details_short = ""

        if "unmount" in error_message.lower() and "no such pool or dataset" in details:
            final_error_message = (
                f"Failed to unmount: {error_message}\n\n"
                "This often indicates an inconsistent state, possibly due to an interrupted "
                "operation involving a child dataset.\n\n"
                "Troubleshooting Steps:\n"
                "1. Try `Refresh All Data`.\n"
                "2. Check system mounts (`mount | grep <dataset>`). Try `sudo umount -l <mountpoint>`.\n"
                "3. Try forcefully destroying the problematic child dataset mentioned in the error (if safe).\n"
                "4. Try exporting and re-importing the entire pool (`zpool export/import <poolname>`).\n\n"
                "See details for the raw error."
            )
            details_short = details
        elif details:
             details_str = str(details)
             max_len = 2000
             details_short = details_str[:max_len] + ("\n\n...(truncated)" if len(details_str) > max_len else "")

        msg_box.setText(final_error_message)
        if details_short:
             msg_box.setInformativeText("Click 'Show Details...' for the full error trace.")
             msg_box.setDetailedText(details_short)

        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

        self._on_action_worker_finished() # Ensure UI re-enabled

    @Slot()
    def _on_action_worker_finished(self):
        """Called when an action worker finishes (after success or error handling)."""
        print("Action worker finished.")
        # Check if the window is still valid before enabling/updating
        if self:
            self._action_in_progress = False

            # Explicitly re-enable controls disabled in _run_worker_task
            self.refresh_action.setEnabled(True)
            if self.tree_view:
                self.tree_view.setEnabled(True)
            if self.details_tabs:
                self.details_tabs.setEnabled(True)

            # Update action states based on the now-finished action and current selection
            self._update_action_states()
        self._worker = None


    # --- Specific Action Slots (No changes from previous version needed here) ---

    @Slot()
    def _create_pool(self):
        dialog = CreatePoolDialog(zfs_client=self.zfs_client, parent=self)
        if dialog.exec():
            pool_name, vdev_specs, force = dialog.get_pool_details()
            if pool_name and vdev_specs:
                self._run_worker_task(
                    self.zfs_client.execute_generic_action,
                    "create_pool", f"Pool '{pool_name}' created successfully.",
                    pool_name, vdev_specs, force=force,
                    op_name=f"Creating Pool {pool_name}"
                )

    @Slot()
    def _destroy_pool(self):
        if not isinstance(self._current_selection, Pool): return
        pool_name = self._current_selection.name
        reply = QMessageBox.critical(self, "Confirm Pool Destruction", f"DANGER ZONE!\n\nAre you absolutely sure you want to permanently destroy the pool '{pool_name}' and ALL data within it?\n\nTHIS ACTION CANNOT BE UNDONE.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            self._run_worker_task(
                self.zfs_client.execute_generic_action,
                "destroy_pool", f"Pool '{pool_name}' destroyed successfully.", pool_name, force=True,
                op_name=f"Destroying Pool {pool_name}"
            )

    @Slot()
    def _import_pool(self):
        if self._action_in_progress or (self._worker and self._worker.isRunning()): return
        self.setEnabled(False); self._update_status_bar("Searching for importable pools...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # Use the client instance to list pools
            success, msg, importable_pools = self.zfs_client.list_importable_pools()
        except (ZfsCommandError, ZfsClientCommunicationError, TimeoutError) as e:
            QApplication.restoreOverrideCursor(); self.setEnabled(True); self._update_status_bar(f"Error listing pools: {e}"); QMessageBox.critical(self, "Error Listing Pools", f"{e}\n\nDetails:\n{getattr(e, 'details', '')}"); return
        except Exception as e:
            QApplication.restoreOverrideCursor(); self.setEnabled(True); self._update_status_bar(f"Unexpected error listing pools: {e}"); QMessageBox.critical(self, "Error", f"An unexpected error occurred: {e}\n{traceback.format_exc()}"); return
        finally: # Ensure cursor/enabled restored
            QApplication.restoreOverrideCursor()
            if not self.isEnabled(): self.setEnabled(True); self._update_action_states()

        self._update_status_bar(msg if success else f"Error: {msg}")
        if not success: QMessageBox.critical(self, "Error Listing Pools", msg); return
        if not importable_pools: QMessageBox.information(self, "Import Pool", "No importable ZFS pools found."); return

        dialog = ImportPoolDialog(importable_pools, zfs_client=self.zfs_client, parent=self)
        if dialog.exec():
             import_details = dialog.get_import_details()
             if import_details:
                  pool_id_or_name = import_details.get("pool_id_or_name")
                  new_name = import_details.get("new_name")
                  force = import_details.get("force", False)
                  search_dirs = import_details.get("search_dirs") # Might be None
                  import_all = import_details.get("import_all", False)

                  if import_all:
                      self._run_worker_task(
                           self.zfs_client.execute_generic_action,
                           "import_pool", "All available pools imported.", search_dirs=search_dirs, force=force,
                           op_name="Importing All Pools"
                      )
                  elif pool_id_or_name:
                       self._run_worker_task(
                           self.zfs_client.execute_generic_action,
                           "import_pool", f"Pool '{pool_id_or_name}' imported.", pool_id_or_name, new_name=new_name, force=force,
                           op_name=f"Importing Pool {pool_id_or_name}"
                       )
                  # else: No pool selected/specified

    @Slot()
    def _export_pool(self):
        if not isinstance(self._current_selection, Pool): return
        pool_name = self._current_selection.name; force_export = False
        reply = QMessageBox.question(self, "Force Export?", f"Force export pool '{pool_name}'?\n(Use Force only if datasets are busy/mounted, may cause issues).", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Cancel: return
        elif reply == QMessageBox.StandardButton.Yes: force_export = True
        confirm_reply = QMessageBox.question(self, "Confirm Export", f"Export pool '{pool_name}'{' forcefully' if force_export else ''}?\n(Makes pool inactive until imported again)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if confirm_reply == QMessageBox.StandardButton.Yes:
            self._run_worker_task(
                self.zfs_client.execute_generic_action,
                "export_pool", f"Pool '{pool_name}' exported successfully.", pool_name, force=force_export,
                op_name=f"Exporting Pool {pool_name}"
            )

    @Slot(bool)
    def _pool_scrub_action(self, stop: bool):
        if not isinstance(self._current_selection, Pool):
            return
        pool_name = self._current_selection.name
        command_name = "scrub_pool"
        action_desc = "stopped" if stop else "started"
        op_name = "Stop Scrub" if stop else "Start Scrub"
        success_msg = f"Scrub {action_desc} for pool '{pool_name}'."

        self._run_worker_task(
            self.zfs_client.execute_generic_action,
            command_name,       # Command name is always "scrub_pool"
            success_msg,
            op_name=op_name,
            # Pass arguments required by the core scrub_pool function:
            pool_name=pool_name,
            stop=stop           # Pass the boolean flag as a keyword arg
        )

    @Slot()
    def _clear_pool_errors_action(self):
        if not isinstance(self._current_selection, Pool): return
        pool_name = self._current_selection.name
        reply = QMessageBox.question(self, "Confirm Clear Errors", f"Clear persistent error counts for pool '{pool_name}'?\n(Does not fix underlying hardware issues)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._run_worker_task(
                self.zfs_client.execute_generic_action,
                "clear_pool_errors", f"Errors cleared for pool '{pool_name}'.", pool_name,
                op_name=f"Clearing Errors for {pool_name}"
            )

    @Slot()
    def _create_dataset(self):
        if not self._current_selection or not isinstance(self._current_selection, (Pool, Dataset)):
            QMessageBox.warning(self, "Selection Error", "Please select a pool or dataset first.")
            return

        dialog = CreateDatasetDialog(self._current_selection.name, self.zfs_client, parent=self)
        if dialog.exec():
            # Unpack the 4 values returned by the dialog
            dialog_result = dialog.get_dataset_details()
            if dialog_result is None:
                # Dialog internally handled validation error and returned None
                self.status_message.emit("Dataset creation cancelled or validation failed.")
                return

            full_name, type_str, properties, encryption_options = dialog_result

            # Prepare the arguments for the zfs_manager command
            # Assuming the daemon handler for 'create_dataset' expects kwargs like:
            # full_dataset_name, dataset_type, properties, encryption_options
            create_kwargs = {
                'full_dataset_name': full_name,
                'dataset_type': type_str,
                'properties': properties,
                'encryption_options': encryption_options
            }

            # Use the generic action executor
            self._run_worker_task(
                self.zfs_client.execute_generic_action,
                command="create_dataset",
                success_msg=f"{type_str.capitalize()} '{full_name}' created successfully",
                # Pass arguments via kwargs dictionary
                **create_kwargs,
                # Pass op_name for status message
                op_name=f"Create {type_str.capitalize()} {full_name}"
            )

    @Slot()
    def _destroy_dataset(self):
        if not isinstance(self._current_selection, Dataset): return
        ds_obj = self._current_selection; ds_name = ds_obj.name; ds_type = ds_obj.obj_type
        children = getattr(ds_obj, 'children', [])
        snapshots = getattr(ds_obj, 'snapshots', [])
        has_children = bool(children or snapshots)
        recursive = False; confirm_needed = True

        if has_children:
             msg_box = QMessageBox(self); msg_box.setIcon(QMessageBox.Icon.Warning); msg_box.setWindowTitle(f"Confirm {ds_type.capitalize()} Destruction")
             msg_box.setText(f"Destroy '{ds_name}'?\nWARNING: This {ds_type} contains children (snapshots and/or nested items).\nHow do you want to proceed?")
             destroy_button = msg_box.addButton("Destroy Only This Item", QMessageBox.ButtonRole.ActionRole)
             destroy_recursive_button = msg_box.addButton("Destroy Recursively (incl. children)", QMessageBox.ButtonRole.DestructiveRole)
             cancel_button = msg_box.addButton(QMessageBox.StandardButton.Cancel); msg_box.setDefaultButton(cancel_button); msg_box.exec()
             clicked_button = msg_box.clickedButton()
             if clicked_button == cancel_button: confirm_needed = False
             elif clicked_button == destroy_recursive_button: recursive = True
             elif clicked_button == destroy_button: recursive = False
             else: confirm_needed = False
        else:
            reply = QMessageBox.warning(self, f"Confirm {ds_type.capitalize()} Destruction", f"Are you sure you want to destroy the {ds_type} '{ds_name}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No: confirm_needed = False

        if confirm_needed:
            recursive_str = 'Recursive ' if recursive else ''
            op_name = f"{recursive_str}Destroy {ds_type.capitalize()} '{ds_name}'"
            success_msg = f"{ds_type.capitalize()} '{ds_name}' destroyed successfully."
            self._run_worker_task(
                self.zfs_client.execute_generic_action,
                "destroy_dataset", success_msg, ds_name, recursive=recursive,
                op_name=op_name
            )

    @Slot()
    def _rename_dataset(self):
        if not isinstance(self._current_selection, Dataset): return
        old_name = self._current_selection.name; type_str = self._current_selection.obj_type.capitalize()
        new_name_part, ok = QInputDialog.getText(self, f"Rename {type_str}", f"Enter the new full path for:\n'{old_name}'\n\nExample: pool/data/new_name", QLineEdit.EchoMode.Normal, old_name)
        if not ok or not new_name_part: return
        new_name = new_name_part.strip();
        if new_name == old_name: return
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_\-:.%/]*$', new_name) or new_name.endswith('/'): QMessageBox.warning(self, "Invalid Name", "The new name contains invalid characters or format."); return
        if '/' not in new_name: QMessageBox.warning(self, "Invalid Name", "The new name must be a full path including the pool name."); return
        recursive = False
        if getattr(self._current_selection, 'snapshots', []):
            reply = QMessageBox.question(self, "Rename Snapshots?", f"Rename all snapshots under '{old_name}' as well? (Recursive rename)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            recursive = (reply == QMessageBox.StandardButton.Yes)
        force = False
        reply_force = QMessageBox.question(self, "Force Unmount?", f"Force unmount '{old_name}' if it is currently busy? (Use with caution)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        force = (reply_force == QMessageBox.StandardButton.Yes)
        recursive_msg = '(Including snapshots)' if recursive else '(Dataset/Volume only)'; force_msg = '(Forcing unmount if needed)' if force else ''
        confirm_reply = QMessageBox.question(self, f"Confirm Rename {type_str}", f"Rename '{old_name}' to '{new_name}'?\n{recursive_msg}\n{force_msg}", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
        if confirm_reply == QMessageBox.StandardButton.Yes:
            op_name = f"Rename {type_str} '{old_name}' to '{new_name}'"
            success_msg = f"{type_str} '{old_name}' renamed to '{new_name}' successfully."
            self._run_worker_task(
                self.zfs_client.execute_generic_action,
                "rename_dataset", success_msg, old_name, new_name, recursive=recursive, force_unmount=force,
                op_name=op_name
            )

    @Slot(bool)
    def _mount_unmount_dataset(self, mount: bool):
        if not isinstance(self._current_selection, Dataset) or self._current_selection.obj_type != 'dataset': return
        ds_name = self._current_selection.name; action_name = "Mount" if mount else "Unmount"
        command_name = "mount_dataset" if mount else "unmount_dataset"
        success_msg = f"Dataset '{ds_name}' {action_name.lower()}ed successfully."
        if mount and getattr(self._current_selection, 'is_encrypted', False):
            key_status = getattr(self._current_selection, 'properties', {}).get('keystatus')
            if key_status != 'available':
                 QMessageBox.warning(self, "Key Unavailable", f"Cannot mount '{ds_name}'.\nEncryption key is unavailable (status: {key_status}). Please load the key first."); return
        self._run_worker_task(
            self.zfs_client.execute_generic_action,
            command_name, success_msg, ds_name,
            op_name=f"{action_name} Dataset {ds_name}"
        )

    @Slot()
    def _promote_dataset(self):
        if not isinstance(self._current_selection, Dataset): return
        ds_name = self._current_selection.name
        origin = getattr(self._current_selection, 'properties', {}).get('origin', '-')
        if origin in ['-', '', None]: QMessageBox.information(self, "Not a Clone", f"'{ds_name}' is not a cloned dataset and cannot be promoted."); return
        reply = QMessageBox.question(self, "Confirm Promotion", f"Promote cloned dataset '{ds_name}'?\n(This makes it independent of its origin snapshot)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._run_worker_task(
                self.zfs_client.execute_generic_action,
                "promote_dataset", f"Dataset '{ds_name}' promoted successfully.", ds_name,
                op_name=f"Promoting Clone {ds_name}"
            )

    # --- Slots from detail widgets ---

    @Slot(str, str, str)
    def _set_property_action(self, obj_name: str, prop_name: str, prop_value: str):
        self._run_worker_task(
            self.zfs_client.execute_generic_action,
            "set_dataset_property", f"Property '{prop_name}' set on '{obj_name}'.", obj_name, prop_name, prop_value,
            op_name=f"Setting {prop_name} on {obj_name}"
        )

    @Slot(str, str)
    def _inherit_property_action(self, obj_name: str, prop_name: str):
        self._run_worker_task(
            self.zfs_client.execute_generic_action,
            "inherit_dataset_property", f"Property '{prop_name}' inherited on '{obj_name}'.", obj_name, prop_name,
            op_name=f"Inheriting {prop_name} on {obj_name}"
        )

    @Slot(str, str, bool)
    def _create_snapshot_action(self, dataset_name: str, snap_name: str, recursive: bool):
        self._run_worker_task(
            self.zfs_client.execute_generic_action,
            "create_snapshot", f"Snapshot '{snap_name}' created for '{dataset_name}'.", dataset_name, snap_name, recursive=recursive,
            op_name=f"Creating Snapshot {dataset_name}@{snap_name}"
        )

    @Slot(str)
    def _delete_snapshot_action(self, full_snapshot_name: str):
        reply = QMessageBox.warning(self, "Confirm Deletion", f"Are you sure you want to permanently delete snapshot:\n{full_snapshot_name}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._run_worker_task(
                self.zfs_client.execute_generic_action,
                "destroy_snapshot", f"Snapshot '{full_snapshot_name}' deleted.", full_snapshot_name, recursive=True,
                op_name=f"Deleting Snapshot {full_snapshot_name}"
            )

    @Slot(str)
    def _rollback_snapshot_action(self, full_snapshot_name: str):
        reply = QMessageBox.critical(self, "Confirm Rollback", f"DANGER: Rolling back to snapshot '{full_snapshot_name}' will destroy all data written to the dataset since this snapshot, including later snapshots.\n\nAre you absolutely sure?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            self._run_worker_task(
                self.zfs_client.execute_generic_action,
                "rollback_snapshot", f"Rolled back to snapshot '{full_snapshot_name}'.", full_snapshot_name,
                op_name=f"Rolling back to {full_snapshot_name}"
            )

    @Slot(str, str, dict)
    def _clone_snapshot_action(self, full_snapshot_name: str, target_dataset_name: str, options: Dict[str, str]):
        self._run_worker_task(
            self.zfs_client.execute_generic_action,
            "clone_snapshot", f"Cloned '{full_snapshot_name}' to '{target_dataset_name}'.", full_snapshot_name, target_dataset_name, properties=options,
            op_name=f"Cloning {full_snapshot_name}"
        )

    # --- Pool Editor Actions ---
    @Slot(str, str, str)
    def _pool_attach_device_action(self, pool_name: str, existing_dev: str, new_dev: str):
        self._run_worker_task(
            self.zfs_client.execute_generic_action, "attach_device",
            f"Device {new_dev} attached to {existing_dev} in pool {pool_name}",
            pool_name, existing_dev, new_dev, op_name=f"Attaching device to {pool_name}"
        )

    @Slot(str, str)
    def _pool_detach_device_action(self, pool_name: str, device: str):
        self._run_worker_task(
            self.zfs_client.execute_generic_action, "detach_device",
            f"Device {device} detached from pool {pool_name}",
            pool_name, device, op_name=f"Detaching {device} from {pool_name}"
        )

    @Slot(str, str, str)
    def _pool_replace_device_action(self, pool_name: str, old_dev: str, new_dev: Optional[str]):
         self._run_worker_task(
             self.zfs_client.execute_generic_action, "replace_device",
             f"Device {old_dev} replaced {(f'with {new_dev}' if new_dev else '')} in pool {pool_name}",
             pool_name, old_dev, new_dev, op_name=f"Replacing {old_dev} in {pool_name}"
         )

    @Slot(str, str, bool)
    def _pool_offline_device_action(self, pool_name: str, device: str, temporary: bool):
        self._run_worker_task(
            self.zfs_client.execute_generic_action, "offline_device",
            f"Device {device} taken offline in pool {pool_name}",
            pool_name, device, temporary=temporary, op_name=f"Offlining {device} in {pool_name}"
        )

    @Slot(str, str, bool)
    def _pool_online_device_action(self, pool_name: str, device: str, expand: bool):
        self._run_worker_task(
            self.zfs_client.execute_generic_action, "online_device",
            f"Device {device} brought online in pool {pool_name}",
            pool_name, device, expand=expand, op_name=f"Onlining {device} in {pool_name}"
        )

    @Slot(str, list, bool)
    def _pool_add_vdev_action(self, pool_name: str, vdev_specs: List[Dict[str, Any]], force: bool):
        self._run_worker_task(
            self.zfs_client.execute_generic_action, "add_vdev",
            f"Vdev added to pool {pool_name}",
            pool_name, vdev_specs, force=force, op_name=f"Adding Vdev to {pool_name}"
        )

    @Slot(str, str)
    def _pool_remove_vdev_action(self, pool_name: str, device_or_vdev_id: str):
        self._run_worker_task(
            self.zfs_client.execute_generic_action, "remove_vdev",
            f"Device/Vdev {device_or_vdev_id} removed from pool {pool_name}",
            pool_name, device_or_vdev_id, op_name=f"Removing {device_or_vdev_id} from {pool_name}"
        )

    @Slot(str, str, dict)
    def _pool_split_action(self, old_pool_name: str, new_pool_name: str, options: Dict[str, Any]):
        self._run_worker_task(
            self.zfs_client.execute_generic_action, "split_pool",
            f"Pool {old_pool_name} split into {new_pool_name}",
            old_pool_name, new_pool_name, options=options, op_name=f"Splitting {old_pool_name}"
        )

    # --- Encryption Actions ---
    @Slot(str, bool, str, str)
    def _load_key_action(self, dataset_name: str, recursive: bool, key_location: Optional[str], passphrase: Optional[str]):
        self._run_worker_task(
            self.zfs_client.execute_generic_action, "load_key",
            f"Key loaded for {dataset_name}",
            dataset_name, recursive=recursive, keylocation=key_location, passphrase=bool(passphrase),
            op_name=f"Loading key for {dataset_name}"
        )

    @Slot(str, bool)
    def _unload_key_action(self, dataset_name: str, recursive: bool):
         self._run_worker_task(
             self.zfs_client.execute_generic_action, "unload_key",
             f"Key unloaded for {dataset_name}",
             dataset_name, recursive=recursive, op_name=f"Unloading key for {dataset_name}"
         )

    @Slot(str, bool, bool, dict, str)
    def _change_key_action(self, dataset_name: str, load_key: bool, recursive: bool, options: Dict[str, Any], change_info: Optional[str]):
         self._run_worker_task(
             self.zfs_client.execute_generic_action, "change_key",
             f"Key changed for {dataset_name}",
             dataset_name, load_key=load_key, recursive=recursive, options=options, change_info=change_info,
             op_name=f"Changing key for {dataset_name}"
         )

    @Slot(str, str)
    def _change_key_location_action(self, dataset_name: str, new_location: str):
        # This now calls the updated _set_property_action which uses execute_generic_action
        self._set_property_action(dataset_name, "keylocation", new_location)

    # --- Misc Actions ---
    @Slot()
    def _show_log_viewer(self):
        dialog = LogViewerDialog(self); dialog.exec()

    # --- Window Closing Logic ---

    def _execute_stop_daemon(self) -> bool:
        """Sends the stop command to the daemon via the ZFS client."""
        try:
            print("Attempting to send shutdown command to daemon via client...")
            # Use the client's shutdown method
            success, msg = self.zfs_client.shutdown_daemon()
            if success:
                print(f"Daemon shutdown command sent successfully: {msg}")
                return True
            else:
                print(f"Failed to send daemon shutdown command: {msg}")
                return False
        except Exception as e:
            print(f"Error sending shutdown command via ZFS client: {e}")
            return False

    def closeEvent(self, event):
        """Handle the window close event."""
        worker_active = False
        if self._worker is not None:
            try: worker_active = self._worker.isRunning()
            except RuntimeError: worker_active = False

        if worker_active or self._action_in_progress:
             reply = QMessageBox.question(self, "Operation in Progress", "A background operation is running.\nAborting might leave the system inconsistent.\n\nAbort and exit?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
             if reply == QMessageBox.StandardButton.No: event.ignore(); return
             else: print("WARN: Aborting running worker on exit (may not stop immediately).")

        # Ask about stopping daemon
        msg_box = QMessageBox(self); msg_box.setWindowTitle(f"Quit {self.APP_NAME}?"); msg_box.setText(f"Do you want to stop the {self.APP_NAME} background process (daemon)?")
        msg_box.setInformativeText("The Daemon Process will stop automatically if you quit!")
        msg_box.setIcon(QMessageBox.Icon.Question)
        stop_daemon_button = msg_box.addButton("Stop Daemon and Quit", QMessageBox.ButtonRole.AcceptRole)
        #keep_daemon_button = msg_box.addButton("Quit Only (Leave Daemon Running)", QMessageBox.ButtonRole.DestructiveRole) #not needed anymore
        cancel_button = msg_box.addButton(QMessageBox.StandardButton.Cancel); msg_box.setDefaultButton(cancel_button)
        msg_box.exec()
        clicked_button = msg_box.clickedButton()

        if clicked_button == stop_daemon_button:
            print("User chose to stop daemon and quit."); self._execute_stop_daemon(); event.accept()
        #elif clicked_button == keep_daemon_button:
        #    print("User chose to quit GUI only."); event.accept()
        else:
            print("User cancelled quit operation."); event.ignore()

# --- END OF FILE src/main_window.py ---
