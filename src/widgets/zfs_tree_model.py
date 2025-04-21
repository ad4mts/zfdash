# --- START OF FILE zfs_tree_model.py ---

from typing import Optional, List # Added List
from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QIcon, QColor, QBrush, QPalette
from PySide6.QtWidgets import QApplication

import utils # Import the whole module
import os
from models import Pool, Dataset, Snapshot, ZfsObject


# Icon paths (not implemented for now)
ICON_DIR = os.path.join(os.path.dirname(__file__), '..', 'icons') #not the right way of finding icons (look at gui_runner.py *dynamically*)
ICON_POOL = QIcon.fromTheme("drive-harddisk", QIcon(os.path.join(ICON_DIR, "pool.png")))
ICON_DATASET = QIcon.fromTheme("folder", QIcon(os.path.join(ICON_DIR, "dataset.png")))
ICON_VOLUME = QIcon.fromTheme("drive-optical", QIcon(os.path.join(ICON_DIR, "dataset.png")))
ICON_SNAPSHOT = QIcon.fromTheme("camera-photo", QIcon(os.path.join(ICON_DIR, "snapshot.png")))
ICON_ENCRYPTED = QIcon.fromTheme("dialog-password", QIcon())
ICON_MOUNTED = QIcon.fromTheme("emblem-mounted", QIcon())


class ZfsTreeModel(QAbstractItemModel):
    """
    A model for displaying ZFS pools, datasets, and snapshots in a QTreeView.
    """
    COLUMNS = ["Name", "Used", "Avail/Referenced", "Mountpoint/Creation", "Type"]
    refresh_needed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_items: list[Pool] = []

    def load_data(self, root_items: list[Pool]):
        self.beginResetModel()
        self._root_items = root_items if root_items else []
        self.endResetModel()

    def clear(self):
        self.load_data([])

    # --- QAbstractItemModel Implementation ---

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            # Root level: Pools
            return len(self._root_items)
        else:
            parent_item = parent.internalPointer()
            if isinstance(parent_item, Pool):
                # Children of Pool are Datasets
                return len(parent_item.children)
            elif isinstance(parent_item, Dataset):
                 # Children of Dataset are sub-Datasets and Snapshots
                 return len(parent_item.children) + len(parent_item.snapshots) # Show both
            # Snapshots have no children in the tree model
            return 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        if not index.isValid():
            return None

        item = index.internalPointer()
        column = index.column()
        app_instance = QApplication.instance()
        app_palette = app_instance.palette() if app_instance else None

        # Display Role
        if role == Qt.DisplayRole:
            if isinstance(item, Pool):
                if column == 0: return item.name
                if column == 1: return utils.format_size(item.alloc)
                if column == 2: return utils.format_size(item.free)
                if column == 3: return f"{item.cap} ({item.frag} frag)"
                if column == 4: return item.health.capitalize()
            elif isinstance(item, Dataset):
                # Display only the last part of the name for datasets
                if column == 0: return item.name.split('/')[-1]
                if column == 1: return utils.format_size(item.used)
                if column == 2: return utils.format_size(item.available)
                if column == 3: return item.mountpoint
                if column == 4: return item.obj_type.capitalize()
            elif isinstance(item, Snapshot):
               # Display snapshot name prefixed with @
               if column == 0: return f"@{item.name}"
               if column == 1: return utils.format_size(item.used)
               if column == 2: return utils.format_size(item.referenced)
               if column == 3: return item.creation_time
               if column == 4: return item.obj_type.capitalize()

        # Decoration Role
        elif role == Qt.DecorationRole and column == 0:
            if isinstance(item, Pool): return ICON_POOL
            elif isinstance(item, Dataset):
                icon = ICON_VOLUME if item.obj_type == 'volume' else ICON_DATASET
                # Optionally add overlay icons for mounted/encrypted
                # This requires more complex icon handling (e.g., QIcon.paint) or specific theme icons
                # if item.is_mounted: pass # Add overlay?
                # if item.is_encrypted: pass # Add overlay?
                return icon
            elif isinstance(item, Snapshot): return ICON_SNAPSHOT

        # Tooltip Role
        elif role == Qt.ToolTipRole:
            if isinstance(item, Pool):
                return f"Pool: {item.name}\nHealth: {item.health}\nSize: {utils.format_size(item.size)}\nAllocated: {utils.format_size(item.alloc)} ({item.cap})\nFree: {utils.format_size(item.free)}\nFragmentation: {item.frag}"
            elif isinstance(item, Dataset):
                tooltip = f"{item.obj_type.capitalize()}: {item.name}\n" \
                          f"Used: {utils.format_size(item.used)}\n" \
                          f"Available: {utils.format_size(item.available)}\n" \
                          f"Referenced: {utils.format_size(item.referenced)}\n" \
                          f"Mountpoint: {item.mountpoint}\n" \
                          f"Mounted: {'Yes' if item.is_mounted else 'No'}\n" \
                          f"Encrypted: {'Yes' if item.is_encrypted else 'No'}\n" \
                          f"Compression: {item.properties.get('compression', 'N/A')}"
                return tooltip
            elif isinstance(item, Snapshot):
                 # Use full snapshot name (property if available, else construct)
                 full_name = item.properties.get('full_snapshot_name', f"{item.dataset_name}@{item.name}")
                 tooltip = f"Snapshot: {full_name}\n" \
                          f"Used: {utils.format_size(item.used)}\n" \
                          f"Referenced: {utils.format_size(item.referenced)}\n" \
                          f"Created: {item.creation_time}"
                 return tooltip

        # Background Color Role
        elif role == Qt.BackgroundRole:
             if isinstance(item, Pool) and column == 4: # Health column for Pool
                 health = item.health.upper()
                 if health == 'ONLINE': return QBrush(QColor(Qt.darkGreen).lighter(180))
                 elif health in ['DEGRADED', 'FAULTED', 'UNAVAIL', 'REMOVED']: return QBrush(QColor(Qt.red).lighter(180))
                 elif health == 'OFFLINE': return QBrush(QColor(Qt.gray))
             # Optionally add background for snapshots if needed
             pass

        # Foreground Color Role (Example: Gray out snapshots)
        elif role == Qt.ForegroundRole:
            if isinstance(item, Snapshot):
                 # Make snapshots slightly grayed out to distinguish them
                 if app_palette:
                     disabled_text_color = app_palette.color(QPalette.ColorRole.PlaceholderText) # Use PlaceholderText for less stark gray
                     return QBrush(disabled_text_color)
                 else:
                     return QBrush(QColor(Qt.gray))

        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> object:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]
        return None

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        parent_item = None
        if not parent.isValid():
            # Root level, parent_item is None, children are pools
            if row < len(self._root_items):
                child_item = self._root_items[row]
                return self.createIndex(row, column, child_item)
        else:
            # Child level, get parent object
            parent_item = parent.internalPointer()
            if isinstance(parent_item, Pool):
                if row < len(parent_item.children):
                    child_item = parent_item.children[row]
                    return self.createIndex(row, column, child_item)
            elif isinstance(parent_item, Dataset):
                 num_children = len(parent_item.children)
                 if row < num_children:
                     # It's a child dataset
                     child_item = parent_item.children[row]
                     return self.createIndex(row, column, child_item)
                 elif row < num_children + len(parent_item.snapshots):
                     # It's a snapshot (index adjusted)
                     snapshot_index = row - num_children
                     child_item = parent_item.snapshots[snapshot_index]
                     return self.createIndex(row, column, child_item)

        return QModelIndex()


    def parent(self, child_index: QModelIndex) -> QModelIndex:
        if not child_index.isValid():
            return QModelIndex()

        child_item: Optional[ZfsObject] = child_index.internalPointer()
        if child_item is None:
            return QModelIndex()

        parent_item: Optional[ZfsObject] = child_item.parent

        if parent_item is None:
            # Child is a Pool, parent is the root
            return QModelIndex()

        # We have the parent_item (Pool or Dataset). Now find its row within its parent (the grandparent).
        grandparent_item: Optional[ZfsObject] = parent_item.parent
        siblings = []
        if grandparent_item is None:
            # Parent is a Pool, so its siblings are the root items (other pools)
            siblings = self._root_items
        elif isinstance(grandparent_item, Pool):
            # Parent is a root Dataset, its siblings are the children of the grandparent Pool
            siblings = grandparent_item.children
        elif isinstance(grandparent_item, Dataset):
            # Parent is a nested Dataset, its siblings are the children of the grandparent Dataset
            siblings = grandparent_item.children
        # Snapshots cannot be parents in this model, so we don't need to check grandparent_item being a Snapshot.

        try:
            # Find the row index of the parent_item within its determined sibling list
            parent_row = siblings.index(parent_item)
            return self.createIndex(parent_row, 0, parent_item)
        except ValueError:
            print(f"ERROR: ZfsTreeModel.parent() could not find parent '{parent_item.name}' (type: {type(parent_item)}) in its supposed sibling list.")
            return QModelIndex()


    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        # All items are enabled and selectable
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def get_zfs_object(self, index: QModelIndex) -> Optional[ZfsObject]:
        """Retrieves the internal ZfsObject associated with a model index."""
        if index.isValid():
            return index.internalPointer()
        return None

    # --- NEW Method ---
    def find_index_by_path(self, path: str, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        """Recursively searches for an item with the given full name/path."""
        rows = self.rowCount(parent)
        for row in range(rows):
            index = self.index(row, 0, parent)
            if not index.isValid(): continue # Skip invalid indexes

            item = self.get_zfs_object(index)
            if not item: continue # Skip if object retrieval fails

            current_item_path = None
            if isinstance(item, (Pool, Dataset)):
                current_item_path = item.name
            elif isinstance(item, Snapshot):
                # Use the full snapshot name property if available
                current_item_path = item.properties.get('full_snapshot_name')
                if not current_item_path:
                    # Fallback if property missing (shouldn't happen with current hierarchy builder)
                    current_item_path = f"{item.dataset_name}@{item.name}"

            # Check if the current item IS the one we're looking for
            if current_item_path == path:
                return index

            # Recursively search children if the current item can have children in the tree
            # (Pools have datasets, Datasets have datasets/snapshots)
            # No need to check if it's a Snapshot, as they have no children in the tree.
            if isinstance(item, (Pool, Dataset)):
                # Only recurse if the path *could* be under the current item
                # Basic check: path starts with current item's path + '/' (for datasets)
                # This avoids searching unrelated branches.
                needs_recursion = False
                if isinstance(item, Pool) and path.startswith(f"{item.name}/"):
                     needs_recursion = True
                elif isinstance(item, Dataset) and path.startswith(f"{item.name}/") or path.startswith(f"{item.name}@"):
                     needs_recursion = True

                if needs_recursion:
                    found_index = self.find_index_by_path(path, index) # Recurse using current item's index as parent
                    if found_index.isValid():
                        return found_index

        return QModelIndex() # Not found in this branch

# --- END OF FILE zfs_tree_model.py ---
