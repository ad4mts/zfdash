# --- START OF FILE src/zfs_daemon.py (Refactored for Pipe IPC) ---
import sys
import os
import json
import traceback
import argparse
# Removed socket, signal, threading, time, pwd, stat imports

from paths import DAEMON_STDERR_LOG

# Assuming zfs_manager_core is in the same directory or PYTHONPATH
import zfs_manager_core
from zfs_manager_core import ZfsCommandError
# Import config_manager for password functions and credential management
try:
    import config_manager
    # --- ADD IMPORT FOR PASSWORD FUNC --- (and default creation)
    from config_manager import update_user_password, create_default_credentials_if_missing
    # Import log path function from paths module
    from paths import get_daemon_log_file_path
except ImportError as e:
    print(f"DAEMON: Error - config_manager or required function not found: {e}!", file=sys.stderr)
    # Define dummy functions if import fails
    def get_daemon_log_file_path(uid): return f"/tmp/zfdash-daemon.log.{uid}.err"
    def update_user_password(u, p): print("DAEMON: ERROR - Dummy update_user_password called!", file=sys.stderr); return False
    def create_default_credentials_if_missing(): print("DAEMON: ERROR - Dummy create_default_credentials_if_missing called!", file=sys.stderr)


# Removed SOCKET_NAME, SOCKET_PATH constants
target_uid = -1
target_gid = -1
daemon_log_file_path = None # Store the determined log path

# Removed shutdown_event global
# Removed get_socket_path function
# Removed handle_signal function
# Removed handle_connection function

def main():
    """Main daemon execution function, communicating via stdin/stdout pipes."""
    global target_uid, target_gid, daemon_log_file_path

    parser = argparse.ArgumentParser(description="ZFS GUI Background Daemon (Pipe IPC)")
    # These arguments are expected to be passed via pkexec by daemon_utils.py
    parser.add_argument('--uid', required=True, type=int, help="Real User ID of the GUI/WebUI process owner")
    parser.add_argument('--gid', required=True, type=int, help="Real Group ID of the GUI/WebUI process owner")
    parser.add_argument('--daemon', action='store_true', help="Flag indicating daemon mode (for main.py)")
    args = parser.parse_args()
    target_uid = args.uid
    target_gid = args.gid

    # Use stderr for all daemon logging output
    print(f"DAEMON: Starting ZFS GUI Daemon for UID={target_uid}, GID={target_gid} (PID: {os.getpid()}) [Pipe Mode]...", file=sys.stderr)

    # Initial Checks
    if os.geteuid() != 0:
        print("DAEMON: Error - Must run as root.", file=sys.stderr)
        sys.exit(1)
    if not zfs_manager_core.ZFS_CMD_PATH or not zfs_manager_core.ZPOOL_CMD_PATH:
        print("DAEMON: Error - zfs/zpool command not found.", file=sys.stderr)
        sys.exit(1)
    if target_uid < 0 or target_gid < 0:
        print(f"DAEMON: Error - Invalid UID ({target_uid}) or GID ({target_gid}) received.", file=sys.stderr)
        sys.exit(1)

    # Determine paths based on the target user UID
    daemon_log_file_path = get_daemon_log_file_path(target_uid)
    print(f"DAEMON: Using log file path (for ZfsManagerCore): {daemon_log_file_path}", file=sys.stderr)

    # --- Ensure default credentials file exists (create if missing) ---
    # This is done by the daemon (root) as it has permissions
    create_default_credentials_if_missing()
    # --- End Credentials Check ---


    # --- DEBUG: Redirect stderr to daemon log for troubleshooting issues ---
    # This block is for debug purposes ONLY. Dont remove it!
    try:
        sys.stderr = open(DAEMON_STDERR_LOG, 'a', buffering=1)  # Line buffered
    except Exception as e:
        # If redirection fails, print to original stderr
        print(f"DAEMON: Failed to redirect stderr: {e}", file=sys.__stderr__)
    # --- END DEBUG BLOCK ---


    # --- Communication Loop (stdin/stdout) ---
    print("DAEMON: Entering communication loop (stdin/stdout)...", file=sys.stderr)

    # --- Send Ready Signal ---
    try:
        ready_signal = json.dumps({"status": "ready"}) + '\n'
        sys.stdout.write(ready_signal)
        sys.stdout.flush()
        print("DAEMON: Sent ready signal to parent.", file=sys.stderr)
    except Exception as e:
        print(f"DAEMON: Error sending ready signal: {e}", file=sys.stderr)
        sys.exit(1) # Exit if we can't even send the ready signal
    # --- END Ready Signal ---

    try:
        for line in sys.stdin:
            if not line.strip(): # Skip empty lines
                continue
            print(f"DAEMON: Received line: {line.strip()}", file=sys.stderr) # Log received data
            response = {}
            request_id = None # Initialize request_id for this request
            try:
                request = json.loads(line)
                command = request.get("command")
                args = request.get("args", [])
                kwargs = request.get("kwargs", {})
                # --- Extract meta info ---
                meta = request.get("meta", {})
                request_id = meta.get("request_id") # Get request ID
                log_enabled = meta.get("log_enabled", False)
                current_command_uid = target_uid
                # --------------------------

                if command == "shutdown_daemon":
                    print("DAEMON: Received shutdown command. Preparing to exit.", file=sys.stderr)
                    response = {"status": "success", "data": "Daemon shutting down gracefully."}
                    # Write final response before exiting
                    response["meta"] = {"request_id": request_id} # Add meta with request_id
                    response_json = json.dumps(response) + '\n'
                    sys.stdout.write(response_json)
                    sys.stdout.flush()
                    print("DAEMON: Exiting cleanly after shutdown command.", file=sys.stderr)
                    sys.exit(0)

                # --- ADD: Handle Change Password Command ---
                elif command == "change_password":
                    print(f"DAEMON: Handling command '{command}'...", file=sys.stderr)
                    username = kwargs.get("username")
                    new_password = kwargs.get("new_password")
                    if not username or not new_password:
                        print(f"DAEMON: Error - change_password requires 'username' and 'new_password' in kwargs.", file=sys.stderr)
                        response = {"status": "error", "error": "Missing username or new_password parameter for change_password"}
                    else:
                        try:
                            success = update_user_password(username, new_password)
                            if success:
                                response = {"status": "success", "data": "Password updated successfully."}
                            else:
                                # update_user_password logs specifics
                                response = {"status": "error", "error": "Password update failed. Check daemon logs."}
                        except Exception as e:
                            print(f"DAEMON: Error executing command '{command}': {e}\n{traceback.format_exc()}", file=sys.stderr)
                            response = {"status": "error", "error": f"Daemon execution error during password change: {e}", "details": traceback.format_exc()}
                # --- END ADD ---

                elif command in zfs_manager_core.COMMAND_MAP:
                    func = zfs_manager_core.COMMAND_MAP[command]
                    try:
                        result_data = func(*args, **kwargs, _log_enabled=log_enabled, _user_uid=current_command_uid)
                        response = {"status": "success", "data": result_data}
                    except ZfsCommandError as zfs_err:
                        print(f"DAEMON: ZfsCommandError for command '{command}': {zfs_err}", file=sys.stderr)
                        response = {"status": "error", "error": str(zfs_err), "details": zfs_err.stderr}
                    except Exception as e:
                        print(f"DAEMON: Error executing command '{command}': {e}\n{traceback.format_exc()}", file=sys.stderr)
                        response = {"status": "error", "error": f"Daemon execution error: {e}", "details": traceback.format_exc()}
                else:
                    print(f"DAEMON: Unknown command received: {command}", file=sys.stderr)
                    response = {"status": "error", "error": f"Unknown command: {command}"}

            except json.JSONDecodeError as json_err:
                print(f"DAEMON: JSON Decode Error: {json_err}. Invalid line received: {line.strip()}", file=sys.stderr)
                response = {"status": "error", "error": f"Invalid JSON request: {json_err}", "details": line.strip()}
            except Exception as e:
                print(f"DAEMON: Error processing request: {e}\n{traceback.format_exc()}", file=sys.stderr)
                response = {"status": "error", "error": f"Daemon request processing error: {e}", "details": traceback.format_exc()}

            # --- Add request_id to meta in all responses ---
            response["meta"] = {"request_id": request_id}

            # --- Send Response ---
            if response:
                try:
                    response_json = json.dumps(response) + '\n'
                    sys.stdout.write(response_json)
                    sys.stdout.flush()
                    print(f"DAEMON: Sent response for ReqID={request_id}, Cmd='{command if 'command' in request else 'unknown'}'", file=sys.stderr) # Log sent data
                except Exception as e:
                    print(f"DAEMON: Error sending response via stdout: {e}. Response was: {response}", file=sys.stderr)
                    print("DAEMON: Exiting due to stdout write error.", file=sys.stderr)
                    sys.exit(1)

    except EOFError:
        print("DAEMON: EOF received on stdin (parent likely closed pipe). Exiting.", file=sys.stderr)
    except KeyboardInterrupt:
        print("DAEMON: KeyboardInterrupt received. Exiting.", file=sys.stderr)
    except Exception as e:
        # Catch any unexpected errors in the main loop
        print(f"DAEMON: Fatal error in main loop: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    finally:
        print("DAEMON: Exiting main function.", file=sys.stderr)
        # No socket cleanup needed


if __name__ == "__main__":
    # This check might be redundant if always launched via main.py --daemon,
    # but good practice.
    main()

# --- END OF FILE src/zfs_daemon.py ---
