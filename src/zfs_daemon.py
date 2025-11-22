# --- START OF FILE src/zfs_daemon.py (Refactored for Pipe IPC) ---
import sys
import os
import json
import traceback
import argparse
# Removed socket, signal, threading, time, pwd, stat imports

from paths import DAEMON_STDERR_LOG

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

should_shutdown = False

def run_command_loop(transport):
    global should_shutdown, target_uid
    
    while not should_shutdown:
        try:
            line = transport.receive_line()
            if not line:  # EOF
                print("DAEMON: Client disconnected (EOF)", file=sys.stderr)
                break
            
            if not line.strip():
                continue
            
            print(f"DAEMON: Received line: {line.strip()}", file=sys.stderr)
            response = {}
            request_id = None
            
            try:
                request = json.loads(line)
                command = request.get("command")
                args = request.get("args", [])
                kwargs = request.get("kwargs", {})
                meta = request.get("meta", {})
                request_id = meta.get("request_id")
                log_enabled = meta.get("log_enabled", False)
                current_command_uid = target_uid

                if command == "shutdown_daemon":
                    print("DAEMON: Received shutdown command.", file=sys.stderr)
                    response = {"status": "success", "data": "Daemon shutting down gracefully."}
                    response["meta"] = {"request_id": request_id}
                    try:
                        transport.send_line(json.dumps(response))
                    except (BrokenPipeError, OSError):
                        pass
                    should_shutdown = True
                    return

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
                                response = {"status": "error", "error": "Password update failed. Check daemon logs."}
                        except Exception as e:
                            print(f"DAEMON: Error executing command '{command}': {e}\n{traceback.format_exc()}", file=sys.stderr)
                            response = {"status": "error", "error": f"Daemon execution error during password change: {e}", "details": traceback.format_exc()}

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

            response["meta"] = {"request_id": request_id}

            if response:
                try:
                    transport.send_line(json.dumps(response))
                    print(f"DAEMON: Sent response for ReqID={request_id}, Cmd='{command if 'command' in locals() else 'unknown'}'", file=sys.stderr)
                except (BrokenPipeError, OSError) as e:
                    print(f"DAEMON: Client gone during response: {e}", file=sys.stderr)
                    break

        except Exception as e:
            print(f"DAEMON: Unexpected error in command loop: {e}", file=sys.stderr)
            break

def main():
    """Main daemon execution function, communicating via stdin/stdout pipes."""
    global target_uid, target_gid, daemon_log_file_path

    parser = argparse.ArgumentParser(description="ZFS GUI Background Daemon")
    # These arguments are expected to be passed via pkexec by daemon_utils.py
    parser.add_argument('--uid', required=True, type=int, help="Real User ID of the GUI/WebUI process owner")
    parser.add_argument('--gid', required=True, type=int, help="Real Group ID of the GUI/WebUI process owner")
    parser.add_argument('--daemon', action='store_true', help="Flag indicating daemon mode (for main.py)")
    parser.add_argument('--listen-socket', type=str, help="Unix socket path to create and listen on (if not provided, uses stdin/stdout pipes)")
    args = parser.parse_args()
    target_uid = args.uid
    target_gid = args.gid

    # --- Setup stderr logging: Write to BOTH terminal and log file ---
    original_stderr = sys.stderr
    
    # Simple wrapper that writes to multiple destinations
    class Tee:
        def __init__(self, *files):
            self.files = files
        def write(self, data):
            for f in self.files:
                try: f.write(data); f.flush()
                except: pass
        def flush(self):
            for f in self.files:
                try: f.flush()
                except: pass
    
    try:
        try: os.remove(DAEMON_STDERR_LOG)  # Remove old log (avoid permission errors)
        except: pass
        log_file = open(DAEMON_STDERR_LOG, 'w', buffering=1, encoding='utf-8', errors='replace')
        os.chmod(DAEMON_STDERR_LOG, 0o666)  # Readable by all for debugging
        sys.stderr = Tee(original_stderr, log_file)  # Send stderr to both terminal and file
        print(f"DAEMON: Logging stderr to {DAEMON_STDERR_LOG} + terminal", file=sys.stderr)
    except Exception as e:
        print(f"DAEMON: Logging stderr setup failed: {e}", file=original_stderr)
    # --- End logging setup ---

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


    # --- Setup Communication Channel (Simplified with ipc_server) ---
    try:
        if args.listen_socket:
            # Socket server mode
            print(f"DAEMON: Creating socket server: {args.listen_socket}", file=sys.stderr)
            transport = SocketServerTransport(
                socket_path=args.listen_socket,
                uid=target_uid,
                gid=target_gid
            )
            transport_mode = f"Socket: {args.listen_socket}"
            
            print(f"DAEMON: Starting ZFS GUI Daemon for UID={target_uid}, GID={target_gid} (PID: {os.getpid()}) [{transport_mode}]", file=sys.stderr)
            
            # Socket Accept Loop
            try:
                while not should_shutdown:
                    print("DAEMON: Waiting for client connection...", file=sys.stderr)
                    try:
                        transport.accept_connection()
                        print("DAEMON: Client connected", file=sys.stderr)
                        
                        transport.send_line(json.dumps({"status": "ready"}))
                        print("DAEMON: Sent ready signal to client", file=sys.stderr)
                        
                        run_command_loop(transport)
                        print("DAEMON: Client session ended", file=sys.stderr)
                        
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        print(f"DAEMON: Error in client session: {e}", file=sys.stderr)
                        # Continue to accept next client unless shutdown
            finally:
                transport.close()

        else:
            # Pipe mode (stdin/stdout)
            print("DAEMON: Using pipe transport (stdin/stdout)", file=sys.stderr)
            transport = PipeServerTransport()
            transport_mode = "Pipe (stdin/stdout)"
            
            print(f"DAEMON: Starting ZFS GUI Daemon for UID={target_uid}, GID={target_gid} (PID: {os.getpid()}) [{transport_mode}]", file=sys.stderr)
            
            try:
                transport.accept_connection()
                transport.send_line(json.dumps({"status": "ready"}))
                run_command_loop(transport)
            finally:
                transport.close()
        
    except KeyboardInterrupt:
        print("\nDAEMON: Interrupted by user (Ctrl+C), shutting down...", file=sys.stderr)
    except Exception as e:
        print(f"DAEMON: Failed to setup transport or fatal error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        print("DAEMON: Exiting main function.", file=sys.stderr)


if __name__ == "__main__":
    # This check might be redundant if always launched via main.py --daemon,
    # but good practice.
    main()

# --- END OF FILE src/zfs_daemon.py ---
