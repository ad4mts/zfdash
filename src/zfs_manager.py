# --- START OF FILE src/zfs_manager.py (Refactored for Transport IPC) ---

import json
import os
import sys
import threading
import queue
import select
import time
import subprocess # For Popen type hint
from typing import List, Dict, Tuple, Optional, Any
import traceback # Import traceback for error printing

# Import IPC transport
from ipc_client import LineBufferedTransport

# Import models and utils needed by the GUI code that USES this manager
from models import Pool, Dataset, Snapshot, ZfsObject, find_child
import utils # For parsing/formatting in helper functions here

# Import config manager to get user settings (like logging pref)
try:
    import config_manager
    import constants
except ImportError:
     print("MANAGER_CLIENT: Warning: config_manager not found.", file=sys.stderr)
     # Define fallback
     class MockConfigManager:
         def get_setting(self, key, default): return False
         def get_log_file_path(self): return "mock_zfdash_client.log"
         def get_viewer_log_file_path(self): return "mock_zfdash_client.log"
     config_manager = MockConfigManager()
     # Mock constants module
     class MockConstants:
         DEFAULT_LOGGING_ENABLED = False
     constants = MockConstants()

# Removed SOCKET_NAME, SOCKET_PATH
# Removed _get_dynamic_socket_path function

# --- Error Class (Unchanged) ---
class ZfsCommandError(Exception):
    """Represents an error reported by the ZFS daemon."""
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details
    def __str__(self):
        if self.details:
            details_str = str(self.details)
            # Limit details length in string representation
            if len(details_str) > 500: details_str = details_str[:500] + "..."
            return f"{super().__str__()} (Details: {details_str})"
        return super().__str__()

# --- Communication Error Class ---
class ZfsClientCommunicationError(Exception):
    """Represents an error in the client-daemon communication itself."""
    pass

# --- ZFS Manager Client Class ---
class ZfsManagerClient:
    def __init__(self, daemon_process: subprocess.Popen, transport: LineBufferedTransport, owns_daemon: bool = True):
        """
        Initialize the client with the running daemon process and IPC transport.
        
        Args:
            daemon_process: The daemon subprocess.Popen object (can be None for external daemons)
            transport: LineBufferedTransport for JSON-line protocol communication
            owns_daemon: If True, this client will shut down the daemon on close.
                        Set to False when connecting to an external/persistent daemon.
        """
        self.daemon_process = daemon_process
        self.transport = transport
        self.owns_daemon = owns_daemon
        self.pending_requests: Dict[int, queue.Queue] = {}
        self.request_lock = threading.Lock()
        self.request_id_counter = 0
        self.shutdown_event = threading.Event()
        self.reader_thread: Optional[threading.Thread] = None
        self._communication_error = None # To store fatal reader errors

        if transport is None:
            raise ValueError("Invalid transport provided.")

        print(f"MANAGER_CLIENT: Initialized with {transport.get_type()} transport (owns_daemon={owns_daemon})", file=sys.stderr)
        print("MANAGER_CLIENT: Starting reader thread...", file=sys.stderr)
        self.reader_thread = threading.Thread(target=self._reader_thread_target, daemon=True)
        self.reader_thread.start()

    def _get_next_request_id(self) -> int:
        with self.request_lock:
            self.request_id_counter += 1
            return self.request_id_counter

    def _reader_thread_target(self):
        """Target function for the thread reading responses from the daemon via transport."""
        print("MANAGER_CLIENT: Reader thread started.", file=sys.stderr)
        
        # Capture transport locally to avoid race conditions during reconnect
        # If self.transport is replaced by reconnect(), this thread should stick to the old one (which will be closed) and exit
        transport = self.transport
        
        while not self.shutdown_event.is_set():
            try:
                # Check if there's data to read using select with a short timeout
                # This allows checking the shutdown_event periodically
                try:
                    ready_to_read, _, _ = select.select([transport.fileno()], [], [], constants.READER_SELECT_TIMEOUT)
                except (ValueError, OSError):
                    # Handle case where file descriptor is closed/invalid
                    if not self.shutdown_event.is_set():
                        # Only log if we haven't been replaced (if self.transport != transport, we expect this close)
                        if self.transport == transport:
                            print("MANAGER_CLIENT: Transport file descriptor invalid/closed.", file=sys.stderr)
                    break

                if not ready_to_read:
                    continue # Timeout, loop back to check shutdown_event

                # Data is available, read a line
                line_bytes = transport.receive_line()

                if not line_bytes:
                    # EOF reached - daemon likely exited or closed connection
                    # Only report error if we are still the active transport
                    if self.transport == transport:
                         print("MANAGER_CLIENT: Reader thread detected EOF. Daemon likely closed connection.", file=sys.stderr)
                         self._communication_error = ZfsClientCommunicationError("Daemon connection closed (EOF).")
                    break # Exit reader loop

                line_str = line_bytes.decode('utf-8', errors='replace').strip()
                #print(f"MANAGER_CLIENT: Reader received: {line_str[:200]}{'...' if len(line_str)>200 else ''}", file=sys.stderr) # Log received data

                if not line_str:
                    continue # Skip empty lines

                response = None
                try:
                    response = json.loads(line_str)
                    if not isinstance(response, dict):
                        raise ValueError("Response is not a JSON object")
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"MANAGER_CLIENT: Reader error parsing JSON: {e}. Line: '{line_str}'", file=sys.stderr)
                    continue # Skip this line

                # --- Process Response --- #
                request_id = response.get("meta", {}).get("request_id")
                if request_id is None:
                    print(f"MANAGER_CLIENT: Warning: Received response without request_id: {response}", file=sys.stderr)
                    continue

                response_queue = None
                with self.request_lock:
                    response_queue = self.pending_requests.pop(request_id, None)

                if response_queue:
                    try:
                        response_queue.put_nowait(response)
                    except queue.Full:
                        print(f"MANAGER_CLIENT: Warning: Response queue full for request_id {request_id}", file=sys.stderr)
                else:
                    # This else belongs to the 'if response_queue:'
                    print(f"MANAGER_CLIENT: Warning: Received response for unknown/timed-out request_id {request_id}: {response}", file=sys.stderr)

            except (OSError, BrokenPipeError, ValueError) as e:
                # This except belongs to the outer try block started at the beginning of the loop
                if not self.shutdown_event.is_set(): # Avoid error message during clean shutdown
                    # Verify we are still the active transport
                    if self.transport == transport:
                         print(f"MANAGER_CLIENT: Reader thread pipe error: {e}", file=sys.stderr)
                         self._communication_error = ZfsClientCommunicationError(f"Pipe communication error: {e}")
                break # Exit reader loop on pipe error

            except Exception as e:
                 # This except handles unexpected errors within the main loop's try block
                 if not self.shutdown_event.is_set():
                     print(f"MANAGER_CLIENT: Reader thread unexpected error: {e}", file=sys.stderr)
                     traceback.print_exc(file=sys.stderr)
                     self._communication_error = ZfsClientCommunicationError(f"Unexpected reader error: {e}")
                 break # Exit reader loop on unexpected error

        # --- Reader Thread Cleanup (Outside the while loop) ---
        print("MANAGER_CLIENT: Reader thread exiting.", file=sys.stderr)
        # Notify any pending requests about the communication failure - only if we are the active thread
        if self.transport == transport:
            self._notify_pending_of_error()

    def _notify_pending_of_error(self):
        """Notify all pending requests about a communication failure."""
        error_response = self._communication_error or ZfsClientCommunicationError("Daemon communication failed.")
        with self.request_lock:
            # Correct indentation for the loop
            for req_id, response_queue in self.pending_requests.items():
                try:
                    response_queue.put_nowait(error_response) # Send error object
                except queue.Full:
                    print(f"MANAGER_CLIENT: Warning: Response queue full when notifying error for request_id {req_id}", file=sys.stderr)
            self.pending_requests.clear() # Clear pending requests after notification

    def _send_request(self, command: str, *args, timeout: float = constants.CLIENT_REQUEST_TIMEOUT, **kwargs) -> Dict[str, Any]:
        """Sends a command to the daemon and waits for a response."""
        if self.shutdown_event.is_set() or self._communication_error:
            raise self._communication_error or ZfsClientCommunicationError("Client is shut down or in error state.")

        request_id = self._get_next_request_id()
        response_queue = queue.Queue(maxsize=1)

        # Correct indentation for request_meta and request_dict
        request_meta = {
            "request_id": request_id,
            "log_enabled": config_manager.get_setting('logging_enabled', constants.DEFAULT_LOGGING_ENABLED),
            "user_uid": os.getuid() if hasattr(os, 'getuid') else -1
        }
        request_dict = {
            "command": command,
            "args": args,
            "kwargs": kwargs,
            "meta": request_meta
        }

        try:
            # Correct indentation for this block
            request_json_bytes = (json.dumps(request_dict) + '\n').encode('utf-8')

            with self.request_lock:
                if self.shutdown_event.is_set() or self._communication_error:
                    raise self._communication_error or ZfsClientCommunicationError("Client is shut down or in error state during request.")
                self.pending_requests[request_id] = response_queue

            #print(f"MANAGER_CLIENT: Sending ReqID={request_id}, Cmd={command}", file=sys.stderr)
            self.transport.send_line(request_json_bytes)

        except (OSError, BrokenPipeError) as e:
            # Correct indentation for except blocks
            print(f"MANAGER_CLIENT: Error writing to daemon: {e}", file=sys.stderr)
            self._communication_error = ZfsClientCommunicationError(f"Failed to write to daemon: {e}")
            with self.request_lock:
                self.pending_requests.pop(request_id, None)
            self.shutdown_event.set()
            self._notify_pending_of_error()
            raise self._communication_error from e
        except Exception as e:
            print(f"MANAGER_CLIENT: Unexpected error sending request: {e}", file=sys.stderr)
            with self.request_lock:
                self.pending_requests.pop(request_id, None)
            self._communication_error = ZfsClientCommunicationError(f"Unexpected error sending request: {e}")
            self.shutdown_event.set()
            self._notify_pending_of_error()
            raise self._communication_error from e

        # --- Wait for Response --- #
        result = None # Define result outside try to ensure it's accessible in finally
        try:
            # Correct indentation
            result = response_queue.get(timeout=timeout)

            if isinstance(result, Exception):
                raise result
            elif isinstance(result, dict):
                if result.get("status") == "error":
                    error_msg = result.get("error", "Unknown daemon error")
                    details = result.get("details")
                    raise ZfsCommandError(error_msg, details)
                else:
                    # The return needs to be here, inside the try block
                    return result # Success
            else:
                 # This else belongs to the inner if/elif chain
                 raise ZfsClientCommunicationError(f"Received unexpected item type from reader thread: {type(result)}")

        except queue.Empty:
            # Correct indentation
            print(f"MANAGER_CLIENT: Timeout ({timeout}s) waiting for response to ReqID={request_id}, Cmd={command}", file=sys.stderr)
            # No need to pop here, finally block handles it
            raise TimeoutError(f"Timeout waiting for daemon response for '{command}'.")
        finally:
            # Correct indentation and structure for finally
            # This ensures the request is removed even if errors occur during processing
            with self.request_lock:
                self.pending_requests.pop(request_id, None)
            # No return statement needed here, the return is in the try block on success

    def get_all_zfs_data(self) -> List[Pool]:
        """Fetches all data via the daemon and builds the hierarchy."""
        # Correct indentation for the whole method
        timeout = constants.CLIENT_ACTION_TIMEOUT
        try:
            response_pools = self._send_request("list_pools", timeout=timeout)
            response_items = self._send_request("list_all_datasets_snapshots", timeout=timeout)
        except (ZfsCommandError, ZfsClientCommunicationError, TimeoutError) as e:
            raise ZfsCommandError(f"Failed initial data fetch: {e}") from e

        # Correct indentation
        pools_raw_data = response_pools.get("data", [])
        items_raw_data = response_items.get("data", [])
        pool_statuses = {}
        pool_vdev_trees = {}  # Structured VDEV trees from zpool status -j
        status_fetch_errors = []

        # Fetch pool statuses and VDEV trees individually (correct indentation)
        for pool_props in pools_raw_data:
            pool_name = pool_props.get("name")
            if not pool_name: continue
            try:
                # Correct indentation inside the try
                response_status = self._send_request("get_pool_status", pool_name, timeout=timeout)
                pool_statuses[pool_name] = response_status.get("data", "Error: Status data missing")
            except (ZfsCommandError, ZfsClientCommunicationError, TimeoutError) as e:
                 # Correct indentation for except
                 status_fetch_errors.append(f"Pool '{pool_name}': {e}")
                 pool_statuses[pool_name] = f"Error fetching status: {e}"
            except Exception as e:
                 # Correct indentation for except
                 status_fetch_errors.append(f"Pool '{pool_name}': Exception fetching status: {e}")
                 pool_statuses[pool_name] = f"Exception fetching status: {e}"
            
            # Fetch structured VDEV tree (new)
            try:
                response_structure = self._send_request("get_pool_status_structure", pool_name, timeout=timeout)
                vdev_data = response_structure.get("data", {})
                # Extract the pool's vdev_tree from the response
                pool_vdev_trees[pool_name] = vdev_data.get("pools", {}).get(pool_name, {}).get("vdev_tree", {})
            except Exception as e:
                 # Non-fatal: log but continue - GUI/WebUI can fall back to raw text
                 print(f"MANAGER_CLIENT: Warning - Failed to get vdev_tree for '{pool_name}': {e}", file=sys.stderr)
                 pool_vdev_trees[pool_name] = {}

        # Correct indentation
        if status_fetch_errors:
            print(f"MANAGER_CLIENT: Warning - Errors fetching pool status:\n" + "\n".join(status_fetch_errors), file=sys.stderr)

        # --- Build Objects and Hierarchy --- (Correct indentation)
        flat_list: List[ZfsObject] = []
        pool_objects = {}
        for props in pools_raw_data: # Create Pools
            pool_name = props.get('name','?')
            pool = Pool(name=pool_name, health=props.get('health','?'), size=utils.parse_size(props.get('size')), alloc=utils.parse_size(props.get('alloc')), free=utils.parse_size(props.get('free')), frag=props.get('frag','-'), cap=props.get('cap','-'), dedup=props.get('dedup','?'), guid=props.get('guid',''), properties=props, status_details=pool_statuses.get(pool_name, "Status unavailable"), vdev_tree=pool_vdev_trees.get(pool_name, {}))
            flat_list.append(pool); pool_objects[pool_name] = pool
        for props in items_raw_data: # Create Datasets/Snapshots
            item_type = props.get('type'); name = props.get('name', '?')
            # Correct indentation for this check
            if not name or name == '?': continue
            if item_type == 'snapshot':
                # Correct indentation for snapshot block
                ds_name, s_name = (name.rsplit('@', 1) + [''])[:2] if '@' in name else ('', '')
                if not ds_name: continue
                p_name = ds_name.split('/')[0] if '/' in ds_name else ds_name
                snap = Snapshot(name=s_name, pool_name=p_name, dataset_name=ds_name, used=utils.parse_size(props.get('used')), referenced=utils.parse_size(props.get('referenced')), creation_time=props.get('creation','-'), properties=props)
                # Correct indentation for these lines
                snap.obj_type = 'snapshot'
                snap.properties['full_snapshot_name'] = name
                flat_list.append(snap)
            elif item_type in ['filesystem', 'volume']:
                # Correct indentation for dataset/volume block
                p_name = name.split('/')[0] if '/' in name else name
                encryption_prop = props.get('encryption', 'off')
                is_encrypted = encryption_prop not in ('off', '-', None)
                ds = Dataset(name=name, pool_name=p_name, used=utils.parse_size(props.get('used')), available=utils.parse_size(props.get('available')), referenced=utils.parse_size(props.get('referenced')), mountpoint=props.get('mountpoint','-'), obj_type='volume' if item_type == 'volume' else 'dataset', properties=props, is_encrypted=is_encrypted, is_mounted=(props.get('mounted', 'no') == 'yes'))
                flat_list.append(ds)

        # Correct indentation for the return
        return build_zfs_hierarchy(flat_list)

    def get_all_properties_with_sources(self, obj_name: str) -> Tuple[bool, Dict[str, Dict[str, str]], str]:
        try:
            response = self._send_request("get_all_properties_with_sources", obj_name)
            # Assuming success if no exception was raised by _send_request
            return True, response.get("data", {}), ""
        except ZfsCommandError as e:
            return False, {}, str(e)
        except (ZfsClientCommunicationError, TimeoutError) as e:
            return False, {}, f"Communication error: {e}"

    def _run_action(self, command: str, *args, success_msg: str, **kwargs) -> Tuple[bool, str]:
        """
        Helper method to run an action command via daemon.
        Returns (True, success_msg) on success, potentially appending daemon data.
        Raises ZfsCommandError or ZfsClientCommunicationError on failure.
        """
        # Determine appropriate timeout (can be passed via kwargs)
        timeout = kwargs.pop('timeout', constants.CLIENT_ACTION_TIMEOUT) # Default long timeout for client-side actions

        response = self._send_request(command, *args, timeout=timeout, **kwargs)
        # Success is implied if _send_request didn't raise an exception
        daemon_data = response.get("data")
        return_msg = f"{success_msg}{f': {daemon_data}' if daemon_data else ''}"
        return True, return_msg

    # --- Actions (Examples - adapt others similarly) ---
    # if possible use this function in order to not create unnecessery complexity!!!
    def execute_generic_action(self, command: str, success_msg: str, *args, **kwargs) -> Tuple[bool, str]:
        """Generic action executor using _run_action."""
        # Pass args and kwargs through
        # Timeout can be passed in kwargs if needed, otherwise _run_action default applies
        return self._run_action(command, *args, success_msg=success_msg, **kwargs)

    def list_importable_pools(self, search_dirs: Optional[List[str]] = None) -> Tuple[bool, str, List[Dict[str, str]]]:
        try:
            kwargs = {"search_dirs": search_dirs} if search_dirs is not None else {}
            response = self._send_request("list_importable_pools", **kwargs, timeout=constants.LIST_IMPORTABLE_POOLS_TIMEOUT)
            return True, "", response.get("data", [])
        except ZfsCommandError as e:
            return False, str(e), []
        except (ZfsClientCommunicationError, TimeoutError) as e:
            return False, f"Communication error: {e}", []

    def list_block_devices(self) -> Dict[str, Any]:
        """Lists available block devices for ZFS pool creation.
        
        Returns:
            Dict with 'all_devices', 'devices', 'platform' keys.
            On error, dict includes 'error' key with message.
        """
        try:
            response = self._send_request("list_block_devices", timeout=constants.CLIENT_REQUEST_TIMEOUT)
            data = response.get("data", {})
            # Ensure we always return a proper structure
            if isinstance(data, dict):
                return data
            # Handle unexpected response format gracefully
            return {'all_devices': [], 'devices': data if isinstance(data, list) else [], 'platform': 'unknown'}
        except (ZfsCommandError, ZfsClientCommunicationError, TimeoutError) as e:
            print(f"MANAGER_CLIENT: Error listing block devices: {e}", file=sys.stderr)
            return {'error': str(e), 'all_devices': [], 'devices': [], 'platform': 'unknown'}

    def shutdown_daemon(self) -> Tuple[bool, str]:
        """Attempts to send the shutdown command to the daemon."""
        # Use a short timeout for the shutdown command itself
        try:
            # Send the command but don't necessarily wait for a reply if the daemon
            # exits quickly. The `close` method handles actual process termination.
            _ = self._send_request("shutdown_daemon", timeout=constants.SHUTDOWN_REQUEST_TIMEOUT)
            # Even if _send_request raises TimeoutError, we might consider it success
            # if the goal is just to signal shutdown.
            return True, "Shutdown command sent."
        except TimeoutError:
            # Daemon didn't reply quickly, but might be shutting down.
            return True, "Shutdown command sent (timeout waiting for reply)."
        except (ZfsCommandError, ZfsClientCommunicationError) as e:
            # Daemon might already be dead or communication failed
            return False, f"Error sending shutdown command: {e}"

    def is_connection_healthy(self) -> bool:
        """
        Check if daemon connection is still alive.
        
        Returns True if connection appears healthy, False otherwise.
        This is useful for socket mode where the daemon can be shut down externally.
        """
        # If shutdown already triggered or communication error occurred
        if self.shutdown_event.is_set() or self._communication_error:
            return False
        # Check if reader thread is still alive (it exits on EOF/errors)
        if self.reader_thread and not self.reader_thread.is_alive():
            return False
        return True

    def get_connection_error(self) -> Optional[str]:
        """
        Get the current connection error message, if any.
        
        Returns the error message string, or None if no error.
        """
        if self._communication_error:
            return str(self._communication_error)
        if self.reader_thread and not self.reader_thread.is_alive() and not self.shutdown_event.is_set():
            return "Daemon connection lost (reader thread exited)"
        return None

    def reconnect(self) -> Tuple[bool, str]:
        """
        Attempt to reconnect to an existing socket daemon.
        
        This is only applicable in socket mode (owns_daemon=False).
        In pipe mode, reconnection is not possible.
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        if self.owns_daemon:
            return False, "Reconnection not available in pipe mode. Please restart the application."
        
        # print(f"MANAGER_CLIENT: Attempting to reconnect to daemon...", file=sys.stderr)
        
        try:
            # Use abstracted connect function
            from ipc_client import connect_to_daemon
            
            # Try to connect to existing daemon
            new_transport = connect_to_daemon()
            
            # Close old transport if any
            if self.transport:
                try:
                    self.transport.close()
                except Exception:
                    pass
            
            # Reset state
            self.transport = new_transport
            self._communication_error = None
            self.shutdown_event.clear()
            
            # Clear pending requests (they won't get responses now)
            with self.request_lock:
                self.pending_requests.clear()
            
            # Start new reader thread
            if self.reader_thread and self.reader_thread.is_alive():
                # Old thread should exit on its own when transport was closed
                pass
            
            self.reader_thread = threading.Thread(target=self._reader_thread_target, daemon=True)
            self.reader_thread.start()
            
            print(f"MANAGER_CLIENT: Successfully reconnected to daemon.", file=sys.stderr)
            return True, "Successfully reconnected to daemon."
            
        except FileNotFoundError as e:
            error_msg = f"Daemon socket not found. Please launch the daemon first:\n  zfdash --launch-daemon"
            # print(f"MANAGER_CLIENT: Reconnect failed - {error_msg}", file=sys.stderr)
            return False, error_msg
            
        except RuntimeError as e:
            error_msg = f"Failed to connect to daemon: {e}"
            # print(f"MANAGER_CLIENT: Reconnect failed - {error_msg}", file=sys.stderr)
            return False, error_msg
            
        except Exception as e:
            error_msg = f"Unexpected error during reconnection: {e}"
            # print(f"MANAGER_CLIENT: Reconnect failed - {error_msg}", file=sys.stderr)
            return False, error_msg

    def close(self):
        """Shuts down the reader thread, closes pipes, and shuts down the daemon."""
        #print("MANAGER_CLIENT: Initiating shutdown...", file=sys.stderr)
        if self.shutdown_event.is_set():
            #print("MANAGER_CLIENT: Already shutting down.", file=sys.stderr)
            return

        # 1. Attempt graceful shutdown command (ONLY if we own the daemon)
        if self.owns_daemon and self.daemon_process:
            try:
                 self.shutdown_daemon() # Try sending the command
            except Exception as e:
                 print(f"MANAGER_CLIENT: Ignored error during optional shutdown command: {e}", file=sys.stderr)
            time.sleep(0.5) # Give daemon a moment to process shutdown
        else:
            print("MANAGER_CLIENT: External daemon, skipping shutdown command.", file=sys.stderr)

        # 2. Signal reader thread to stop (fix: NOW set this, after sending shutdown request or it fails)
        self.shutdown_event.set()

        # 3. Close transport (this signals EOF/broken connection to daemon/reader)
        print("MANAGER_CLIENT: Closing transport...", file=sys.stderr)
        if self.transport:
            try: 
                self.transport.close()
            except OSError as e: 
                print(f"MANAGER_CLIENT: Error closing transport: {e}", file=sys.stderr)
            self.transport = None

        # 4. Join reader thread
        if self.reader_thread and self.reader_thread.is_alive():
            # Only join if we are not calling from the reader thread itself
            if threading.current_thread() != self.reader_thread:
                print("MANAGER_CLIENT: Joining reader thread...", file=sys.stderr)
                self.reader_thread.join(timeout=constants.THREAD_JOIN_TIMEOUT)
                if self.reader_thread.is_alive():
                    print("MANAGER_CLIENT: Warning: Reader thread did not exit cleanly.", file=sys.stderr)
            else:
                print("MANAGER_CLIENT: Skipping join (called from reader thread).", file=sys.stderr)
        self.reader_thread = None

        # 5. Terminate and wait for daemon process (last resort / webui or gui must be root)
        # Note: terminate()/kill() may fail if daemon runs as root and we're a user process.
        # That's expected - we rely on shutdown_daemon IPC command above for graceful exit.
        # This fallback only works in Docker (where WebUI is also root).
        if self.owns_daemon and self.daemon_process:
            if self.daemon_process.poll() is None:
                print(f"MANAGER_CLIENT: Terminating daemon process (PID: {self.daemon_process.pid})...", file=sys.stderr)
                try:
                    self.daemon_process.terminate() # Send SIGTERM
                    self.daemon_process.wait(timeout=constants.TERMINATE_TIMEOUT) # Wait for termination
                    print(f"MANAGER_CLIENT: Daemon process terminated (Exit code: {self.daemon_process.returncode}).", file=sys.stderr)
                except subprocess.TimeoutExpired:
                    print("MANAGER_CLIENT: Timeout waiting for daemon termination, attempting kill...", file=sys.stderr)
                    try:
                        self.daemon_process.kill() # Send SIGKILL
                        self.daemon_process.wait(timeout=constants.KILL_TIMEOUT)
                        print(f"MANAGER_CLIENT: Daemon process killed (Exit code: {self.daemon_process.returncode}).", file=sys.stderr)
                    except Exception as e:
                        print(f"MANAGER_CLIENT: Error killing daemon process: {e}", file=sys.stderr)
                except Exception as e:
                     print(f"MANAGER_CLIENT: Error terminating daemon process: {e}", file=sys.stderr)
            else:
                print(f"MANAGER_CLIENT: Daemon process already exited (Exit code: {self.daemon_process.returncode}).", file=sys.stderr)
        self.daemon_process = None

        print("MANAGER_CLIENT: Shutdown complete.", file=sys.stderr)

    # --- ADD: Method to Change WebUI Password ---
    def change_webui_password(self, username: str, new_password: str) -> Tuple[bool, str]:
        """
        Sends a request to the daemon to change the WebUI password.
        Args:
            username: The username whose password needs changing.
            new_password: The new PLAIN TEXT password.
        Returns:
            Tuple[bool, str]: (success status, message)
        """
        print(f"MANAGER_CLIENT: Requesting password change for user '{username}'...", file=sys.stderr)
        kwargs = {
            "username": username,
            "new_password": new_password
        }
        # Use the generic action runner
        return self._run_action(
            command="change_password",
            success_msg="Password change request sent successfully.",
            **kwargs
        )
    # --- END ADD ---


# --- Static Hierarchy Builder (Fix AttributeError) ---
def build_zfs_hierarchy(flat_list: List[ZfsObject]) -> List[Pool]:
    """Builds the parent-child relationships from a flat list of ZFS objects."""
    pools = [item for item in flat_list if isinstance(item, Pool)]

    # Map full path -> object for Datasets and Snapshots
    # Map pool name -> Pool object separately
    items_by_path: Dict[str, ZfsObject] = {}
    pools_by_name: Dict[str, Pool] = {p.name: p for p in pools}

    for item in flat_list:
        if isinstance(item, Dataset):
            items_by_path[item.name] = item # Use full dataset path (e.g., "pool/data")
        elif isinstance(item, Snapshot):
            full_snap_name = item.properties.get('full_snapshot_name') # e.g., "pool/data@snap"
            if full_snap_name:
                items_by_path[full_snap_name] = item
            else:
                # Fallback if property missing (shouldn't happen)
                constructed_name = f"{item.dataset_name}@{item.name}"
                items_by_path[constructed_name] = item
                print(f"WARNING: Snapshot {constructed_name} missing 'full_snapshot_name' property.", file=sys.stderr)


    # Link items
    for item in flat_list:
        item.parent = None # Reset parent link initially
        parent_obj: Optional[ZfsObject] = None
        parent_key = None # The name/path used to find the parent

        if isinstance(item, Pool):
            continue # Pools are top-level

        elif isinstance(item, Dataset):
            item.children.clear()
            item.snapshots.clear()
            if '/' in item.name:
                # Nested dataset: parent is the dataset path before the last '/'
                parent_key = item.name.rsplit('/', 1)[0]
                parent_obj = items_by_path.get(parent_key) # Lookup parent dataset by path
            else:
                # Root dataset: parent is the Pool object
                parent_key = item.pool_name
                parent_obj = pools_by_name.get(parent_key) # Lookup parent Pool by name

        elif isinstance(item, Snapshot):
             # Snapshot: parent is the dataset path
             parent_key = item.dataset_name
             parent_obj = items_by_path.get(parent_key) # Lookup parent dataset by path

        # Link item to parent_obj if found
        if parent_obj:
            # Determine where to attach the child
            target_list = None
            if isinstance(item, Dataset):
                 if hasattr(parent_obj, 'children') and isinstance(parent_obj.children, list):
                      target_list = parent_obj.children
                 else:
                      print(f"WARNING: Parent object '{parent_key}' lacks 'children' list for Dataset '{item.name}'", file=sys.stderr)
            elif isinstance(item, Snapshot):
                 if isinstance(parent_obj, Dataset): # Snapshots only attach to Datasets
                      if hasattr(parent_obj, 'snapshots') and isinstance(parent_obj.snapshots, list):
                           target_list = parent_obj.snapshots
                      else:
                           print(f"WARNING: Parent Dataset '{parent_key}' lacks 'snapshots' list for Snapshot '{item.name}'", file=sys.stderr)
                 else:
                      print(f"WARNING: Found parent for Snapshot '{item.name}', but it's not a Dataset (type: {type(parent_obj)})", file=sys.stderr)

            # Attach if target list found
            if target_list is not None:
                 target_list.append(item)
                 item.parent = parent_obj
            # else: Warning already printed above

        elif parent_key: # Only warn if we expected to find a parent based on name structure
             print(f"WARNING: Parent object '{parent_key}' not found for item '{getattr(item, 'properties', {}).get('full_snapshot_name', getattr(item, 'name', 'unknown'))}'", file=sys.stderr)


    # Sort children and snapshots
    for pool in pools: # Iterate through pools to ensure sorting happens top-down
        # Use a stack for depth-first traversal to sort all levels
        stack = [pool]
        visited_ids = set() # Track visited object IDs to prevent cycles and redundant work
        while stack:
            current_item = stack.pop()
            current_id = id(current_item)
            if current_id in visited_ids: continue # Check ID instead of object
            visited_ids.add(current_id) # Add ID instead of object

            # Sort children if they exist
            if hasattr(current_item, 'children') and isinstance(current_item.children, list):
                current_item.children.sort(key=lambda x: x.name)
                # Add children to stack to process them next (reverse order for depth-first)
                stack.extend(reversed(current_item.children))

            # Sort snapshots if they exist
            if hasattr(current_item, 'snapshots') and isinstance(current_item.snapshots, list):
                # Snapshots don't have children, but sort them
                sort_key = lambda x: getattr(x, 'creation_time_raw', x.name) # Sort by creation time if available
                current_item.snapshots.sort(key=sort_key)

    return pools


# --- END OF FILE src/zfs_manager.py ---
