# --- START OF FILE widgets/pool_status_widget.py ---

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton,
    QButtonGroup, QFrame, QLabel
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QIcon, QFont

from typing import Optional
from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError


class PoolStatusWidget(QWidget):
    """Widget to display ZFS pool status with switchable views (status, layout, iostat)."""

    status_message = Signal(str)

    def __init__(self, zfs_client: ZfsManagerClient, parent=None):
        super().__init__(parent)
        self.zfs_client = zfs_client
        self._current_pool_name: Optional[str] = None
        self._current_view: str = 'status'  # 'status', 'layout', or 'iostat'
        self._cache = {
            'status': None,
            'layout': None,
            'iostat': None
        }
        self._setup_ui()

    def _setup_ui(self):
        """Set up the widget UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header with buttons
        header_frame = QFrame()
        header_frame.setFrameShape(QFrame.Shape.NoFrame)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(8, 8, 8, 8)

        # Title
        title_label = QLabel("Pool Health")
        title_font = title_label.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        title_label.setFont(title_font)
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # Button group for view switching
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        self.status_btn = QPushButton(QIcon.fromTheme("dialog-information"), " Status")
        self.status_btn.setCheckable(True)
        self.status_btn.setChecked(True)
        self.status_btn.setToolTip("Show zpool status output")
        self.button_group.addButton(self.status_btn, 0)
        header_layout.addWidget(self.status_btn)

        self.layout_btn = QPushButton(QIcon.fromTheme("view-list-tree", QIcon.fromTheme("document-properties")), " Layout")
        self.layout_btn.setCheckable(True)
        self.layout_btn.setToolTip("Show zpool list -v output")
        self.button_group.addButton(self.layout_btn, 1)
        header_layout.addWidget(self.layout_btn)

        self.iostat_btn = QPushButton(QIcon.fromTheme("utilities-system-monitor", QIcon.fromTheme("dialog-information")), " IO Stats")
        self.iostat_btn.setCheckable(True)
        self.iostat_btn.setToolTip("Show zpool iostat -v output")
        self.button_group.addButton(self.iostat_btn, 2)
        header_layout.addWidget(self.iostat_btn)

        main_layout.addWidget(header_frame)

        # Content area
        self.content_text = QPlainTextEdit()
        self.content_text.setReadOnly(True)
        monospace_font = QFont("Monospace")
        monospace_font.setStyleHint(QFont.StyleHint.TypeWriter)
        monospace_font.setPointSize(10)
        self.content_text.setFont(monospace_font)
        self.content_text.setPlaceholderText("Select a pool to view its status.")
        main_layout.addWidget(self.content_text)

        # Connect signals
        self.button_group.idClicked.connect(self._on_view_changed)

        # Initial state - buttons disabled until pool selected
        self._set_buttons_enabled(False)

    def _set_buttons_enabled(self, enabled: bool):
        """Enable or disable the view buttons."""
        self.status_btn.setEnabled(enabled)
        self.layout_btn.setEnabled(enabled)
        self.iostat_btn.setEnabled(enabled)

    def _on_view_changed(self, button_id: int):
        """Handle view button click."""
        view_map = {0: 'status', 1: 'layout', 2: 'iostat'}
        new_view = view_map.get(button_id, 'status')
        
        if new_view == self._current_view:
            return
        
        self._current_view = new_view
        self._update_display()

    def _update_display(self):
        """Update the display based on current view and cache."""
        if not self._current_pool_name:
            self.content_text.setPlainText("Select a pool to view its status.")
            return

        if self._current_view == 'status':
            if self._cache['status']:
                self.content_text.setPlainText(self._cache['status'])
            else:
                self.content_text.setPlainText("Pool status not available.")
        elif self._current_view == 'layout':
            if self._cache['layout']:
                self.content_text.setPlainText(self._cache['layout'])
            else:
                self._fetch_pool_data('layout')
        elif self._current_view == 'iostat':
            if self._cache['iostat']:
                self.content_text.setPlainText(self._cache['iostat'])
            else:
                self._fetch_pool_data('iostat')

    def _fetch_pool_data(self, data_type: str):
        """Fetch pool data from daemon."""
        if not self._current_pool_name or not self.zfs_client:
            return

        self.content_text.setPlainText(f"Loading {data_type}...")
        
        try:
            if data_type == 'layout':
                success, msg = self.zfs_client.execute_generic_action(
                    'get_pool_list_verbose', 
                    f"Got pool layout for {self._current_pool_name}",
                    self._current_pool_name
                )
            elif data_type == 'iostat':
                success, msg = self.zfs_client.execute_generic_action(
                    'get_pool_iostat_verbose',
                    f"Got IO stats for {self._current_pool_name}",
                    self._current_pool_name
                )
            else:
                return

            if success:
                # The message contains the data after the success message and ": "
                # Format: "Got pool layout for <pool>: <actual data>"
                data_start = msg.find(': ')
                if data_start != -1:
                    data = msg[data_start + 2:]
                else:
                    data = msg
                self._cache[data_type] = data
                # Only update if still on same view
                if self._current_view == data_type:
                    self.content_text.setPlainText(data)
            else:
                error_msg = f"Error fetching {data_type}: {msg}"
                self._cache[data_type] = error_msg
                if self._current_view == data_type:
                    self.content_text.setPlainText(error_msg)

        except (ZfsCommandError, ZfsClientCommunicationError) as e:
            error_msg = f"Error fetching {data_type}: {e}"
            self._cache[data_type] = error_msg
            if self._current_view == data_type:
                self.content_text.setPlainText(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error fetching {data_type}: {e}"
            self._cache[data_type] = error_msg
            if self._current_view == data_type:
                self.content_text.setPlainText(error_msg)

    def set_pool(self, pool_name: Optional[str], status_text: str = ""):
        """Set the current pool and its status text."""
        # If pool changed, clear caches
        if pool_name != self._current_pool_name:
            self._cache = {
                'status': status_text if pool_name else None,
                'layout': None,
                'iostat': None
            }
            self._current_pool_name = pool_name
            self._current_view = 'status'
            
            # Reset button state
            self.status_btn.setChecked(True)
            self._set_buttons_enabled(pool_name is not None)
        else:
            # Same pool, just update status cache
            self._cache['status'] = status_text

        self._update_display()

    def clear(self):
        """Clear the widget (when no pool is selected)."""
        self._current_pool_name = None
        self._cache = {'status': None, 'layout': None, 'iostat': None}
        self._current_view = 'status'
        self.status_btn.setChecked(True)
        self._set_buttons_enabled(False)
        self.content_text.setPlainText("Pool status not applicable.")


# --- END OF FILE widgets/pool_status_widget.py ---
