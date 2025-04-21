# --- START OF FILE zfs_manager_core.py ---

import subprocess
import re
import os
import sys
import shlex
import json
import datetime # For logging timestamp
import stat # For setting log file permissions
from typing import List, Dict, Tuple, Optional, Any, Union
import traceback # Added traceback import
import utils # <-- Import utils here
from functools import wraps

# Import constants and config manager
try:
    import constants
    import config_manager
except ImportError as e:
    print(f"CORE: Error importing constants/config_manager: {e}. Cannot continue without them.", file=sys.stderr)
    raise e # Or sys.exit(1)

# --- Find ZFS/ZPOOL Executables ---
def _find_executable(name, paths=['/usr/sbin', '/sbin', '/usr/bin', '/bin']):
    for path_dir in paths:
        full_path = os.path.join(path_dir, name)
        if os.path.exists(full_path) and os.access(full_path, os.X_OK):
            return full_path
    return None

ZFS_CMD_PATH = _find_executable("zfs")
ZPOOL_CMD_PATH = _find_executable("zpool")

# --- Error Classes ---
class ZfsError(Exception):
    """Base class for ZFS related errors."""
    pass

class ZfsCommandError(ZfsError):
    """Custom exception for ZFS command execution errors."""
    def __init__(self, message, command_parts=None, stderr=None, returncode=None):
        super().__init__(message)
        self.command_parts = command_parts
        self.stderr = stderr
        self.returncode = returncode

    def __str__(self):
        details = []
        if self.command_parts:
             try: cmd_str = shlex.join(self.command_parts); details.append(f"Command: {cmd_str}")
             except TypeError: details.append(f"Command: {self.command_parts}") # Fallback
        if self.returncode is not None: details.append(f"Return Code: {self.returncode}")
        if self.stderr:
             stderr_short = self.stderr.strip()
             if len(stderr_short) > 300: stderr_short = stderr_short[:300] + "..."
             details.append(f"Stderr: {stderr_short}")
        details_str = " (" + ", ".join(details) + ")" if details else ""
        return f"{super().__str__()}{details_str}"

class ZfsParsingError(ZfsError):
    """Custom exception for errors parsing ZFS command output."""
    def __init__(self, message, raw_line=None, command_parts=None):
        super().__init__(message)
        self.raw_line = raw_line
        self.command_parts = command_parts

    def __str__(self):
        details = []
        if self.command_parts:
             try: cmd_str = shlex.join(self.command_parts); details.append(f"Command: {cmd_str}")
             except TypeError: details.append(f"Command: {self.command_parts}")
        if self.raw_line: details.append(f"Problematic Line: '{self.raw_line[:100]}{'...' if len(self.raw_line)>100 else ''}'")
        details_str = " (" + ", ".join(details) + ")" if details else ""
        return f"{super().__str__()}{details_str}"


# --- Internal Command Runner ---
def _run_command(
    command_parts: list[str],
    *,
    log_enabled: bool = False,
    user_uid: int = -1,
    passphrase: Optional[str] = None,
    passphrase_change_info: Optional[str] = None # For change-key specifically
) -> tuple[int, str, str]:
    """
    Runs a command using subprocess, handles input/output, logging, and errors.
    Determines input_data based on command and passphrase arguments.
    """
    if not command_parts or not command_parts[0]:
        err_msg = "Error: Invalid command parts provided to _run_command."
        print(f"DAEMON_CORE: {err_msg}", file=sys.stderr)
        # Return consistent tuple format
        return -1, "", err_msg

    cmd_str_safe = "Invalid command"
    try:
        cmd_str_safe = shlex.join(command_parts)
    except TypeError:
        cmd_str_safe = str(command_parts) # Fallback

    # Determine input_data based on command type and provided passphrases
    input_data = None
    command_action = command_parts[1] if len(command_parts) > 1 else ""
    is_zfs_cmd = command_parts[0] == ZFS_CMD_PATH
    is_zpool_cmd = command_parts[0] == ZPOOL_CMD_PATH

    if is_zfs_cmd:
        if command_action in ['create', 'load-key'] and passphrase:
            input_data = passphrase
        elif command_action == 'change-key' and passphrase_change_info:
            input_data = passphrase_change_info
    elif is_zpool_cmd:
        # Check if 'create' command includes encryption options requiring passphrase
        if command_action == 'create' and passphrase:
            # Look for '-o keyformat=passphrase' and potentially '-o keylocation=prompt' (though prompt is implicit)
            has_passphrase_format = False
            for i, part in enumerate(command_parts):
                if part == '-O' and i + 1 < len(command_parts):
                    option = command_parts[i+1]
                    if option.startswith('keyformat=passphrase'):
                        has_passphrase_format = True
                        break
            if has_passphrase_format:
                input_data = passphrase

    encoded_input = input_data.encode('utf-8') if input_data is not None else None
    log_input_display = "[hidden passphrase]" if input_data else "[none]"

    print(f"DAEMON_CORE: Executing: {cmd_str_safe}{f' (Input: {log_input_display})' if input_data else ''}", file=sys.stderr)

    process = None
    start_time = datetime.datetime.now()
    stdout, stderr, returncode = "", "", -1

    # Get configurable timeout
    timeout_seconds = config_manager.get_setting("daemon_command_timeout", constants.DEFAULT_DAEMON_COMMAND_TIMEOUT)
    try:
        timeout_seconds = int(timeout_seconds)
        if timeout_seconds <= 0: timeout_seconds = constants.DEFAULT_DAEMON_COMMAND_TIMEOUT
    except (ValueError, TypeError):
        timeout_seconds = constants.DEFAULT_DAEMON_COMMAND_TIMEOUT
        print(f"DAEMON_CORE: Warning: Invalid daemon_command_timeout in config. Using default: {timeout_seconds}s", file=sys.stderr)

    try:
        process = subprocess.run(
            command_parts,
            input=encoded_input,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=False, # Read bytes
            check=False, # Don't raise exception on non-zero exit
            timeout=timeout_seconds
        )
        returncode = process.returncode
        # Decode with error handling
        stdout = process.stdout.decode('utf-8', errors='replace') if process.stdout else ""
        stderr = process.stderr.decode('utf-8', errors='replace') if process.stderr else ""

        if process.returncode != 0:
             print(f"DAEMON_CORE: Command failed (ret={returncode}) for: {cmd_str_safe}", file=sys.stderr)
             if stderr: print(f"DAEMON_CORE: Stderr:\n{stderr.strip()}", file=sys.stderr)
             else: print(f"DAEMON_CORE: No stderr captured.", file=sys.stderr)
             # Only print stdout if stderr is empty, as stderr is usually more informative on failure
             if stdout and not stderr.strip(): print(f"DAEMON_CORE: Stdout:\n{stdout.strip()}", file=sys.stderr)

    except FileNotFoundError:
        err_msg = f"Error: Command not found: '{command_parts[0]}'."
        print(f"DAEMON_CORE: {err_msg}", file=sys.stderr)
        stderr = err_msg; returncode = -1
    except PermissionError:
        err_msg = f"Error: Permission denied executing '{command_parts[0]}'."
        print(f"DAEMON_CORE: {err_msg}", file=sys.stderr)
        stderr = err_msg; returncode = -1
    except subprocess.TimeoutExpired:
        err_msg = f"Error: Command '{cmd_str_safe}' timed out after {timeout_seconds} seconds."
        print(f"DAEMON_CORE: {err_msg}", file=sys.stderr)
        stderr = err_msg; returncode = -1 # Or a specific timeout code?
    except Exception as e:
        err_msg = f"Unexpected error running command {cmd_str_safe}: {e}"
        print(f"DAEMON_CORE: {err_msg}\n{traceback.format_exc()}", file=sys.stderr)
        stderr = err_msg; returncode = -1
    finally:
        # Logging
        if log_enabled:
            if user_uid < 0:
                 print(f"DAEMON_CORE: Warning: Cannot log command, invalid user UID ({user_uid}) provided.", file=sys.stderr)
            else:
                log_path = config_manager.get_daemon_log_file_path(user_uid)
                end_time = datetime.datetime.now()
                duration = end_time - start_time
                try:
                    log_dir = os.path.dirname(log_path)
                    if not os.path.exists(log_dir):
                        try: os.makedirs(log_dir, exist_ok=True)
                        except OSError as dir_e: print(f"DAEMON_CORE: Warning: Could not create log directory {log_dir}: {dir_e}", file=sys.stderr)

                    if not os.path.exists(log_path):
                         open(log_path, 'a').close()
                         try:
                              # Set permissions to rw-rw---- (user=rw, group=rw, others=no)
                              os.chmod(log_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP)
                              os.chown(log_path, user_uid, -1) # Keep group same as daemon
                         except OSError as perm_e: print(f"DAEMON_CORE: Warning: Could not set permissions/owner on log file {log_path}: {perm_e}", file=sys.stderr)

                    with open(log_path, 'a', encoding='utf-8') as log_file:
                        log_file.write(f"--- {start_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} ---\n")
                        log_file.write(f"COMMAND: {cmd_str_safe}\n")
                        if input_data: log_file.write(f"INPUT: {log_input_display}\n")
                        log_file.write(f"RETURN CODE: {returncode}\n")
                        log_file.write(f"DURATION: {duration.total_seconds():.3f}s\n")
                        if stdout: log_file.write("STDOUT:\n"); log_file.write(stdout.strip() + "\n")
                        if stderr: log_file.write("STDERR:\n"); log_file.write(stderr.strip() + "\n")
                        log_file.write("\n")
                except (IOError, OSError) as log_e: print(f"DAEMON_CORE: Error writing to log file '{log_path}': {log_e}", file=sys.stderr)
                except Exception as outer_log_e: print(f"DAEMON_CORE: Unexpected error during logging: {outer_log_e}\n{traceback.format_exc()}", file=sys.stderr)

    return returncode, stdout, stderr


# --- Helper to adapt functions for common kwargs ---
def adapt_common_kwargs(func):
    """
    Decorator to extract common arguments like _log_enabled and _user_uid
    and pass them explicitly to the wrapped function.
    Passphrase arguments are now handled directly by _run_command or the function.
    """
    def wrapper(*args, **kwargs):
        log_enabled = kwargs.pop('_log_enabled', False)
        user_uid = kwargs.pop('_user_uid', -1)
        # Passphrase args are kept in kwargs for the function or _run_command to handle
        return func(*args, _log_enabled=log_enabled, _user_uid=user_uid, **kwargs)
    return wrapper


# --- Command Builder Base Class ---
class CommandBuilder:
    def __init__(self, base_command: str):
        if not base_command:
            raise ValueError("Base command cannot be empty")
        self._parts: List[str] = [base_command]
        self._passphrase: Optional[str] = None
        self._passphrase_change_info: Optional[str] = None

    def _add_option(self, flag: str, value: Union[str, bool]):
        if isinstance(value, bool):
            if value: self._parts.append(flag)
        elif value is not None:
            self._parts.extend([flag, str(value)])
        return self

    def _add_flag(self, flag: str, condition: bool = True):
        if condition:
            self._parts.append(flag)
        return self

    def _add_key_value_option(self, flag: str, key: str, value: str):
        if key and value is not None:
            self._parts.extend([flag, f"{key}={value}"])
        return self

    def _add_args(self, *args: Optional[str]):
        for arg in args:
            if arg is not None:
                self._parts.append(arg)
        return self

    def _add_arg_list(self, args: Optional[List[str]]):
        if args:
            self._parts.extend(args)
        return self

    def set_passphrase(self, passphrase: Optional[str]):
        self._passphrase = passphrase
        return self

    def set_passphrase_change(self, change_info: Optional[str]):
        self._passphrase_change_info = change_info
        return self

    def build(self) -> List[str]:
        return self._parts

    def get_passphrase(self) -> Optional[str]:
        return self._passphrase

    def get_passphrase_change_info(self) -> Optional[str]:
        return self._passphrase_change_info

    def run(self, *, _log_enabled=False, _user_uid=-1) -> Tuple[int, str, str]:
        """Builds and runs the command using _run_command."""
        cmd_parts = self.build()
        return _run_command(
            cmd_parts,
            log_enabled=_log_enabled,
            user_uid=_user_uid,
            passphrase=self.get_passphrase(),
            passphrase_change_info=self.get_passphrase_change_info()
        )

# --- ZFS Command Builder ---
class ZfsCommandBuilder(CommandBuilder):
    def __init__(self, action: str):
        if not ZFS_CMD_PATH: raise ZfsCommandError("zfs command not found.")
        super().__init__(ZFS_CMD_PATH)
        self._add_args(action)

    def recursive(self, condition=True): return self._add_flag('-r', condition)
    def force(self, condition=True): return self._add_flag('-f', condition)
    def parsable(self, condition=True): return self._add_flag('-p', condition)
    def script(self, condition=True): return self._add_flag('-H', condition) # No header, tab separated
    def type(self, types: str): return self._add_option('-t', types) # e.g., "filesystem,volume"
    def output_props(self, props: List[str]): return self._add_option('-o', ','.join(props))
    def option(self, key: str, value: str): return self._add_key_value_option('-o', key, value)
    def volsize(self, size: str): return self._add_option('-V', size)
    def keylocation(self, location: str): return self._add_option('-L', location)
    def loadkey(self, condition=True): return self._add_flag('-l', condition) # For change-key
    def target(self, name: str): return self._add_args(name)
    def targets(self, *names: str): return self._add_args(*names)

# --- ZPOOL Command Builder ---
class ZpoolCommandBuilder(CommandBuilder):
    def __init__(self, action: str):
        if not ZPOOL_CMD_PATH: raise ZfsCommandError("zpool command not found.")
        super().__init__(ZPOOL_CMD_PATH)
        self._add_args(action)

    def force(self, condition=True): return self._add_flag('-f', condition)
    def parsable(self, condition=True): return self._add_flag('-p', condition) # Show full paths
    def script(self, condition=True): return self._add_flag('-H', condition) # No header, tab separated
    def verbose(self, condition=True): return self._add_flag('-v', condition)
    def output_props(self, props: List[str]): return self._add_option('-o', ','.join(props))
    def pool_option(self, key: str, value: str): return self._add_key_value_option('-o', key, value)
    def fs_option(self, key: str, value: str): return self._add_key_value_option('-O', key, value)
    def search_dir(self, dir_path: str): return self._add_option('-d', dir_path)
    def search_dirs(self, dir_paths: List[str]):
        for d in dir_paths: self._add_option('-d', d)
        return self
    def pool(self, name: str): return self._add_args(name)
    def pools(self, *names: str): return self._add_args(*names)
    def device(self, name: str): return self._add_args(name)
    def devices(self, *names: str): return self._add_args(*names)
    def new_name(self, name: str): return self._add_args(name) # For import
    def import_all(self, condition=True): return self._add_flag('-a', condition)
    def temporary(self, condition=True): return self._add_flag('-t', condition) # For offline
    def expand(self, condition=True): return self._add_flag('-e', condition) # For online
    def stop_scrub(self, condition=True): return self._add_flag('-s', condition)
    def dry_run(self, condition=True): return self._add_flag('-n', condition) # For split
    def altroot(self, path: str): return self._add_option('-R', path) # For split

    def add_vdev_specs(self, vdev_specs: List[Dict[str, Any]], context: str):
        valid_vdevs_added = 0
        for i, vdev_raw in enumerate(vdev_specs):
            try:
                vdev = _validate_vdev_spec(vdev_raw, f"{context} spec #{i}")
                if vdev is None: continue # Should not happen if validation is strict
                vdev_type = vdev['type']; devices = vdev['devices']
                # Don't add 'disk' type explicitly, just devices
                if vdev_type != 'disk': self._add_args(vdev_type)
                self._add_arg_list(devices)
                valid_vdevs_added += 1
            except ZfsCommandError as e:
                # Re-raise validation errors immediately
                raise e
            except Exception as e:
                err_msg = f"Unexpected error processing vdev spec #{i} ({vdev_raw!r}): {e}"
                print(f"DAEMON_CORE: {err_msg}\n{traceback.format_exc()}", file=sys.stderr)
                raise ZfsCommandError(err_msg) # Convert to ZfsCommandError
        if valid_vdevs_added == 0:
            raise ZfsCommandError(f"Cannot proceed with {context} with no valid devices specified after validation.")
        return self


# --- Core Get Functions ---
@adapt_common_kwargs
def list_pools(*, _log_enabled=False, _user_uid=-1, **kwargs) -> List[Dict[str, Any]]:
    builder = ZpoolCommandBuilder('list').script().output_props(constants.ZPOOL_PROPS)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError("Failed to list pools.", builder.build(), stderr, retcode)

    pools_data = []
    for line_num, line in enumerate(stdout.strip().split('\n'), 1):
        if not line: continue
        values = line.strip().split('\t')
        if len(values) == len(constants.ZPOOL_PROPS):
            pools_data.append(dict(zip(constants.ZPOOL_PROPS, values)))
        else:
            # Log error more formally, skip line
            err_msg = f"Mismatched columns parsing pool list output line {line_num}. Expected {len(constants.ZPOOL_PROPS)}, got {len(values)}."
            print(f"DAEMON_CORE: Error: {err_msg} Line: '{line}'", file=sys.stderr)
            # Optionally raise ZfsParsingError here if strictness is required
            # raise ZfsParsingError(err_msg, line, builder.build())
    return pools_data

@adapt_common_kwargs
def get_pool_status(pool_name: str, *, _log_enabled=False, _user_uid=-1, **kwargs) -> str:
    builder = ZpoolCommandBuilder('status').verbose().parsable().pool(pool_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to get status for pool '{pool_name}'.", builder.build(), stderr, retcode)
    return stdout.strip()

@adapt_common_kwargs
def list_all_datasets_snapshots(*, _log_enabled=False, _user_uid=-1, **kwargs) -> List[Dict[str, Any]]:
    items_data = []

    # List datasets/volumes
    ds_builder = ZfsCommandBuilder('list').script().recursive().output_props(constants.ZFS_DATASET_PROPS).type('filesystem,volume')
    retcode_ds, stdout_ds, stderr_ds = ds_builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode_ds != 0: raise ZfsCommandError("Failed to list datasets/volumes.", ds_builder.build(), stderr_ds, retcode_ds)

    for line_num, line in enumerate(stdout_ds.strip().split('\n'), 1):
        if not line: continue
        values = line.strip().split('\t')
        if len(values) == len(constants.ZFS_DATASET_PROPS):
            items_data.append(dict(zip(constants.ZFS_DATASET_PROPS, values)))
        else:
            err_msg = f"Mismatched columns parsing dataset/volume list output line {line_num}. Expected {len(constants.ZFS_DATASET_PROPS)}, got {len(values)}."
            print(f"DAEMON_CORE: Error: {err_msg} Line: '{line}'", file=sys.stderr)
            # raise ZfsParsingError(err_msg, line, ds_builder.build())

    # List snapshots
    snap_builder = ZfsCommandBuilder('list').script().recursive().output_props(constants.ZFS_SNAPSHOT_PROPS).type('snapshot')
    retcode_snap, stdout_snap, stderr_snap = snap_builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)

    # Handle expected "no snapshots" scenarios gracefully
    stderr_snap_lower = stderr_snap.lower()
    if retcode_snap != 0 and not ("does not exist" in stderr_snap_lower or "no datasets available" in stderr_snap_lower):
        # Log a warning for unexpected errors, but don't fail the whole operation
        print(f"DAEMON_CORE: Warning: Failed to list snapshots. Error: {stderr_snap.strip()}", file=sys.stderr)
    elif retcode_snap == 0:
        for line_num, line in enumerate(stdout_snap.strip().split('\n'), 1):
            if not line: continue
            values = line.strip().split('\t')
            if len(values) == len(constants.ZFS_SNAPSHOT_PROPS):
                snap_props = dict(zip(constants.ZFS_SNAPSHOT_PROPS, values))
                snap_props['type'] = 'snapshot' # Add type for consistency
                items_data.append(snap_props)
            else:
                err_msg = f"Mismatched columns parsing snapshot list output line {line_num}. Expected {len(constants.ZFS_SNAPSHOT_PROPS)}, got {len(values)}."
                print(f"DAEMON_CORE: Error: {err_msg} Line: '{line}'", file=sys.stderr)
                # raise ZfsParsingError(err_msg, line, snap_builder.build())

    return items_data

@adapt_common_kwargs
def get_all_properties_with_sources(obj_name: str, *, _log_enabled=False, _user_uid=-1, **kwargs) -> Dict[str, Dict[str, str]]:
    properties = {}
    builder = ZfsCommandBuilder('get').script().parsable().output_props(['name','property','value','source']).target('all').target(obj_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to get properties for '{obj_name}'.", builder.build(), stderr, retcode)

    for line_num, line in enumerate(stdout.strip().split('\n'), 1):
        if not line: continue
        try:
            _name, prop, value, source = line.strip().split('\t', 3)
            # Normalize source: '-' means local or default, treat as None for simplicity? Or keep '-'? Let's keep '-' for now.
            properties[prop] = {'value': value, 'source': source} # Source can be '-', 'local', 'inherited from X', 'default'
        except ValueError:
            err_msg = f"Could not parse property line {line_num}. Expected 4 tab-separated values."
            print(f"DAEMON_CORE: Error: {err_msg} Line: '{line}'", file=sys.stderr)
            # raise ZfsParsingError(err_msg, line, builder.build())
    return properties


# --- Action Functions ---

def _validate_vdev_spec(vdev_spec: Dict[str, Any], context: str) -> Dict[str, Any]:
    """Validates a single vdev specification dictionary. Raises ZfsCommandError on failure."""
    if not isinstance(vdev_spec, dict):
        raise ZfsCommandError(f"Invalid vdev spec in {context}: Expected dict, got {type(vdev_spec).__name__}")

    vdev_type = vdev_spec.get('type')
    devices = vdev_spec.get('devices')

    if not vdev_type or not isinstance(vdev_type, str):
        raise ZfsCommandError(f"Invalid vdev spec in {context}: Missing or invalid 'type' (string expected)")
    vdev_type = vdev_type.lower() # Normalize type

    if not devices or not isinstance(devices, list) or not devices:
        raise ZfsCommandError(f"Invalid vdev spec in {context}: Missing or empty 'devices' list for type '{vdev_type}'")

    validated_devices = []
    for i, dev in enumerate(devices):
        if not isinstance(dev, str) or not dev.strip():
             raise ZfsCommandError(f"Invalid device path at index {i} in {context} for type '{vdev_type}': Must be a non-empty string.")
        # Basic check for plausible device paths (can be expanded)
        if not dev.startswith('/dev/'):
            print(f"DAEMON_CORE: Warning: Device path '{dev}' in {context} doesn't start with /dev/. Proceeding cautiously.", file=sys.stderr)
            # Depending on strictness, could raise ZfsCommandError here
        validated_devices.append(dev.strip())

    # Return validated structure
    return {'type': vdev_type, 'devices': validated_devices}

@adapt_common_kwargs
def create_pool(pool_name: str, vdev_specs: List[Dict[str, Any]], options: Optional[Dict[str, str]] = None, force: bool = False, *, _log_enabled=False, _user_uid=-1, passphrase: Optional[str] = None, **kwargs):
    if not isinstance(vdev_specs, list):
        raise ZfsCommandError(f"Daemon received invalid vdev_specs for create_pool: Expected list, got {type(vdev_specs).__name__}")

    # Validate all specs first
    validated_specs = [_validate_vdev_spec(spec, f"create_pool '{pool_name}'") for spec in vdev_specs]

    builder = ZpoolCommandBuilder('create').force(force).pool(pool_name)
    builder.set_passphrase(passphrase) # Pass passphrase to builder

    # Process options
    if options:
        fs_props = ['mountpoint', 'encryption', 'keyformat', 'keylocation', 'pbkdf2iters', 'compression', 'atime', 'relatime', 'readonly', 'dedup', 'sync', 'logbias', 'recordsize']
        pool_props_o = ['altroot', 'cachefile', 'comment', 'failmode'] # -o
        pool_props_O = ['feature@encryption', 'listsnapshots', 'version'] # -O

        final_options = options.copy()
        # Remove keylocation=prompt if passphrase is provided (it's implicit)
        if passphrase and final_options.get('keylocation') == 'prompt' and final_options.get('keyformat') == 'passphrase':
            del final_options['keylocation']

        for key, value in final_options.items():
            if not isinstance(key, str) or not isinstance(value, str): continue # Skip invalid option types
            if key in fs_props or key in pool_props_O: builder.fs_option(key, value)
            elif key in pool_props_o: builder.pool_option(key, value)
            else: print(f"DAEMON_CORE: Warning: Ignoring unknown option '{key}' during pool creation.")

    # Add validated vdevs
    builder.add_vdev_specs(validated_specs, f"create_pool '{pool_name}'")

    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to create pool '{pool_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def destroy_pool(pool_name: str, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZpoolCommandBuilder('destroy').force().pool(pool_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to destroy pool '{pool_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def create_dataset(full_dataset_name: str, is_volume: bool = False, volsize: Optional[str] = None, options: Optional[Dict[str, str]] = None, *, _log_enabled=False, _user_uid=-1, passphrase: Optional[str] = None, **kwargs):
    builder = ZfsCommandBuilder('create')
    builder.set_passphrase(passphrase)

    if is_volume:
        if not volsize: raise ZfsCommandError("Volume size (-V) is required for creating ZFS volumes.")
        builder.volsize(volsize)

    if options:
        final_options = options.copy()
        # Remove keylocation=prompt if passphrase is provided
        if passphrase and final_options.get('keylocation') == 'prompt' and final_options.get('keyformat') == 'passphrase':
             del final_options['keylocation']
        for key, value in final_options.items():
            if not isinstance(key, str) or not isinstance(value, str): continue
            builder.option(key, value)

    builder.target(full_dataset_name)

    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to create {'volume' if is_volume else 'dataset'} '{full_dataset_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def destroy_dataset(full_dataset_name: str, recursive: bool = False, *, _log_enabled=False, _user_uid=-1, **kwargs):
    # Use -f -r for recursive destroy
    builder = ZfsCommandBuilder('destroy').recursive(recursive).force(recursive).target(full_dataset_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to destroy '{full_dataset_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def rename_dataset(old_name: str, new_name: str, recursive: bool = False, force_unmount: bool = False, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZfsCommandBuilder('rename').recursive(recursive).force(force_unmount).targets(old_name, new_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to rename '{old_name}' to '{new_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def set_dataset_property(full_dataset_name: str, prop_name: str, prop_value: str, *, _log_enabled=False, _user_uid=-1, **kwargs):
    # Basic validation
    if not prop_name or '=' in prop_name: raise ZfsCommandError(f"Invalid property name: '{prop_name}'")
    # Value can be empty, but check type? Assume string for now.
    if not isinstance(prop_value, str): raise ZfsCommandError(f"Invalid property value type: {type(prop_value).__name__}")

    builder = ZfsCommandBuilder('set').target(f"{prop_name}={prop_value}").target(full_dataset_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to set property '{prop_name}' for '{full_dataset_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def inherit_dataset_property(full_dataset_name: str, prop_name: str, *, _log_enabled=False, _user_uid=-1, **kwargs):
    if not prop_name: raise ZfsCommandError("Invalid property name: cannot be empty.")
    builder = ZfsCommandBuilder('inherit').target(prop_name).target(full_dataset_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to inherit property '{prop_name}' for '{full_dataset_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def mount_dataset(full_dataset_name: str, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZfsCommandBuilder('mount').target(full_dataset_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    # Allow failure if already mounted or key not loaded (GUI handles key loading separately)
    stderr_lower = stderr.lower()
    if retcode != 0 and not ("already mounted" in stderr_lower or "keystore" in stderr_lower or "keys are not loaded" in stderr_lower):
         raise ZfsCommandError(f"Failed to mount dataset '{full_dataset_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def unmount_dataset(full_dataset_name: str, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZfsCommandBuilder('unmount').target(full_dataset_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    # Allow failure if already unmounted
    if retcode != 0 and "not mounted" not in stderr.lower():
        raise ZfsCommandError(f"Failed to unmount dataset '{full_dataset_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def create_snapshot(full_dataset_name: str, snapshot_name: str, recursive: bool = False, *, _log_enabled=False, _user_uid=-1, **kwargs):
    if '@' in snapshot_name: raise ZfsCommandError("Snapshot name should not contain '@'.")
    full_snapshot_name = f"{full_dataset_name}@{snapshot_name}"
    builder = ZfsCommandBuilder('snapshot').recursive(recursive).target(full_snapshot_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to create snapshot '{full_snapshot_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def destroy_snapshot(full_snapshot_name: str, *, _log_enabled=False, _user_uid=-1, **kwargs):
    if '@' not in full_snapshot_name: raise ZfsCommandError("Invalid snapshot name format (missing '@').")
    builder = ZfsCommandBuilder('destroy').target(full_snapshot_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to destroy snapshot '{full_snapshot_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def rollback_snapshot(full_snapshot_name: str, *, _log_enabled=False, _user_uid=-1, **kwargs):
    if '@' not in full_snapshot_name: raise ZfsCommandError("Invalid snapshot name format (missing '@').")
    # Add -f to force unmount if necessary during rollback, -r to destroy newer snapshots
    builder = ZfsCommandBuilder('rollback').recursive().force().target(full_snapshot_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to rollback to '{full_snapshot_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def clone_snapshot(full_snapshot_name: str, target_dataset_name: str, options: Optional[Dict[str, str]] = None, *, _log_enabled=False, _user_uid=-1, **kwargs):
    if '@' not in full_snapshot_name: raise ZfsCommandError("Invalid snapshot name format (missing '@').")
    builder = ZfsCommandBuilder('clone')
    if options:
        for key, value in options.items():
            if not isinstance(key, str) or not isinstance(value, str): continue
            builder.option(key, value)
    builder.targets(full_snapshot_name, target_dataset_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to clone snapshot '{full_snapshot_name}' to '{target_dataset_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def promote_dataset(full_dataset_name: str, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZfsCommandBuilder('promote').target(full_dataset_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to promote dataset '{full_dataset_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def scrub_pool(pool_name: str, stop: bool = False, *, _log_enabled=False, _user_uid=-1, **kwargs):
    action = "stop" if stop else "start"
    builder = ZpoolCommandBuilder('scrub').stop_scrub(stop).pool(pool_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to {action} scrub for pool '{pool_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def clear_pool_errors(pool_name: str, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZpoolCommandBuilder('clear').pool(pool_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to clear errors for pool '{pool_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def list_importable_pools(search_dirs: Optional[List[str]] = None, *, _log_enabled=False, _user_uid=-1, **kwargs) -> List[Dict[str, str]]:
    builder = ZpoolCommandBuilder('import')
    if search_dirs: builder.search_dirs(search_dirs)

    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    pools = []
    output = stdout.strip(); stderr_lower = stderr.lower()

    # Check stderr *first* for the specific "no pools" message
    if "no pools available for import" in stderr_lower:
        return [] # This is not an error condition

    # Only raise error if return code is non-zero AND it wasn't the "no pools" case
    if retcode != 0:
        raise ZfsCommandError("Failed to search for importable pools.", builder.build(), stderr, retcode)

    # If return code is 0 but output is empty, also return empty list
    if not output:
        return []

    # Parse the output (this format is less standard, be careful)
    current_pool = None
    config_lines = []
    for line in output.split('\n'):
        line_strip = line.strip()
        if not line_strip: continue # Skip empty lines

        match = re.match(r'^\s*(\w+):\s*(.*)$', line) # Match "key: value" lines, allowing leading whitespace
        if match:
            key = match.group(1)
            value = match.group(2).strip()
            if key == 'pool':
                if current_pool: # Save previous pool
                    current_pool['config'] = '\n'.join(config_lines).strip()
                    pools.append(current_pool)
                current_pool = {'name': value, 'id': '', 'state': '', 'action': '', 'config': ''}
                config_lines = []
            elif current_pool:
                if key == 'id': current_pool['id'] = value
                elif key == 'state': current_pool['state'] = value
                elif key == 'action': current_pool['action'] = value
                elif key == 'config': # Start of config block
                     config_lines.append(value) # Add the first line of config
                # else: ignore unknown keys like status, see, etc.
        elif current_pool and config_lines: # If we are in a config block
            config_lines.append(line_strip) # Add raw config line

    if current_pool: # Save the last pool
        current_pool['config'] = '\n'.join(config_lines).strip()
        pools.append(current_pool)

    return pools

@adapt_common_kwargs
def import_pool(pool_name_or_id: Optional[str] = None, new_name: Optional[str] = None, force: bool = False, search_dirs: Optional[List[str]] = None, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZpoolCommandBuilder('import').force(force)
    if search_dirs: builder.search_dirs(search_dirs)

    import_all = False
    if pool_name_or_id:
        builder.pool(pool_name_or_id)
        if new_name: builder.new_name(new_name)
    else:
        builder.import_all()
        import_all = True
        if new_name: raise ZfsCommandError("Cannot specify a new name when importing all pools (-a).")

    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0:
        target = f"pool '{pool_name_or_id}'" if not import_all else "all pools"
        raise ZfsCommandError(f"Failed to import {target}.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def export_pool(pool_name: str, force: bool = False, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZpoolCommandBuilder('export').force(force).pool(pool_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to export pool '{pool_name}'.", builder.build(), stderr, retcode)


# --- Block Device Listing (Using lsblk JSON) ---
@adapt_common_kwargs
def list_block_devices(*, _log_enabled=False, _user_uid=-1, **kwargs) -> List[Dict[str, Any]]:
    """Lists available block devices using lsblk JSON output for robustness."""
    lsblk_path = _find_executable("lsblk", ['/usr/bin', '/bin'])
    if not lsblk_path:
        print(f"DAEMON_CORE: Error: 'lsblk' command not found. Cannot list block devices.", file=sys.stderr)
        return [] # Cannot proceed without lsblk

    all_blk_devices = []
    try:
        # Use JSON output (-J), parsable paths (-p), no dependencies (-b for bytes?), output specific columns
        # PATH, SIZE, TYPE, MOUNTPOINT, FSTYPE, PARTLABEL, LABEL, VENDOR, MODEL, SERIAL, WWN, PKNAME (parent kernel name)
        cmd = [lsblk_path, '-Jpbn', '-o', 'PATH,SIZE,TYPE,MOUNTPOINT,FSTYPE,PARTLABEL,LABEL,VENDOR,MODEL,SERIAL,WWN,PKNAME']
        # Use _run_command for consistency, but disable logging for this internal helper command
        # Passphrase args are irrelevant here
        retcode, stdout, stderr = _run_command(cmd, log_enabled=False, user_uid=_user_uid)
        if retcode != 0:
             # Don't raise ZfsCommandError, maybe just log and return empty
             print(f"DAEMON_CORE: Error running lsblk command (ret={retcode}): {stderr.strip()}", file=sys.stderr)
             return []

        lsblk_data = json.loads(stdout)

        # Identify devices that are actively mounted (non-ZFS, non-swap) or hold critical types
        mounted_or_critical_paths = set()
        critical_fs_types = {'swap', 'crypto_luks', 'lvm2_member'} # Add more if needed

        # Recursive function to process lsblk nodes and determine usability
        def process_node(node, current_parents):
            dev_path = node.get('path')
            dev_type = node.get('type')
            fstype = node.get('fstype')
            mountpoint = node.get('mountpoint')
            pkname = node.get('pkname') # Parent kernel name

            if not dev_path: return # Skip nodes without path

            is_mounted_non_swap = mountpoint and mountpoint != '[SWAP]'
            is_critical_type = fstype and fstype.lower() in critical_fs_types
            is_zfs_member = fstype and fstype.lower() == 'zfs_member'

            # Determine if this device itself is blocked
            is_directly_blocked = is_mounted_non_swap or is_critical_type

            # Check if any parent is blocked (more efficient check later)
            parent_is_blocked = any(p in mounted_or_critical_paths for p in current_parents)

            # If this device is blocked, mark it and its parents
            if is_directly_blocked:
                mounted_or_critical_paths.add(dev_path)
                for p_path in current_parents:
                    mounted_or_critical_paths.add(p_path)

            # Store device info if it's a disk or partition
            if dev_type in ('disk', 'part'):
                 dev_info = {
                    'name': dev_path,
                    'size_bytes': node.get('size'), # Keep as string from lsblk for now
                    'type': dev_type,
                    'mountpoint': mountpoint,
                    'fstype': fstype,
                    'label': node.get('label') or node.get('partlabel'), # Prefer label over partlabel?
                    'vendor': node.get('vendor'),
                    'model': node.get('model'),
                    'serial': node.get('serial'),
                    'wwn': node.get('wwn'),
                    'pkname': pkname,
                    'is_zfs_member': is_zfs_member,
                    'is_directly_blocked': is_directly_blocked,
                    'parent_path': f"/dev/{pkname}" if pkname else None # Precompute parent path
                 }
                 all_blk_devices.append(dev_info)

            # Recursively process children
            new_parents = current_parents + [dev_path]
            if 'children' in node and node['children']:
                for child_node in node['children']:
                    process_node(child_node, new_parents)

        # Start processing from top-level devices
        for top_level_device in lsblk_data.get('blockdevices', []):
             process_node(top_level_device, [])

    except json.JSONDecodeError as e:
         print(f"DAEMON_CORE: Error parsing lsblk JSON output: {e}", file=sys.stderr)
         return []
    except Exception as e:
        print(f"DAEMON_CORE: Unexpected error listing block devices: {e}\n{traceback.format_exc()}", file=sys.stderr)
        return []

    # Filter the collected devices based on collected block status
    eligible_devices = []
    for dev in all_blk_devices:
        # --- Filtering Logic ---
        # 1. Exclude if it's explicitly a ZFS member
        if dev['is_zfs_member']: continue
        # 2. Exclude if it's directly blocked (mounted, critical FS type)
        if dev['is_directly_blocked']: continue
        # 3. Exclude if its parent is blocked
        if dev['parent_path'] and dev['parent_path'] in mounted_or_critical_paths: continue
        # 4. Exclude certain device types we generally don't want (loop, rom)
        if dev['type'] in ('loop', 'rom'): continue

        # --- If it passes all checks, format and add it ---

        # Format size for display
        size_bytes_val = dev.get('size_bytes') # Value from lsblk -b is likely an int
        size_formatted = "?"
        if isinstance(size_bytes_val, int):
            try:
                # Assuming utils.format_size exists and works correctly
                size_formatted = utils.format_size(size_bytes_val)
            except Exception as fmt_e: # Catch potential errors in format_size
                 print(f"DAEMON_CORE: Warning - format_size failed for {size_bytes_val}: {fmt_e}", file=sys.stderr)
                 pass # Keep "?" if formatting fails
        elif size_bytes_val is not None: # Handle unexpected non-int, non-None values
             size_formatted = str(size_bytes_val)

        # Construct display name
        display_label = dev.get('label', '') # label or partlabel was already chosen
        dev['display_name'] = f"{dev['name']} ({size_formatted}) {display_label}".strip()

        # Clean up internal flags before returning
        del dev['is_directly_blocked']
        del dev['parent_path']
        eligible_devices.append(dev)

    eligible_devices.sort(key=lambda x: x.get('name', ''))
    return eligible_devices


# --- POOL EDITING FUNCTIONS ---
@adapt_common_kwargs
def attach_device(pool_name: str, existing_device: str, new_device: str, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZpoolCommandBuilder('attach').pool(pool_name).devices(existing_device, new_device)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to attach '{new_device}' to '{existing_device}' in pool '{pool_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def detach_device(pool_name: str, device: str, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZpoolCommandBuilder('detach').pool(pool_name).device(device)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to detach '{device}' from pool '{pool_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def replace_device(pool_name: str, old_device: str, new_device: Optional[str] = None, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZpoolCommandBuilder('replace').pool(pool_name).device(old_device)
    # new_device can be None (auto-replace from spare) or "" (mark for replacement) or "/dev/..."
    if new_device is not None:
        builder.device(new_device)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to replace '{old_device}'{f' with {new_device}' if new_device is not None else ''} in pool '{pool_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def offline_device(pool_name: str, device: str, temporary: bool = False, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZpoolCommandBuilder('offline').temporary(temporary).pool(pool_name).device(device)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to take '{device}' offline in pool '{pool_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def online_device(pool_name: str, device: str, expand: bool = False, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZpoolCommandBuilder('online').expand(expand).pool(pool_name).device(device)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to bring '{device}' online in pool '{pool_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def add_vdev(pool_name: str, vdev_specs: List[Dict[str, Any]], force: bool = False, *, _log_enabled=False, _user_uid=-1, **kwargs):
    if not isinstance(vdev_specs, list):
        raise ZfsCommandError(f"Daemon received invalid vdev_specs for add_vdev: Expected list, got {type(vdev_specs).__name__}")
    if not vdev_specs:
        raise ZfsCommandError(f"No vdev specifications provided to add to pool '{pool_name}'.")

    # Validate specs first
    validated_specs = [_validate_vdev_spec(spec, f"add_vdev '{pool_name}'") for spec in vdev_specs]

    builder = ZpoolCommandBuilder('add').force(force).pool(pool_name)
    builder.add_vdev_specs(validated_specs, f"add_vdev '{pool_name}'")

    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to add vdev(s) to pool '{pool_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def remove_vdev(pool_name: str, device_or_vdev_id: str, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZpoolCommandBuilder('remove').pool(pool_name).device(device_or_vdev_id)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    stderr_lower = stderr.lower()
    # Don't raise error immediately if busy or I/O error, just report info
    if retcode != 0 and not ("is busy" in stderr_lower or "i/o error" in stderr_lower):
        raise ZfsCommandError(f"Failed to remove '{device_or_vdev_id}' from pool '{pool_name}'. Check limitations.", builder.build(), stderr, retcode)
    elif "is busy" in stderr_lower or "i/o error" in stderr_lower:
        # Log info, but don't treat as success? The operation might be pending.
        # Maybe return a specific status or the stderr? For now, just log.
        print(f"DAEMON_CORE: Info: Removal of '{device_or_vdev_id}' may be pending due to device activity or errors.", file=sys.stderr)
        # Consider returning stderr here if the caller needs to know about the pending state.

@adapt_common_kwargs
def split_pool(pool_name: str, new_pool_name: str, options: Optional[Dict[str, Any]] = None, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZpoolCommandBuilder('split')
    if options:
        builder.altroot(options.get('altroot')) # Handles None safely
        builder.dry_run(options.get('dry_run', False))
        pool_props = options.get('pool_props')
        if isinstance(pool_props, dict):
            for prop_key, prop_val in pool_props.items(): builder.pool_option(prop_key, prop_val)
        fs_props = options.get('fs_props')
        if isinstance(fs_props, dict):
            for prop_key, prop_val in fs_props.items(): builder.fs_option(prop_key, prop_val)

    builder.pools(pool_name, new_pool_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to split pool '{pool_name}' into '{new_pool_name}'. Check requirements.", builder.build(), stderr, retcode)


# --- Encryption Key Management Functions ---
@adapt_common_kwargs
def load_key(dataset_name: str, recursive: bool = False, key_location: Optional[str] = None, *, _log_enabled=False, _user_uid=-1, passphrase: Optional[str] = None, **kwargs):
    builder = ZfsCommandBuilder('load-key').recursive(recursive)
    builder.set_passphrase(passphrase)
    # Only add -L if key_location is provided and not 'prompt' (which is implicit for passphrase)
    if key_location and key_location != 'prompt':
        builder.keylocation(key_location)
    builder.target(dataset_name)

    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    stderr_lower = stderr.lower()
    if retcode != 0:
        if "keys are already loaded" in stderr_lower:
            print(f"DAEMON_CORE: Info: Key(s) for {dataset_name} already loaded.", file=sys.stderr) # Not an error
        else:
            raise ZfsCommandError(f"Failed to load key for '{dataset_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def unload_key(dataset_name: str, recursive: bool = False, *, _log_enabled=False, _user_uid=-1, **kwargs):
    builder = ZfsCommandBuilder('unload-key').recursive(recursive).target(dataset_name)
    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    stderr_lower = stderr.lower()
    if retcode != 0:
        if "keys are already unloaded" in stderr_lower or "dataset is not encrypted" in stderr_lower:
            print(f"DAEMON_CORE: Info: Key(s) for {dataset_name} already unloaded or dataset not encrypted.", file=sys.stderr) # Not an error
        else:
            raise ZfsCommandError(f"Failed to unload key for '{dataset_name}'.", builder.build(), stderr, retcode)

@adapt_common_kwargs
def change_key(dataset_name: str, load_key_flag: bool = False, recursive: bool = False, options: Optional[Dict[str, str]] = None, *, _log_enabled=False, _user_uid=-1, passphrase_change_info: Optional[str] = None, **kwargs):
    """
    Handles changing encryption keys.
    Passphrase changes require `passphrase_change_info` (old\nnew or just new).
    Keyfile changes require options={'keyformat': 'raw/hex', 'keylocation': 'file://...'}.
    """
    builder = ZfsCommandBuilder('change-key').loadkey(load_key_flag).recursive(recursive)
    builder.set_passphrase_change(passphrase_change_info) # Pass change info

    final_options = options.copy() if options else {}

    if passphrase_change_info:
        # If changing to passphrase, ensure options reflect that
        print("DAEMON_CORE: change_key: Detected passphrase change input.", file=sys.stderr)
        if final_options.get('keyformat') != 'passphrase':
            print("DAEMON_CORE: change_key: Ensuring '-o keyformat=passphrase' for passphrase change.", file=sys.stderr)
            final_options['keyformat'] = 'passphrase'
        if final_options.get('keylocation') == 'prompt':
            print("DAEMON_CORE: change_key: Removing redundant '-o keylocation=prompt' for passphrase change.", file=sys.stderr)
            if 'keylocation' in final_options: del final_options['keylocation']
    elif final_options:
        # If changing to keyfile, validate options
        print(f"DAEMON_CORE: change_key: Detected options for potential keyfile change: {final_options}", file=sys.stderr)
        if not final_options.get('keylocation', '').startswith('file://'):
             raise ZfsCommandError(f"Invalid options for keyfile change: 'keylocation' must be a file URI (file:///...).", builder.build())
        if final_options.get('keyformat') not in ['raw', 'hex']:
             raise ZfsCommandError(f"Invalid options for keyfile change: 'keyformat' must be 'raw' or 'hex'.", builder.build())

    # Apply relevant options
    for key, value in final_options.items():
        if not isinstance(key, str) or not isinstance(value, str): continue
        if key in ['keyformat', 'keylocation', 'pbkdf2iters']:
             builder.option(key, value)
        else: print(f"DAEMON_CORE: Warning: Ignoring unknown option '{key}' during change-key.")

    builder.target(dataset_name)
    print(f"DAEMON_CORE: change_key: Final command parts: {builder.build()}", file=sys.stderr)
    print(f"DAEMON_CORE: change_key: Final input_data: {'[hidden passphrase]' if passphrase_change_info else '[none]'}", file=sys.stderr)

    retcode, stdout, stderr = builder.run(_log_enabled=_log_enabled, _user_uid=_user_uid)
    if retcode != 0: raise ZfsCommandError(f"Failed to change key for '{dataset_name}'. Check logs/permissions.", builder.build(), stderr, retcode)


# --- COMMAND_MAP ---
# Maps action names (used by zfs_manager) to the core functions
COMMAND_MAP = {
    # Getters
    "list_pools": list_pools,
    "get_pool_status": get_pool_status,
    "list_all_datasets_snapshots": list_all_datasets_snapshots,
    "get_all_properties_with_sources": get_all_properties_with_sources,
    "list_importable_pools": list_importable_pools,
    "list_block_devices": list_block_devices,
    # Pool Actions
    "create_pool": create_pool,
    "destroy_pool": destroy_pool,
    "import_pool": import_pool,
    "export_pool": export_pool,
    "scrub_pool": scrub_pool,
    "clear_pool_errors": clear_pool_errors,
    "split_pool": split_pool,
    # Dataset/Volume Actions
    "create_dataset": create_dataset, # Handles volumes via is_volume flag
    "destroy_dataset": destroy_dataset,
    "rename_dataset": rename_dataset,
    "set_dataset_property": set_dataset_property,
    "inherit_dataset_property": inherit_dataset_property,
    "mount_dataset": mount_dataset,
    "unmount_dataset": unmount_dataset,
    "promote_dataset": promote_dataset,
    # Snapshot Actions
    "create_snapshot": create_snapshot,
    "destroy_snapshot": destroy_snapshot,
    "rollback_snapshot": rollback_snapshot,
    "clone_snapshot": clone_snapshot,
    # Pool Editing Actions
    "attach_device": attach_device,
    "detach_device": detach_device,
    "replace_device": replace_device,
    "offline_device": offline_device,
    "online_device": online_device,
    "add_vdev": add_vdev,
    "remove_vdev": remove_vdev,
    # Encryption Actions
    "load_key": load_key,
    "unload_key": unload_key,
    "change_key": change_key,
    # Add new actions here...
    # "rename_pool": rename_pool, # Example for future
}

# --- END OF FILE zfs_manager_core.py ---
