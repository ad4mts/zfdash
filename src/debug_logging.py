"""
Unified Logging Utility for ZfDash Daemon

Provides a centralized logging system that:
- Routes logs to file and optionally terminal (via configured stderr)
- Filters DEBUG-level messages based on --debug flag
- Forces IMPORTANT/ERROR/CRITICAL to terminal even without --debug

Usage:
    from debug_logging import log, set_debug_mode, configure_terminal_output

Modules call:
    log("TCP_SERVER", "message")                    # INFO level (always logged) except in daemon (stderr redirected)
    log("TCP_SERVER", "verbose details", "DEBUG")   # Only logged with --debug
    log("DAEMON", "error occurred", "ERROR")        # Always logged + forced to terminal
"""

import sys
from typing import Optional

# Global state
_debug_enabled = False
_original_stderr = None  # Set by daemon to force terminal output for errors


def set_debug_mode(enabled: bool) -> None:
    """Enable or disable debug logging globally."""
    global _debug_enabled
    _debug_enabled = enabled


def configure_terminal_output(original_stderr) -> None:
    """
    Configure terminal for forced output of errors.
    
    Called by daemon after setting up stderr redirect.
    Args:
        original_stderr: The original sys.stderr before redirect
    """
    global _original_stderr
    _original_stderr = original_stderr


def is_debug_enabled() -> bool:
    """Check if debug mode is enabled."""
    return _debug_enabled

def log(prefix: str, message: str, level: str = "INFO") -> None:
    """
    Log a message with the specified level.
    
    Args:
        prefix: Module prefix (e.g., "TCP_SERVER", "TLS", "DAEMON")
        message: The log message
        level: Log level - DEBUG, INFO, IMPORTANT, ERROR, CRITICAL
               DEBUG messages are only shown when debug mode is enabled.
    """
    # Skip DEBUG messages when debug mode is disabled
    if level == "DEBUG" and not _debug_enabled:
        return
    
    # Format message with level
    txt = f"{prefix} [{level}]: {message}" if prefix else f"[{level}]: {message}"
    
    # Write to configured stderr (may be file, or Tee in debug mode)
    print(txt, file=sys.stderr)

# =============================================================================
# Daemon-specific logging (stderr redirected to file by default)
# =============================================================================

# Levels that always show on terminal (even without --debug)
ALWAYS_SHOW_LEVELS = ("CRITICAL", "ERROR", "IMPORTANT", "WARNING")

def daemon_log(message: str, level: str = "INFO") -> None:
    """
    Daemon-specific logging with DAEMON prefix.
    
    Daemon stderr is redirected to file by default. This function:
    - Without --debug: Only shows IMPORTANT/ERROR/CRITICAL/WARNING on terminal
    - With --debug: Shows all messages (Tee sends to both terminal and file)
    
    Args:
        message: The log message
        level: DEBUG, INFO, WARNING, IMPORTANT, ERROR, CRITICAL
    """
    # Skip non-critical messages when debug disabled
    if level not in ALWAYS_SHOW_LEVELS and not _debug_enabled:
        return
    
    # Format message
    txt = f"DAEMON [{level}]: {message}"
    
    # Write to stderr (file only normally, Tee in debug mode)
    print(txt, file=sys.stderr)
    
    # FORCE terminal output for important levels when NOT in debug mode
    # (In debug mode, Tee already handles terminal output)
    if level in ALWAYS_SHOW_LEVELS and not _debug_enabled:
        if _original_stderr and sys.stderr != _original_stderr:
            try:
                print(txt, file=_original_stderr)
            except Exception:
                pass

# Convenience aliases for cleaner code
def log_debug(prefix: str, message: str) -> None:
    """Shortcut for DEBUG level logging."""
    log(prefix, message, "DEBUG")

def log_info(prefix: str, message: str) -> None:
    """Shortcut for INFO level logging."""
    log(prefix, message, "INFO")

def log_important(prefix: str, message: str) -> None:
    """Shortcut for IMPORTANT level logging."""
    log(prefix, message, "IMPORTANT")

def log_error(prefix: str, message: str) -> None:
    """Shortcut for ERROR level logging."""
    log(prefix, message, "ERROR")
def log_warning(prefix: str, message: str) -> None:
    """Shortcut for WARNING level logging."""
    log(prefix, message, "WARNING")
def log_critical(prefix: str, message: str) -> None:
    """Shortcut for CRITICAL level logging."""
    log(prefix, message, "CRITICAL")
