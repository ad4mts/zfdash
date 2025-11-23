# --- START OF FILE utils.py ---

import re
import subprocess # Keep subprocess for potential future use? Maybe not needed now.
import sys
import os
import shlex # Keep shlex, it's useful

# --- Helper Script related constants REMOVED ---
# HELPER_SCRIPT_PATH = ...
# HELPER_EXISTS = ...
# HELPER_EXECUTABLE = ...
# POLKIT_ACTION_ID = ... (removed - PolicyKit is Linux-specific)

def parse_size(size_str):
    """Parses ZFS size strings (e.g., 1.23G, 100M, 500K, 2T) into bytes."""
    if isinstance(size_str, (int, float)):
        return int(size_str)
    if size_str is None or size_str == '-' or not isinstance(size_str, str):
        return 0

    size_str = size_str.upper().strip()
    # Allow for optional 'B' at the end, and 'iB' for kibibytes etc.
    match = re.match(r'^([\d.]+)\s*([KMGTPEZY])?I?B?$', size_str)
    if not match:
        try:
            # Assume bytes if no unit and conversion works
            return int(float(size_str))
        except ValueError:
             # Check if it's exactly '0' before returning 0, otherwise it's invalid
             if size_str == '0': return 0
             # Raise error for unparseable non-zero strings
             raise ValueError(f"Invalid size format: '{size_str}'")


    value = float(match.group(1))
    unit = match.group(2)

    units = {'K': 1, 'M': 2, 'G': 3, 'T': 4, 'P': 5, 'E': 6, 'Z': 7, 'Y': 8}
    if unit:
        exponent = units.get(unit, 0)
        value *= 1024 ** exponent

    return int(value)


def format_size(size_bytes):
    """Formats bytes into a human-readable ZFS-like size string."""
    if size_bytes is None or not isinstance(size_bytes, (int, float)) or size_bytes < 0:
        return "-"
    if size_bytes == 0:
        return "0B" # Consistent output for zero

    units = ['B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y']
    i = 0
    # Use float division for accuracy
    float_size = float(size_bytes)
    while float_size >= 1024 and i < len(units) - 1:
        float_size /= 1024.0
        i += 1

    # Use ZFS-style precision (usually 2 decimal places, unless it's small or integer)
    if i == 0: # Bytes
        return f"{int(float_size)}{units[i]}"
    elif float_size < 10:
        return f"{float_size:.2f}{units[i]}"
    elif float_size < 100:
        return f"{float_size:.1f}{units[i]}"
    else:
        # Round to nearest integer if >= 100
        return f"{int(round(float_size))}{units[i]}"


def format_capacity(used_bytes, total_bytes):
    """Formats used/total bytes into a percentage string."""
    if total_bytes is None or not isinstance(total_bytes, (int, float)) or total_bytes <= 0:
        return "0%" # Avoid division by zero
    if used_bytes is None or not isinstance(used_bytes, (int, float)) or used_bytes < 0:
        used_bytes = 0

    percentage = (used_bytes / total_bytes) * 100
    # Clamp percentage between 0 and 100+ (don't show negative)
    percentage = max(0, percentage)
    return f"{percentage:.1f}%"

# --- run_privileged_action REMOVED ---

# --- END OF FILE utils.py ---
