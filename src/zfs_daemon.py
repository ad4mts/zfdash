#!/usr/bin/env python3
# --- START OF FILE src/zfs_daemon.py (Refactored for Pipe IPC) ---
import sys
import os
import json
import traceback
import argparse
# Removed socket, signal, threading, time, pwd, stat imports

from paths import DAEMON_STDERR_FILENAME, get_daemon_log_file_path

# SECURITY: Only import server-side transport classes.
# This module contains NO daemon launching or privilege escalation code.
from ipc_server import PipeServerTransport, SocketServerTransport

# Assuming zfs_manager_core is in the same directory or PYTHONPATH
import zfs_manager_core
from zfs_manager_core import ZfsCommandError
# Import config_manager for password functions and credential management
try:
    import config_manager
    # --- ADD IMPORT FOR PASSWORD FUNC --- (and default creation)
    from config_manager import update_user_password, create_default_credentials_if_missing, ensure_flask_secret_key
    # Import log path function from paths module
    from paths import get_daemon_log_file_path
except ImportError as e:
    print(f"DAEMON: Error - config_manager or required function not found: {e}!", file=sys.stderr)
    # Define dummy functions if import fails
    def get_daemon_log_file_path(uid, log_name=None):
        if log_name is None:
            return f"/tmp/zfdash-daemon.log.err"
        return f"/tmp/{log_name}.err"
    def update_user_password(u, p): print("DAEMON: ERROR - Dummy update_user_password called!", file=sys.stderr); return False
    def create_default_credentials_if_missing(): print("DAEMON: ERROR - Dummy create_default_credentials_if_missing called!", file=sys.stderr)
    def ensure_flask_secret_key(uid, gid): print("DAEMON: ERROR - Dummy ensure_flask_secret_key called!", file=sys.stderr); return False


# Removed SOCKET_NAME, SOCKET_PATH constants
target_uid = -1
target_gid = -1
daemon_log_file_path = None # Store the determined log path

# Removed shutdown_event global
# Removed get_socket_path function
# Removed handle_signal function
# Removed handle_connection function

import threading

# Thread-safe shutdown event (replaces simple bool for concurrent safety)
shutdown_event = threading.Event()

def _execute_command_task(transport, request_data, uid, shutdown_event):
    """
    Worker function that runs in the thread pool.
    Executes a single command and sends the response via the transport.
    """
    request_id = None
    command = "unknown"
    try:
        command = request_data.get("command", "unknown")
        args = request_data.get("args", [])
        kwargs = request_data.get("kwargs", {})
        meta = request_data.get("meta", {})
        request_id = meta.get("request_id")
        log_enabled = meta.get("log_enabled", False)

        print(f"DAEMON [Thread]: Executing command '{command}' (ReqID={request_id})", file=sys.stderr)
        response = {}

        if command == "change_password":
            username = kwargs.get("username")
            new_password = kwargs.get("new_password")
            if not username or not new_password:
                response = {"status": "error", "error": "Missing username or new_password parameter"}
            else:
                try:
                    success = update_user_password(username, new_password)
                    if success:
                        response = {"status": "success", "data": "Password updated successfully."}
                    else:
                        response = {"status": "error", "error": "Password update failed. Check daemon logs."}
                except Exception as e:
                    response = {"status": "error", "error": f"Password change error: {e}", "details": traceback.format_exc()}

        elif command in zfs_manager_core.COMMAND_MAP:
            func = zfs_manager_core.COMMAND_MAP[command]
            try:
                result_data = func(*args, **kwargs, _log_enabled=log_enabled, _user_uid=uid)
                response = {"status": "success", "data": result_data}
            except ZfsCommandError as zfs_err:
                print(f"DAEMON [Thread]: ZfsCommandError for '{command}': {zfs_err}", file=sys.stderr)
                response = {"status": "error", "error": str(zfs_err), "details": zfs_err.stderr}
            except Exception as e:
                print(f"DAEMON [Thread]: Error executing '{command}': {e}\n{traceback.format_exc()}", file=sys.stderr)
                response = {"status": "error", "error": f"Execution error: {e}", "details": traceback.format_exc()}
        else:
            print(f"DAEMON [Thread]: Unknown command: {command}", file=sys.stderr)
            response = {"status": "error", "error": f"Unknown command: {command}"}

        response["meta"] = {"request_id": request_id}
        transport.send_line(json.dumps(response))
        print(f"DAEMON [Thread]: Sent response for ReqID={request_id}, Cmd='{command}'", file=sys.stderr)

    except (BrokenPipeError, OSError) as e:
        print(f"DAEMON [Thread]: Client gone during response (ReqID={request_id}): {e}", file=sys.stderr)
    except Exception as e:
        print(f"DAEMON [Thread]: Unexpected error in task (ReqID={request_id}, Cmd='{command}'): {e}\n{traceback.format_exc()}", file=sys.stderr)
        # Try to send error response
        try:
            error_response = {"status": "error", "error": f"Worker thread error: {e}", "meta": {"request_id": request_id}}
            transport.send_line(json.dumps(error_response))
        except:
            pass


def run_command_loop(transport, executor, shutdown_event):
    """
    Command loop for a single client connection.
    Uses shared ThreadPoolExecutor for async command execution.
    
    Args:
        transport: Client transport (PipeServerTransport or SocketClientHandler)
        executor: Shared ThreadPoolExecutor for command execution
        shutdown_event: threading.Event to signal shutdown
    """
    global target_uid
    futures = []
    
    while not shutdown_event.is_set():
        try:
            line = transport.receive_line()
            if not line:  # EOF - client disconnected
                print("DAEMON: Client disconnected (EOF)", file=sys.stderr)
                break
            
            if not line.strip():
                continue
            
            print(f"DAEMON: Received request: {line.strip()[:100]}...", file=sys.stderr)
            
            try:
                request = json.loads(line)
                command = request.get("command")
                request_id = request.get("meta", {}).get("request_id")

                # Handle shutdown synchronously (must be immediate)
                if command == "shutdown_daemon":
                    print("DAEMON: Received shutdown command.", file=sys.stderr)
                    response = {"status": "success", "data": "Daemon shutting down gracefully.", "meta": {"request_id": request_id}}
                    try:
                        transport.send_line(json.dumps(response))
                    except (BrokenPipeError, OSError):
                        pass
                    shutdown_event.set()  # Signal all threads to stop
                    break

                # Submit command to shared thread pool (non-blocking)
                future = executor.submit(_execute_command_task, transport, request, target_uid, shutdown_event)
                futures.append(future)
                
                # Periodic cleanup: only when list gets large
                if len(futures) > 100:
                    futures = [f for f in futures if not f.done()]

            except json.JSONDecodeError as json_err:
                print(f"DAEMON: JSON Decode Error: {json_err}", file=sys.stderr)
                response = {"status": "error", "error": f"Invalid JSON: {json_err}", "meta": {"request_id": None}}
                try:
                    transport.send_line(json.dumps(response))
                except:
                    pass

        except Exception as e:
            print(f"DAEMON: Unexpected error in command loop: {e}", file=sys.stderr)
            break
    
    # Wait for this client's pending tasks (with timeout)
    pending = [f for f in futures if not f.done()]
    if pending:
        print(f"DAEMON: Waiting for {len(pending)} pending tasks for this client...", file=sys.stderr)
        for f in pending:
            try:
                f.result(timeout=10)
            except Exception as e:
                print(f"DAEMON: Task failed during client cleanup: {e}", file=sys.stderr)

def main():
    """Main daemon execution function, communicating via stdin/stdout pipes."""
    global target_uid, target_gid, daemon_log_file_path

    parser = argparse.ArgumentParser(description="ZFS GUI Background Daemon")
    # These arguments are expected to be passed via privilege escalation (pkexec/doas/sudo) by daemon_utils.py
    parser.add_argument('--uid', required=True, type=int, help="Real User ID of the GUI/WebUI process owner")
    parser.add_argument('--gid', required=True, type=int, help="Real Group ID of the GUI/WebUI process owner")
    parser.add_argument('--daemon', action='store_true', help="Flag indicating daemon mode (for main.py)")
    parser.add_argument('--listen-socket', type=str, nargs='?', const='', help="Unix socket path to create and listen on (if not provided, uses stdin/stdout pipes). If flag present without path, uses default from get_daemon_socket_path(uid)")
    parser.add_argument('--debug', action='store_true', help="Enable debug output to both terminal and log file")
    args = parser.parse_args()
    target_uid = args.uid
    target_gid = args.gid

    # -----------------------------
    # --- Unified Logging Setup ---
    # -----------------------------
    original_stderr = sys.stderr

    class Tee:
        def __init__(self, *files): self.files = files
        def write(self, d): 
            for f in self.files: 
                try: f.write(d); f.flush() 
                except: pass
        def flush(self): 
            for f in self.files: 
                try: f.flush() 
                except: pass

    try:
        log_path = get_daemon_log_file_path(target_uid, DAEMON_STDERR_FILENAME)
        try:
            if os.path.exists(log_path):
                os.remove(log_path)
        except OSError:
            pass
        
        log_f = open(log_path, 'w', buffering=1, encoding='utf-8', errors='replace')
        try:
            os.chmod(log_path, 0o666)
        except OSError:
            pass
        
        # Redirect stderr: Debug -> Tee(Term, File); Normal -> File
        sys.stderr = Tee(original_stderr, log_f) if args.debug else log_f
    except Exception as e:
        print(f"DAEMON: Log setup failed: {e}", file=original_stderr)
        log_path = "terminal fallback"

    def log(msg, level="INFO"):
        txt = f"DAEMON [{level}]: {msg}"
        # Write to system stderr (handles routing to file and optional debug terminal)
        print(txt, file=sys.stderr)
        
        # Critical override: Force terminal for errors if not already in debug mode
        if not args.debug and level in ("ERROR", "CRITICAL") and sys.stderr != original_stderr:
             try:
                 print(txt, file=original_stderr)
             except:
                 pass

    log(f"Logging to {log_path}" + (" + terminal" if args.debug else ""), "INFO")

    # ---------------------

    # Handle default socket path if --listen-socket flag present without path
    if args.listen_socket == '':
        from paths import get_daemon_socket_path
        args.listen_socket = get_daemon_socket_path(target_uid)
        log(f"Using default socket path: {args.listen_socket}", "INFO")

    # Initial checks with proper log levels
    if os.geteuid() != 0:
        log("Must run as root", "CRITICAL")
        sys.exit(1)
    if not zfs_manager_core.ZFS_CMD_PATH or not zfs_manager_core.ZPOOL_CMD_PATH:
        log("zfs/zpool command not found", "CRITICAL")
        sys.exit(1)
    if target_uid < 0 or target_gid < 0:
        log(f"Invalid UID ({target_uid}) or GID ({target_gid}) received", "CRITICAL")
        sys.exit(1)

    # Determine paths based on the target user UID
    daemon_log_file_path = get_daemon_log_file_path(target_uid)
    log(f"Using log file path (for ZfsManagerCore): {daemon_log_file_path}", "INFO")

    # --- Ensure default credentials file exists (create if missing) ---
    # This is done by the daemon (root) as it has permissions
    create_default_credentials_if_missing()
    # --- Ensure Flask Secret Key exists ---
    # Daemon (root) creates it with ownership set to target_uid (WebUI user)
    # This fixes permissions issues when running from source
    if ensure_flask_secret_key(target_uid, target_gid):
         log("Flask secret key verified/created", "INFO")
    else:
         log("Failed to ensure Flask secret key!", "ERROR")
    # --- End Flask Key Check ---


    # --- Setup Communication Channel ---
    from concurrent.futures import ThreadPoolExecutor
    
    # Calculate worker count: at least 8, scales with CPU count for larger systems
    max_workers = max(8, (os.cpu_count() or 4) * 2)
    
    try:
        if args.listen_socket:
            # Socket server mode - concurrent clients
            log(f"Creating socket server: {args.listen_socket}", "INFO")
            transport = SocketServerTransport(
                socket_path=args.listen_socket,
                uid=target_uid,
                gid=target_gid
            )
            transport_mode = f"Socket: {args.listen_socket}"
            
            log(f"Starting ZFS GUI Daemon for UID={target_uid}, GID={target_gid} (PID: {os.getpid()}) [{transport_mode}]", "INFO")
            log(f"ThreadPoolExecutor: max_workers={max_workers}", "INFO")
            
            # Shared executor for all clients
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="daemon_worker") as executor:
                client_threads = []
                
                try:
                    while not shutdown_event.is_set():
                        log("Waiting for client connection...", "DEBUG")
                        try:
                            # Accept with 1s timeout to check shutdown_event periodically
                            client_handler = transport.accept_client(timeout=1.0)
                            if client_handler is None:
                                continue  # Timeout, check shutdown_event
                            
                            log("Client connected", "INFO")
                            
                            def handle_client(handler, exec, event):
                                """Handle a single client in its own thread."""
                                try:
                                    handler.send_line(json.dumps({"status": "ready"}))
                                    run_command_loop(handler, exec, event)
                                except Exception as e:
                                    print(f"DAEMON: Error in client thread: {e}", file=sys.stderr)
                                finally:
                                    handler.close()
                                    log("Client session ended", "INFO")
                            
                            # Spawn thread for this client (pass args to avoid closure issues)
                            t = threading.Thread(
                                target=handle_client,
                                args=(client_handler, executor, shutdown_event),
                                daemon=True,
                                name=f"client_{len(client_threads)}"
                            )
                            t.start()
                            client_threads.append(t)
                            
                            # Cleanup finished threads periodically
                            if len(client_threads) > 10:
                                client_threads = [t for t in client_threads if t.is_alive()]
                                
                        except KeyboardInterrupt:
                            raise
                        except Exception as e:
                            if not shutdown_event.is_set():
                                log(f"Error accepting client: {e}", "ERROR")
                    
                    # Wait for client threads on shutdown
                    active = [t for t in client_threads if t.is_alive()]
                    if active:
                        log(f"Waiting for {len(active)} client threads to finish...", "INFO")
                        for t in active:
                            t.join(timeout=5.0)
                            
                finally:
                    transport.close()

        else:
            # Pipe mode (stdin/stdout) - single client
            log("Using pipe transport (stdin/stdout)", "INFO")
            transport = PipeServerTransport()
            transport_mode = "Pipe (stdin/stdout)"
            
            log(f"Starting ZFS GUI Daemon for UID={target_uid}, GID={target_gid} (PID: {os.getpid()}) [{transport_mode}]", "INFO")
            
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="daemon_worker") as executor:
                try:
                    transport.accept_connection()
                    transport.send_line(json.dumps({"status": "ready"}))
                    run_command_loop(transport, executor, shutdown_event)
                finally:
                    transport.close()
        
    except KeyboardInterrupt:
        shutdown_event.set()
        log("Interrupted by user (Ctrl+C), shutting down...", "WARNING")
    except Exception as e:
        log(f"Failed to setup transport or fatal error: {e}", "CRITICAL")
        sys.exit(1)
    finally:
        log("Exiting main function", "INFO")


if __name__ == "__main__":
    # This check might be redundant if always launched via main.py --daemon,
    # but good practice.
    main()

# --- END OF FILE src/zfs_daemon.py ---
