from PySide6.QtCore import QThread, Signal, Slot

import traceback

class Worker(QThread):
    """
    Generic worker thread for running ZFS commands or other long tasks.
    
    Note: Removed WaitCursor handling - UI stays responsive during operations.
    Action buttons are disabled via main_window._update_action_states() instead.
    """
    # Signal(result_type)
    result_ready = Signal(object)  # Emits the result of the task
    error_occurred = Signal(str, str) # Emits (error_message, details)
    status_update = Signal(str)    # Emits progress messages

    def __init__(self, task_func, *args, **kwargs):
        super().__init__()
        self.task_func = task_func
        self.args = args
        self.kwargs = kwargs
        self._is_running = True

    @Slot()
    def run(self):
        self.status_update.emit(f"Starting task: {self.task_func.__name__}...")
        try:
            result = self.task_func(*self.args, **self.kwargs)

            # Check if the task was stopped *during* execution before emitting
            if not self._is_running:
                 self.status_update.emit(f"Task aborted: {self.task_func.__name__}")
                 return # Don't emit results if stopped

            self.result_ready.emit(result)
            status_msg = f"Task completed: {self.task_func.__name__}"
            # If result is tuple (success_bool, message), adjust status
            if isinstance(result, tuple) and len(result) >= 2 and isinstance(result[0], bool):
                 status_msg = f"Task {self.task_func.__name__}: {'Success' if result[0] else 'Failed'} - {result[1]}"
            self.status_update.emit(status_msg)

        except Exception as e:
            if self._is_running: # Only report error if not intentionally stopped
                error_trace = traceback.format_exc()
                print(f"Error in worker thread ({self.task_func.__name__}): {e}\n{error_trace}")
                self.error_occurred.emit(f"Error during '{self.task_func.__name__}': {e}", error_trace)
                self.status_update.emit(f"Task failed: {self.task_func.__name__}")

    def stop(self):
        # Only change state if it's actually running
        if self.isRunning():
            self.status_update.emit(f"Attempting to stop task: {self.task_func.__name__}...")
            self._is_running = False
            # Note: This doesn't forcefully stop the underlying zfs command.
            # Proper cancellation might require process termination, which is complex.
            # We primarily prevent signals from being emitted after stop() is called.
