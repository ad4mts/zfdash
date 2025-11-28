# --- START OF FILE src/widgets/dashboard_widget.py ---

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout,
    QScrollArea, QSizePolicy, QProgressBar, QGroupBox, QSpacerItem
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QFont, QPalette, QColor

from typing import Optional, Dict, Any, List
import platform
import os
import sys

from models import Pool, Dataset, Snapshot, ZfsObject
import utils


class UsageBar(QWidget):
    """A styled progress bar showing storage usage with percentage and values."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(6)
        
        # Header with label and percentage
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        self.label = QLabel("Storage")
        self.label.setStyleSheet("font-weight: 600; color: #333; font-size: 13px;")
        header_layout.addWidget(self.label)
        
        header_layout.addStretch()
        
        self.percentage_label = QLabel("0%")
        self.percentage_label.setStyleSheet("font-weight: 700; color: #333; font-size: 14px;")
        header_layout.addWidget(self.percentage_label)
        
        layout.addLayout(header_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMinimumHeight(26)
        self._base_bar_style = """
            QProgressBar {{
                border: 2px solid #a8b0bc;
                border-radius: 13px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e8ecf0, stop:0.5 #d8dce0, stop:1 #e8ecf0);
                padding: 2px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, {gradient});
                border-radius: 9px;
            }}
        """
        self.progress_bar.setStyleSheet(self._base_bar_style.format(gradient="stop:0 #81C784, stop:0.5 #4CAF50, stop:1 #388E3C"))
        layout.addWidget(self.progress_bar)
        
        # Details row
        details_layout = QHBoxLayout()
        details_layout.setContentsMargins(0, 4, 0, 0)
        
        self.used_label = QLabel("Used: 0B")
        self.used_label.setStyleSheet("color: #666; font-size: 12px;")
        details_layout.addWidget(self.used_label)
        
        details_layout.addStretch()
        
        self.free_label = QLabel("Free: 0B")
        self.free_label.setStyleSheet("color: #666; font-size: 12px;")
        details_layout.addWidget(self.free_label)
        
        details_layout.addStretch()
        
        self.total_label = QLabel("Total: 0B")
        self.total_label.setStyleSheet("color: #666; font-size: 11px;")
        details_layout.addWidget(self.total_label)
        
        layout.addLayout(details_layout)
        
    def set_values(self, used: int, total: int, label: str = "Storage"):
        """Set the usage values and update the display."""
        self.label.setText(label)
        
        if total <= 0:
            self.progress_bar.setValue(0)
            self.percentage_label.setText("0%")
            self.used_label.setText("Used: -")
            self.free_label.setText("Free: -")
            self.total_label.setText("Total: -")
            return
            
        percentage = min(100, int((used / total) * 100))
        free = max(0, total - used)
        
        self.progress_bar.setValue(percentage)
        self.percentage_label.setText(f"{percentage}%")
        self.used_label.setText(f"Used: {utils.format_size(used)}")
        self.free_label.setText(f"Free: {utils.format_size(free)}")
        self.total_label.setText(f"Total: {utils.format_size(total)}")
        
        # Color coding with gradients based on usage (vertical gradient: light top, dark bottom)
        if percentage >= 90:
            gradient = "stop:0 #ef5350, stop:0.5 #f44336, stop:1 #c62828"  # Red gradient
            self.percentage_label.setStyleSheet("font-weight: 700; color: #e53935; font-size: 14px;")
        elif percentage >= 75:
            gradient = "stop:0 #ffb74d, stop:0.5 #ff9800, stop:1 #e65100"  # Orange gradient
            self.percentage_label.setStyleSheet("font-weight: 700; color: #f57c00; font-size: 14px;")
        elif percentage >= 50:
            gradient = "stop:0 #64B5F6, stop:0.5 #2196F3, stop:1 #1565C0"  # Blue gradient
            self.percentage_label.setStyleSheet("font-weight: 700; color: #1976D2; font-size: 14px;")
        else:
            gradient = "stop:0 #81C784, stop:0.5 #4CAF50, stop:1 #2E7D32"  # Green gradient
            self.percentage_label.setStyleSheet("font-weight: 700; color: #388E3C; font-size: 14px;")
            
        self.progress_bar.setStyleSheet(self._base_bar_style.format(gradient=gradient))


class InfoCard(QFrame):
    """A styled card widget for displaying key-value information."""
    
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setStyleSheet("""
            InfoCard {
                background-color: white;
                border: 1px solid #e0e0e0;
                border-radius: 12px;
            }
            InfoCard:hover {
                border: 1px solid #d0d0d0;
            }
        """)
        self._setup_ui(title)
        
    def _setup_ui(self, title: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        
        # Title with icon
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        
        self.title_label = QLabel(title)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet("color: #333; border: none; background: transparent;")
        title_layout.addWidget(self.title_label)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # Separator line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #e8e8e8; border: none; max-height: 1px;")
        layout.addWidget(line)
        
        # Content area
        self.content_layout = QGridLayout()
        self.content_layout.setContentsMargins(0, 8, 0, 0)
        self.content_layout.setHorizontalSpacing(16)
        self.content_layout.setVerticalSpacing(10)
        self.content_layout.setColumnStretch(0, 0)  # Label column - don't stretch
        self.content_layout.setColumnStretch(1, 1)  # Value column - stretch to fill
        self.content_layout.setColumnMinimumWidth(0, 100)  # Minimum width for labels
        layout.addLayout(self.content_layout)
        
        self._row = 0
        
    def add_row(self, label: str, value: str, value_color: str = "#333"):
        """Add a label-value row to the card."""
        label_widget = QLabel(label)
        label_widget.setStyleSheet("color: #666; border: none; background: transparent; font-size: 12px;")
        label_widget.setMinimumWidth(90)
        
        value_widget = QLabel(value)
        value_widget.setStyleSheet(f"color: {value_color}; font-weight: 500; border: none; background: transparent; font-size: 12px;")
        value_widget.setWordWrap(True)
        value_widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        self.content_layout.addWidget(label_widget, self._row, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.content_layout.addWidget(value_widget, self._row, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._row += 1
        
    def clear_content(self):
        """Clear all content rows."""
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._row = 0
        
    def set_title(self, title: str):
        """Update the card title."""
        self.title_label.setText(title)


class DashboardWidget(QWidget):
    """Dashboard widget showing an overview of the selected pool/dataset."""
    
    status_message = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_object: Optional[ZfsObject] = None
        self._setup_ui()
        
    def _setup_ui(self):
        # Scroll area for the dashboard content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setStyleSheet("""
            QScrollArea { 
                background-color: #f8f9fa; 
                border: none; 
            }
            QScrollBar:vertical {
                background-color: #f0f0f0;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background-color: #c0c0c0;
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #a0a0a0;
            }
        """)
        
        # Main container widget
        container = QWidget()
        container.setStyleSheet("background-color: #f8f9fa;")
        self.main_layout = QVBoxLayout(container)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(20)
        
        # Header section
        self._create_header_section()
        
        # Storage usage section
        self._create_storage_section()
        
        # Info cards section (grid of cards)
        self._create_info_section()
        
        # Statistics section
        self._create_stats_section()
        
        # Add stretch at the bottom
        self.main_layout.addStretch()
        
        scroll_area.setWidget(container)
        
        # Root layout
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll_area)
        
    def _create_header_section(self):
        """Create the header section with name and type badge."""
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #667eea, stop:0.5 #764ba2, stop:1 #667eea);
                border: none;
                border-radius: 12px;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(24, 20, 24, 20)
        
        # Left side - Name and type
        left_layout = QVBoxLayout()
        left_layout.setSpacing(8)
        
        self.name_label = QLabel("Select a pool or dataset")
        name_font = QFont()
        name_font.setPointSize(18)
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        self.name_label.setStyleSheet("color: white; border: none; background: transparent;")
        self.name_label.setWordWrap(True)
        self.name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        left_layout.addWidget(self.name_label)
        
        self.type_label = QLabel("")
        self.type_label.setStyleSheet("""
            color: white;
            background-color: rgba(255, 255, 255, 0.2);
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 10px;
            font-weight: bold;
            border: none;
        """)
        self.type_label.setFixedHeight(24)
        self.type_label.hide()
        left_layout.addWidget(self.type_label, 0, Qt.AlignmentFlag.AlignLeft)
        
        header_layout.addLayout(left_layout, 1)
        header_layout.addStretch()
        
        # Right side - Health status (for pools)
        self.health_label = QLabel("")
        self.health_label.setStyleSheet("""
            color: white;
            background-color: #4CAF50;
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: bold;
            border: none;
        """)
        self.health_label.hide()
        header_layout.addWidget(self.health_label, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        self.main_layout.addWidget(header_frame)
        
    def _create_storage_section(self):
        """Create the storage usage section with progress bars."""
        self.storage_frame = QFrame()
        self.storage_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #e0e0e0;
                border-radius: 12px;
            }
        """)
        storage_layout = QVBoxLayout(self.storage_frame)
        storage_layout.setContentsMargins(24, 20, 24, 20)
        storage_layout.setSpacing(20)
        
        # Section title
        storage_title = QLabel("Storage Usage")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)
        storage_title.setFont(title_font)
        storage_title.setStyleSheet("color: #333; border: none; background: transparent;")
        storage_layout.addWidget(storage_title)
        
        # Primary usage bar
        self.primary_usage_bar = UsageBar()
        storage_layout.addWidget(self.primary_usage_bar)
        
        # Secondary usage bar (for datasets showing referenced vs quota)
        self.secondary_usage_bar = UsageBar()
        self.secondary_usage_bar.hide()
        storage_layout.addWidget(self.secondary_usage_bar)
        
        self.main_layout.addWidget(self.storage_frame)
        
    def _create_info_section(self):
        """Create the info cards section."""
        self.info_frame = QFrame()
        self.info_frame.setStyleSheet("QFrame { background-color: transparent; border: none; }")
        info_layout = QHBoxLayout(self.info_frame)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(20)
        
        # General info card
        self.general_card = InfoCard("General Information")
        info_layout.addWidget(self.general_card)
        
        # Configuration card
        self.config_card = InfoCard("Configuration")
        info_layout.addWidget(self.config_card)
        
        self.main_layout.addWidget(self.info_frame)
        
    def _create_stats_section(self):
        """Create the statistics section."""
        self.stats_frame = QFrame()
        self.stats_frame.setStyleSheet("QFrame { background-color: transparent; border: none; }")
        stats_layout = QHBoxLayout(self.stats_frame)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(20)
        
        # Performance/stats card
        self.stats_card = InfoCard("Statistics")
        stats_layout.addWidget(self.stats_card)
        
        # System info card (for pools)
        self.system_card = InfoCard("System Information")
        stats_layout.addWidget(self.system_card)
        
        self.main_layout.addWidget(self.stats_frame)
        
    def set_object(self, zfs_object: Optional[ZfsObject]):
        """Update the dashboard with the given ZFS object."""
        self._current_object = zfs_object
        
        if zfs_object is None:
            self._show_empty_state()
            return
            
        if isinstance(zfs_object, Pool):
            self._display_pool(zfs_object)
        elif isinstance(zfs_object, Dataset):
            self._display_dataset(zfs_object)
        elif isinstance(zfs_object, Snapshot):
            self._display_snapshot(zfs_object)
        else:
            self._show_empty_state()
            
    def _show_empty_state(self):
        """Show empty/placeholder state."""
        self.name_label.setText("Select a pool or dataset")
        self.type_label.hide()
        self.health_label.hide()
        
        # Reset storage bars
        self.primary_usage_bar.set_values(0, 0, "Storage")
        self.secondary_usage_bar.hide()
        
        # Clear info cards
        self.general_card.clear_content()
        self.general_card.add_row("", "Select an item from the tree to view its dashboard")
        
        self.config_card.clear_content()
        self.stats_card.clear_content()
        self.system_card.clear_content()
        self._update_system_info()
        
    def _display_pool(self, pool: Pool):
        """Display pool information."""
        # Header
        self.name_label.setText(pool.name)
        
        self.type_label.setText("POOL")
        self.type_label.setStyleSheet("""
            color: white;
            background-color: #6a64e8;
            padding: 2px 10px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: bold;
            border: none;
        """)
        self.type_label.show()
        
        # Health badge
        health = pool.health.upper() if pool.health else "UNKNOWN"
        health_colors = {
            "ONLINE": "#4CAF50",
            "DEGRADED": "#ff9800",
            "FAULTED": "#f44336",
            "OFFLINE": "#9e9e9e",
            "UNAVAIL": "#f44336",
            "REMOVED": "#795548",
        }
        health_color = health_colors.get(health, "#9e9e9e")
        self.health_label.setText(f"⬤ {health}")
        self.health_label.setStyleSheet(f"""
            color: white;
            background-color: {health_color};
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: bold;
            border: none;
        """)
        self.health_label.show()
        
        # Storage usage
        self.primary_usage_bar.set_values(pool.alloc, pool.size, "Pool Capacity")
        self.secondary_usage_bar.hide()
        
        # General info
        self.general_card.clear_content()
        self.general_card.add_row("Name:", pool.name)
        self.general_card.add_row("Health:", health, health_color)
        self.general_card.add_row("GUID:", pool.guid if pool.guid else "-")
        
        # Get properties
        props = pool.properties or {}
        self.general_card.add_row("Version:", str(props.get('version', '-')))
        self.general_card.add_row("Altroot:", props.get('altroot', '-'))
        
        # Configuration
        self.config_card.clear_content()
        self.config_card.add_row("Deduplication:", pool.dedup or "off")
        self.config_card.add_row("Fragmentation:", pool.frag if pool.frag != "-" else "-")
        self.config_card.add_row("Capacity:", pool.cap if pool.cap != "-" else "-")
        self.config_card.add_row("Autotrim:", props.get('autotrim', '-'))
        self.config_card.add_row("Autoexpand:", props.get('autoexpand', '-'))
        self.config_card.add_row("Failmode:", props.get('failmode', '-'))
        
        # Stats
        self.stats_card.clear_content()
        self.stats_card.add_row("Total Size:", utils.format_size(pool.size))
        self.stats_card.add_row("Allocated:", utils.format_size(pool.alloc))
        self.stats_card.add_row("Free:", utils.format_size(pool.free))
        
        # Count children
        num_datasets = self._count_datasets(pool.children)
        num_snapshots = self._count_snapshots(pool.children)
        self.stats_card.add_row("Datasets:", str(num_datasets))
        self.stats_card.add_row("Snapshots:", str(num_snapshots))
        
        # System info
        self._update_system_info()
        
    def _display_dataset(self, dataset: Dataset):
        """Display dataset information."""
        # Header
        self.name_label.setText(dataset.name)
        
        ds_type = dataset.obj_type.upper()
        type_color = "#2196F3" if ds_type == "DATASET" else "#9C27B0"  # Blue for dataset, purple for volume
        self.type_label.setText(ds_type)
        self.type_label.setStyleSheet(f"""
            color: white;
            background-color: {type_color};
            padding: 2px 10px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: bold;
            border: none;
        """)
        self.type_label.show()
        
        # Health badge (mounted status for datasets)
        if dataset.obj_type == "dataset":
            mounted_text = "MOUNTED" if dataset.is_mounted else "UNMOUNTED"
            mounted_color = "#4CAF50" if dataset.is_mounted else "#9e9e9e"
            self.health_label.setText(f"⬤ {mounted_text}")
            self.health_label.setStyleSheet(f"""
                color: white;
                background-color: {mounted_color};
                padding: 8px 16px;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                border: none;
            """)
            self.health_label.show()
        else:
            self.health_label.hide()
        
        # Storage usage
        total = dataset.used + dataset.available if dataset.available > 0 else dataset.used
        self.primary_usage_bar.set_values(dataset.used, total, "Space Used")
        
        # Show referenced data as secondary bar
        if dataset.referenced > 0:
            self.secondary_usage_bar.set_values(dataset.referenced, total, "Referenced Data")
            self.secondary_usage_bar.show()
        else:
            self.secondary_usage_bar.hide()
        
        # General info
        self.general_card.clear_content()
        self.general_card.add_row("Name:", dataset.name)
        self.general_card.add_row("Pool:", dataset.pool_name)
        self.general_card.add_row("Type:", dataset.obj_type.capitalize())
        self.general_card.add_row("Mountpoint:", dataset.mountpoint if dataset.mountpoint else "-")
        self.general_card.add_row("Mounted:", "Yes" if dataset.is_mounted else "No")
        
        # Configuration
        props = dataset.properties or {}
        self.config_card.clear_content()
        self.config_card.add_row("Compression:", props.get('compression', '-'))
        self.config_card.add_row("Dedup:", props.get('dedup', '-'))
        self.config_card.add_row("Atime:", props.get('atime', '-'))
        self.config_card.add_row("Sync:", props.get('sync', '-'))
        self.config_card.add_row("Record Size:", props.get('recordsize', '-'))
        
        if dataset.is_encrypted:
            self.config_card.add_row("Encrypted:", "Yes", "#f44336")
            self.config_card.add_row("Key Status:", props.get('keystatus', '-'))
        else:
            self.config_card.add_row("Encrypted:", "No")
        
        # Stats
        self.stats_card.clear_content()
        self.stats_card.add_row("Used:", utils.format_size(dataset.used))
        self.stats_card.add_row("Available:", utils.format_size(dataset.available))
        self.stats_card.add_row("Referenced:", utils.format_size(dataset.referenced))
        
        # Count children and snapshots
        num_children = len(dataset.children) if dataset.children else 0
        num_snapshots = len(dataset.snapshots) if dataset.snapshots else 0
        self.stats_card.add_row("Child Datasets:", str(num_children))
        self.stats_card.add_row("Snapshots:", str(num_snapshots))
        
        # Quota info if set
        quota = props.get('quota', 'none')
        refquota = props.get('refquota', 'none')
        if quota and quota != 'none' and quota != '-' and quota != '0':
            self.stats_card.add_row("Quota:", quota)
        if refquota and refquota != 'none' and refquota != '-' and refquota != '0':
            self.stats_card.add_row("Ref Quota:", refquota)
        
        # System info
        self._update_system_info()
        
    def _display_snapshot(self, snapshot: Snapshot):
        """Display snapshot information."""
        # Header
        self.name_label.setText(snapshot.name)
        
        self.type_label.setText("SNAPSHOT")
        self.type_label.setStyleSheet("""
            color: white;
            background-color: #607D8B;
            padding: 2px 10px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: bold;
            border: none;
        """)
        self.type_label.show()
        self.health_label.hide()
        
        # Storage (snapshots don't have 'available', just used and referenced)
        if snapshot.referenced > 0:
            self.primary_usage_bar.set_values(snapshot.used, snapshot.referenced, "Snapshot Size")
        else:
            self.primary_usage_bar.set_values(0, 0, "Snapshot Size")
        self.secondary_usage_bar.hide()
        
        # General info
        self.general_card.clear_content()
        
        # Extract snapshot name (part after @)
        snap_name = snapshot.name.split('@')[-1] if '@' in snapshot.name else snapshot.name
        parent_ds = snapshot.name.split('@')[0] if '@' in snapshot.name else "-"
        
        self.general_card.add_row("Snapshot:", snap_name)
        self.general_card.add_row("Dataset:", parent_ds)
        self.general_card.add_row("Pool:", snapshot.pool_name)
        self.general_card.add_row("Created:", snapshot.creation_time if snapshot.creation_time else "-")
        
        # Configuration (limited for snapshots)
        self.config_card.clear_content()
        props = snapshot.properties or {}
        self.config_card.add_row("Clones:", props.get('clones', '-'))
        self.config_card.add_row("Defer Destroy:", props.get('defer_destroy', '-'))
        self.config_card.add_row("Hold Tags:", props.get('userrefs', '-'))
        
        # Stats
        self.stats_card.clear_content()
        self.stats_card.add_row("Used:", utils.format_size(snapshot.used))
        self.stats_card.add_row("Referenced:", utils.format_size(snapshot.referenced))
        
        # System info
        self._update_system_info()
        
    def _update_system_info(self):
        """Update the system information card."""
        self.system_card.clear_content()
        self.system_card.set_title("System Information")
        
        # OS info
        self.system_card.add_row("OS:", platform.system())
        self.system_card.add_row("Platform:", platform.platform())
        
        # Python version
        py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        self.system_card.add_row("Python:", py_version)
        
        # Try to get ZFS version (stored in first pool usually)
        if self._current_object:
            props = {}
            if isinstance(self._current_object, Pool):
                props = self._current_object.properties or {}
            elif isinstance(self._current_object, (Dataset, Snapshot)):
                # Try to get from pool_name
                pass
            
            zfs_version = props.get('version', '-')
            if zfs_version and zfs_version != '-':
                self.system_card.add_row("ZFS Version:", str(zfs_version))
                
    def _count_datasets(self, children: List[Dataset]) -> int:
        """Recursively count all datasets."""
        count = 0
        for child in children:
            count += 1
            if child.children:
                count += self._count_datasets(child.children)
        return count
        
    def _count_snapshots(self, children: List[Dataset]) -> int:
        """Recursively count all snapshots."""
        count = 0
        for child in children:
            if child.snapshots:
                count += len(child.snapshots)
            if child.children:
                count += self._count_snapshots(child.children)
        return count


# --- END OF FILE src/widgets/dashboard_widget.py ---
