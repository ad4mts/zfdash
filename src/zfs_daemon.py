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

# TCP transport for Agent Mode (network-accessible daemon)
try:
    from ipc_tcp_server import TCPServerTransport
    TCP_AVAILABLE = True
except ImportError:
    TCP_AVAILABLE = False

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

# Unified logging - imported at module level for helper functions
from debug_logging import daemon_log, set_debug_mode, configure_terminal_output

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

        daemon_log(f"Executing command '{command}' (ReqID={request_id})", "DEBUG")
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
                daemon_log(f"ZfsCommandError for '{command}': {zfs_err}", "DEBUG")
                response = {"status": "error", "error": str(zfs_err), "details": zfs_err.stderr}
            except Exception as e:
                daemon_log(f"Error executing '{command}': {e}", "DEBUG")
                response = {"status": "error", "error": f"Execution error: {e}", "details": traceback.format_exc()}
        else:
            daemon_log(f"Unknown command: {command}", "ERROR")
            response = {"status": "error", "error": f"Unknown command: {command}"}

        response["meta"] = {"request_id": request_id}
        transport.send_line(json.dumps(response))
        daemon_log(f"Sent response for ReqID={request_id}, Cmd='{command}'", "DEBUG")

    except (BrokenPipeError, OSError) as e:
        daemon_log(f"Client gone during response (ReqID={request_id}): {e}", "DEBUG")
    except Exception as e:
        daemon_log(f"Unexpected error in task (ReqID={request_id}, Cmd='{command}'): {e}", "ERROR")
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
                daemon_log("Client disconnected (EOF)", "DEBUG")
                break
            
            if not line.strip():
                continue
            
            daemon_log(f"Received request: {line.strip()[:100]}...", "DEBUG")
            
            try:
                request = json.loads(line)
                command = request.get("command")
                request_id = request.get("meta", {}).get("request_id")

                # Handle shutdown synchronously (must be immediate)
                if command == "shutdown_daemon":
                    daemon_log("Received shutdown command.", "INFO")
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
                daemon_log(f"JSON Decode Error: {json_err}", "ERROR")
                response = {"status": "error", "error": f"Invalid JSON: {json_err}", "meta": {"request_id": None}}
                try:
                    transport.send_line(json.dumps(response))
                except:
                    pass

        except Exception as e:
            daemon_log(f"Unexpected error in command loop: {e}", "ERROR")
            break
    
    # Wait for this client's pending tasks (with timeout)
    pending = [f for f in futures if not f.done()]
    if pending:
        daemon_log(f"Waiting for {len(pending)} pending tasks for this client...", "INFO")
        for f in pending:
            try:
                f.result(timeout=10)
            except Exception as e:
                daemon_log(f"Task failed during client cleanup: {e}", "ERROR")

# =============================================================================
# Server Mode Helpers
# =============================================================================

def _handle_client(handler, executor, shutdown_event, transport_type="socket"):
    """
    Handle a single client connection in its own thread.
    Sends ready signal, runs command loop, then cleans up.
    """
    try:
        handler.send_line(json.dumps({"status": "ready"}))
        run_command_loop(handler, executor, shutdown_event)
    except Exception as e:
        daemon_log(f"Error in {transport_type} client thread: {e}", "ERROR")
    finally:
        handler.close()
        daemon_log(f"{transport_type.upper()} client session ended", "DEBUG")


def _tcp_accept_loop(tcp_transport, executor, shutdown_event, client_threads):
    """
    Accept loop for TCP clients (runs in separate thread).
    Spawns a handler thread for each authenticated connection.
    """
    while not shutdown_event.is_set():
        try:
            tcp_handler = tcp_transport.accept_client(timeout=1.0)
            if tcp_handler is None:
                continue
            
            addr = tcp_handler.get_address()
            daemon_log(f"TCP client connected from {addr[0]}:{addr[1]}", "DEBUG")
            
            t = threading.Thread(
                target=_handle_client,
                args=(tcp_handler, executor, shutdown_event, "tcp"),
                daemon=True,
                name=f"tcp_client_{len(client_threads)}"
            )
            t.start()
            client_threads.append(t)
            
        except Exception as e:
            if not shutdown_event.is_set():
                daemon_log(f"TCP accept error: {e}", "ERROR")


def _stdin_command_listener(shutdown_event):
    """
    Listen for commands on stdin (runs in separate thread).
    Allows graceful shutdown by typing 'q' or 'quit'.
    """
    import select
    
    while not shutdown_event.is_set():
        try:
            # Use select with timeout to allow checking shutdown_event
            if select.select([sys.stdin], [], [], 1.0)[0]:
                line = sys.stdin.readline()
                if not line:  # EOF (stdin closed)
                    continue
                
                cmd = line.strip().lower()
                if cmd in ('q', 'quit', 'exit', 'stop'):
                    daemon_log("Received 'quit' command from terminal - shutting down gracefully...", "INFO")
                    shutdown_event.set()
                    break
                elif cmd == 'status':
                    daemon_log("Daemon is running. Type 'q' or 'quit' to shutdown.", "INFO")
                elif cmd:
                    daemon_log(f"Unknown command: '{cmd}'. Type 'q' or 'quit' to shutdown.", "INFO")
        except Exception as e:
            # stdin may not be available (e.g., when run as service)
            if not shutdown_event.is_set():
                daemon_log(f"stdin listener error (may be normal if running as service): {e}", "DEBUG")
            break


def _socket_accept_loop(socket_transport, executor, shutdown_event, client_threads):
    """
    Accept loop for Unix socket clients (runs in main thread).
    Spawns a handler thread for each connection.
    """
    while not shutdown_event.is_set():
        daemon_log("Waiting for socket client connection...", "DEBUG")
        try:
            client_handler = socket_transport.accept_client(timeout=1.0)
            if client_handler is None:
                continue  # Timeout, check shutdown_event
            
            daemon_log("Socket client connected", "DEBUG")
            
            t = threading.Thread(
                target=_handle_client,
                args=(client_handler, executor, shutdown_event, "socket"),
                daemon=True,
                name=f"socket_client_{len(client_threads)}"
            )
            t.start()
            client_threads.append(t)
            
            # Cleanup finished threads periodically
            if len(client_threads) > 10:
                client_threads[:] = [t for t in client_threads if t.is_alive()]
                
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if not shutdown_event.is_set():
                daemon_log(f"Error accepting socket client: {e}", "ERROR")


def _create_socket_transport(socket_path, target_uid, target_gid):
    """
    Create and initialize Unix socket transport.
    
    Returns:
        SocketServerTransport instance
    """
    daemon_log(f"Creating socket server: {socket_path}", "DEBUG")
    return SocketServerTransport(
        socket_path=socket_path,
        uid=target_uid,
        gid=target_gid
    )


def _create_tcp_transport(port, use_tls=True):
    """
    Create and initialize TCP transport for Agent Mode.
    
    Args:
        port: TCP port to listen on
        use_tls: Whether to use TLS encryption (default: True)
    
    Returns:
        TCPServerTransport instance, or None if creation fails
    """
    if not TCP_AVAILABLE:
        daemon_log("Agent mode requested but ipc_tcp module not available", "ERROR")
        return None
    
    try:
        transport = TCPServerTransport(host="0.0.0.0", port=port, use_tls=use_tls)
        
        # Check if TLS was successfully enabled (attribute renamed to tls_enabled)
        if transport.tls_enabled:
            daemon_log(f"TLS is enabled and required for this agent. use --no-tls to disable it (not recommended)", "IMPORTANT")
            daemon_log(f"Agent Mode: TCP server listening on port {port} (TLS ENABLED)", "IMPORTANT")
        else:
            if use_tls:
                daemon_log("WARNING: Agent running WITHOUT encryption!", "IMPORTANT") 
                daemon_log("To enable TLS: install cryptography: (uv sync) then use (sudo .venv/bin/python src/main.py --agent..)", "IMPORTANT")
                daemon_log("OR Install openssl on your system", "IMPORTANT")
                daemon_log(f"Agent Mode: TCP server listening on port {port} (NO TLS!)", "IMPORTANT")
            else:
                daemon_log(f"Agent Mode: TCP server listening on port {port} (TLS DISABLED by user)", "IMPORTANT")
        
        return transport
    except Exception as e:
        daemon_log(f"Failed to start TCP server: {e}", "ERROR")
        return None


def _cleanup_transports(socket_transport, tcp_transport):
    """Close all transports safely."""
    if socket_transport:
        socket_transport.close()
    if tcp_transport:
        try:
            tcp_transport.close()
            daemon_log("TCP transport closed", "IMPORTANT")
        except Exception as e:
            daemon_log(f"Error closing TCP transport: {e}", "ERROR")


def _wait_for_client_threads(client_threads):
    """Wait for active client threads to finish (with timeout)."""
    active = [t for t in client_threads if t.is_alive()]
    if active:
        daemon_log(f"Waiting for {len(active)} client threads to finish...", "IMPORTANT")
        for t in active:
            t.join(timeout=5.0)


# =============================================================================
# Server Mode Entry Point
# =============================================================================

def _run_server_mode(args, target_uid, target_gid, max_workers, shutdown_event):
    """
    Run daemon in server mode (Unix socket and/or TCP).
    """
    from concurrent.futures import ThreadPoolExecutor
    import signal
    
    # Setup transports based on args
    socket_transport = None
    tcp_transport = None
    modes = []
    
    if args.listen_socket:
        socket_transport = _create_socket_transport(
            args.listen_socket, target_uid, target_gid
        )
        modes.append(f"Socket: {args.listen_socket}")
    
    if args.agent:
        tcp_transport = _create_tcp_transport(args.agent_port, use_tls=not args.no_tls)
        if tcp_transport:
            modes.append(f"TCP: 0.0.0.0:{args.agent_port}")
    
    mode_desc = " + ".join(modes) if modes else "None"
    
    daemon_log(f"Starting ZFS GUI Daemon for UID={target_uid}, GID={target_gid} "
        f"(PID: {os.getpid()}) [{mode_desc}]", "INFO")
    daemon_log(f"ThreadPoolExecutor: max_workers={max_workers}", "DEBUG")
    
    # Define SIGQUIT handler for graceful terminal shutdown
    def _handle_sigquit(signum, frame):
        daemon_log("Received SIGQUIT (Ctrl+\\) - shutting down gracefully...", "INFO")
        shutdown_event.set()
    
    # Ignore SIGINT/SIGHUP in server mode - daemon should persist through WebUI restarts
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    # But allow SIGQUIT for manual terminal shutdown
    signal.signal(signal.SIGQUIT, _handle_sigquit)
    daemon_log("Server mode: SIGINT (Ctrl+C) ignored.", "DEBUG")
    daemon_log("To shutdown: type 'q' or 'quit' then Enter in terminal, or use --stop-daemon", "IMPORTANT")
    
    # Run accept loops
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="daemon_worker") as executor:
        client_threads = []
        
        try:
            # Start TCP accept thread if enabled
            if tcp_transport:
                tcp_thread = threading.Thread(
                    target=_tcp_accept_loop,
                    args=(tcp_transport, executor, shutdown_event, client_threads),
                    daemon=True,
                    name="tcp_accept"
                )
                tcp_thread.start()
                daemon_log("TCP accept thread started", "DEBUG")
            
            # Start stdin command listener thread for terminal shutdown
            stdin_thread = threading.Thread(
                target=_stdin_command_listener,
                args=(shutdown_event,),
                daemon=True,
                name="stdin_listener"
            )
            stdin_thread.start()
            daemon_log("Terminal command listener started (type 'q' to quit)", "DEBUG")
            
            # Run socket accept loop or wait for shutdown
            if socket_transport:
                _socket_accept_loop(socket_transport, executor, shutdown_event, client_threads)
            else:
                daemon_log("Running in TCP-only mode, waiting for shutdown signal...", "DEBUG")
                while not shutdown_event.is_set():
                    shutdown_event.wait(timeout=1.0)
            
            _wait_for_client_threads(client_threads)
            
        finally:
            _cleanup_transports(socket_transport, tcp_transport)


def _run_pipe_mode(target_uid, target_gid, max_workers, shutdown_event):
    """
    Run daemon in pipe mode (stdin/stdout for single client).
    
    Args:
        target_uid: User ID for permission context
        target_gid: Group ID for permission context
        max_workers: ThreadPoolExecutor worker count
        shutdown_event: threading.Event for shutdown signaling
    """
    from concurrent.futures import ThreadPoolExecutor
    
    daemon_log("Using pipe transport (stdin/stdout)", "DEBUG")
    transport = PipeServerTransport()
    transport_mode = "Pipe (stdin/stdout)"
    
    daemon_log(f"Starting ZFS GUI Daemon for UID={target_uid}, GID={target_gid} (PID: {os.getpid()}) [{transport_mode}]", "INFO")
    
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="daemon_worker") as executor:
        try:
            transport.accept_connection()
            transport.send_line(json.dumps({"status": "ready"}))
            run_command_loop(transport, executor, shutdown_event)
        finally:
            transport.close()


def main():
    """Main daemon execution function, communicating via stdin/stdout pipes."""
    global target_uid, target_gid, daemon_log_file_path

    parser = argparse.ArgumentParser(description="ZFS GUI Background Daemon")
    # These arguments are expected to be passed via privilege escalation (pkexec/doas/sudo) by daemon_utils.py
    parser.add_argument('--uid', required=True, type=int, help="Real User ID of the GUI/WebUI process owner")
    parser.add_argument('--gid', required=True, type=int, help="Real Group ID of the GUI/WebUI process owner")
    parser.add_argument('--daemon', action='store_true', help="Flag indicating daemon mode (for main.py)")
    parser.add_argument('--listen-socket', type=str, nargs='?', const='', help="Unix socket path to create and listen on (if not provided, uses stdin/stdout pipes). If flag present without path, uses default from get_daemon_socket_path(uid)")
    parser.add_argument('--agent', action='store_true', help="Enable Agent Mode: Listen on TCP port for network connections (requires authentication)")
    parser.add_argument('--agent-port', type=int, default=5555, help="TCP port for Agent Mode (default: 5555)")
    parser.add_argument('--no-tls', action='store_true', help="Disable TLS encryption for Agent Mode (not recommended for production)")
    parser.add_argument('--debug', action='store_true', help="Enable debug output to both terminal and log file")
    args = parser.parse_args()
    target_uid = args.uid
    target_gid = args.gid
    
    # Setup global debug mode for all modules (uses module-level import)
    set_debug_mode(args.debug)

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

    # Configure unified logging with terminal output for error forcing
    configure_terminal_output(original_stderr)
    daemon_log(f"Logging to {log_path}" + (" + terminal" if args.debug else ""))
    # ---------------------

    # Handle default socket path if --listen-socket flag present without path
    if args.listen_socket == '':
        from paths import get_daemon_socket_path
        args.listen_socket = get_daemon_socket_path(target_uid)
        daemon_log(f"Using default socket path: {args.listen_socket}")

    # Initial checks with proper log levels
    if os.geteuid() != 0:
        daemon_log("Must run as root", "CRITICAL")
        sys.exit(1)
    if not zfs_manager_core.ZFS_CMD_PATH or not zfs_manager_core.ZPOOL_CMD_PATH:
        daemon_log("zfs/zpool command not found", "CRITICAL")
        sys.exit(1)
    if target_uid < 0 or target_gid < 0:
        daemon_log(f"Invalid UID ({target_uid}) or GID ({target_gid}) received", "CRITICAL")
        sys.exit(1)

    # Determine paths based on the target user UID
    daemon_log_file_path = get_daemon_log_file_path(target_uid)
    daemon_log(f"Using log file path (for ZfsManagerCore): {daemon_log_file_path}")

    # --- Ensure default credentials file exists (create if missing) ---
    # This is done by the daemon (root) as it has permissions
    create_default_credentials_if_missing()
    # --- Ensure Flask Secret Key exists ---
    # Daemon (root) creates it with ownership set to target_uid (WebUI user)
    # This fixes permissions issues when running from source
    if ensure_flask_secret_key(target_uid, target_gid):
         daemon_log("Flask secret key verified/created")
    else:
         daemon_log("Failed to ensure Flask secret key!", "ERROR")
    # --- End Flask Key Check ---


    # --- Setup Communication Channel ---
    from concurrent.futures import ThreadPoolExecutor
    
    # Calculate worker count: at least 8, scales with CPU count for larger systems
    max_workers = max(8, (os.cpu_count() or 4) * 2)
    
    # Determine mode: server (socket and/or TCP) vs pipe
    use_server_mode = args.listen_socket or args.agent
    
    try:
        if use_server_mode:
            _run_server_mode(args, target_uid, target_gid, max_workers, shutdown_event)
        else:
            _run_pipe_mode(target_uid, target_gid, max_workers, shutdown_event)
        
    except KeyboardInterrupt:
        shutdown_event.set()
        daemon_log("Interrupted by user (Ctrl+C), shutting down...", "WARNING")
    except Exception as e:
        daemon_log(f"Failed to setup transport or fatal error: {e}", "CRITICAL")
        sys.exit(1)
    finally:
        daemon_log("Exiting main function")


if __name__ == "__main__":
    # This check might be redundant if always launched via main.py --daemon,
    # but good practice.
    main()

# --- END OF FILE src/zfs_daemon.py ---
