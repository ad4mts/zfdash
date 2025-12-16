#!/usr/bin/env python3
# --- START OF FILE src/main.py ---
import sys
import os
import signal
import atexit
import platform
import traceback # Keep for error reporting if needed
import argparse # Import argparse
from typing import Optional

# Import new dependencies
from ipc_client import launch_daemon, connect_to_existing_socket_daemon, stop_socket_daemon
from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError
import constants
from paths import IS_FROZEN

# Globals for cleanup
_cleanup_done = False
_zfs_client: Optional['ZfsManagerClient'] = None
_daemon_process = None  # Track daemon process separately for early-exit cleanup

def _cleanup():
    """Central cleanup function - called on exit or signal."""
    global _cleanup_done, _zfs_client, _daemon_process
    if _cleanup_done:
        return
    _cleanup_done = True
    
    #print("MAIN: Cleaning up...", file=sys.stderr)
    
    # Close client (which shuts down daemon if it owns it)
    if _zfs_client:
        try:
            _zfs_client.close()
        except Exception as e:
            print(f"MAIN: Cleanup error: {e}", file=sys.stderr)
        _zfs_client = None
    
    # Kill orphan daemon if client wasn't created yet (works only if we are root in docker)
    if _daemon_process and _daemon_process.poll() is None:
        print(f"MAIN: Terminating orphan daemon (PID: {_daemon_process.pid})...", file=sys.stderr)
        try:
            _daemon_process.terminate()
            _daemon_process.wait(timeout=2)
        except Exception:
            try:
                _daemon_process.kill()
            except Exception:
                pass  # Silently fail - can't kill root process as user
        _daemon_process = None
    
    #print("MAIN: Exiting.", file=sys.stderr)

def _signal_handler(signum, frame):
    """Handle termination signals."""
    sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
    print(f"\nMAIN: Received {sig_name}, shutting down...", file=sys.stderr)
    
    # Ensure we break out of any blocking calls if possible
    # For GUI apps, this might not be enough if the event loop is stuck, 
    # but it helps for CLI/daemon modes.
    
    _cleanup()
    
    # Force exit if cleanup takes too long or hangs
    # We use os._exit to bypass Python's cleanup handlers which might be stuck
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)

def _sigtstp_handler(signum, frame):
    """Handle suspend signal (Ctrl+Z) by ignoring it and warning the user."""
    print("\nMAIN: Ctrl+Z (Suspend) detected. Suspension is disabled to prevent orphaned processes.", file=sys.stderr)
    print("MAIN: If the application stops despite this warning, please manually kill any stuck processes.", file=sys.stderr)
    print("MAIN: Please use Ctrl+C to exit safely.", file=sys.stderr)

# Register cleanup
atexit.register(_cleanup)
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
if hasattr(signal, 'SIGTSTP'):
    signal.signal(signal.SIGTSTP, _sigtstp_handler)


# Basic error display function ONLY for cases where GUI components cannot load
# Avoids importing PySide6 here if possible.(so users with no desktop enviroment can run the web_ui)
def _show_startup_error(title, message):
    print(f"STARTUP ERROR: {title}\n{message}", file=sys.stderr)
    try:
        #main.py should not import any gui things by default, so it can run on systems with no desktop env
        # Attempt a minimal Qt message box if possible as a last resort
        from PySide6.QtWidgets import QApplication, QMessageBox
        # Ensure QApplication exists; create temporarily if needed
        _app = QApplication.instance()
        if _app is None:
             _app = QApplication([]) # Minimal app just for the message box
        QMessageBox.critical(None, title, message)
    except Exception:
        print("(Failed to show GUI error message)", file=sys.stderr)




# Main execution dispatcher
if __name__ == "__main__":

    # --- Argument Parsing ---
    class RawDefaultsHelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
        pass

    usage_str = (
        "%(prog)s [-h] [-w] [--host HOST] [-p PORT] [--debug] [--socket [PATH]]\n"
        "   or: %(prog)s --connect-socket [PATH]  # Connect only (no auto-launch)\n"
        "   or: %(prog)s --launch-daemon [PATH]   # Launch daemon and exit\n"
        "   or: %(prog)s --stop-daemon [PATH]     # Stop running daemon\n"
        "   or: %(prog)s --daemon --uid UID --gid GID [--listen-socket [PATH]]\n"
    )

    # Dynamic program name for help examples
    if IS_FROZEN:
        prog_name = os.path.basename(sys.argv[0])
        prog_name_root = prog_name
    else:
        prog_name = "uv run src/main.py"
        # For daemon commands that need root, use venv Python (sudo ignores venv activation)
        prog_name_root = ".venv/bin/python src/main.py"

    parser = argparse.ArgumentParser(
        usage=usage_str,
        description="ZfDash ZFS Manager",
        formatter_class=RawDefaultsHelpFormatter,
        epilog=(
            "Examples:\n"
            f"  Run GUI with pipe-mode daemon (default, daemon exits with GUI):\n"
            f"    {prog_name}\n\n"
            f"  Run Web UI with persistent socket daemon (recommended):\n"
            f"    {prog_name} --web --socket\n\n"
            f"  Connect to existing socket daemon (error if not running):\n"
            f"    {prog_name} --web --connect-socket\n\n"
            f"  Launch daemon in background and exit:\n"
            f"    {prog_name} --launch-daemon\n\n"
            f"  Stop a running socket daemon:\n"
            f"    {prog_name} --stop-daemon\n\n"
            f"  Start daemon manually (run as root with venv Python):\n"
            f"    sudo {prog_name_root} --daemon --uid $(id -u) --gid $(id -g) --listen-socket\n\n"
            f"  Start Agent Mode daemon (TCP server with TLS):\n"
            f"    sudo {prog_name_root} --daemon --uid $(id -u) --gid $(id -g) --agent\n"
        ),
    )

    # Client / UI options (grouped)
    client_group = parser.add_argument_group(
        'Client options',
        'Options for client processes (GUI or Web UI). Controls UI mode, network binding, debug, and '
        'how to connect to the privileged daemon (socket/pipes).'
    )
    client_group.add_argument('-w', '--web', action='store_true', help='Run the Web UI (serve the web interface).')
    client_group.add_argument('--host', default='127.0.0.1', help='Host/IP to bind the Web UI server.')
    client_group.add_argument('-p', '--port', default=5001, type=int, help='Port to bind the Web UI server.')
    client_group.add_argument('--debug', action='store_true', help='Enable debug mode with verbose logging (affects both client and daemon).')
    client_group.add_argument('--socket', type=str, metavar='PATH', nargs='?', const='',
                              help='Use persistent socket daemon. Connects if running, launches if not. Daemon persists after client exit. PATH optional.')
    client_group.add_argument('--connect-socket', type=str, metavar='PATH', nargs='?', const='',
                              help='Connect to existing socket daemon only (error if not running). PATH optional.')
    client_group.add_argument('--launch-daemon', type=str, metavar='PATH', nargs='?', const='',
                              help='Launch a persistent socket daemon and exit. PATH optional.')
    client_group.add_argument('--stop-daemon', type=str, metavar='PATH', nargs='?', const='',
                              help='Stop a running socket daemon and exit. PATH optional.')

    # Daemon options (grouped)
    daemon_group = parser.add_argument_group(
        'Daemon options',
        'Options for running the privileged background daemon. Controls running as a daemon, '
        'the target UID/GID for operations, and socket listening path.'
    )
    daemon_group.add_argument('--daemon', action='store_true', help='Run the background daemon process (requires --uid and --gid).')
    daemon_group.add_argument('--uid', type=int, help='Target user ID for daemon operations (required with --daemon).')
    daemon_group.add_argument('--gid', type=int, help='Target group ID for daemon operations (required with --daemon).')
    daemon_group.add_argument('--listen-socket', type=str, metavar='PATH', nargs='?', const='',
                              help='Create and listen on a Unix socket (daemon server mode). If PATH not specified, uses default from get_daemon_socket_path(uid).')


    # Filter out platform-specific launcher arguments when frozen (for future macOS .app bundle support)
    main_args = sys.argv[1:]
    if IS_FROZEN and platform.system() == "Darwin":
        # macOS Finder injects -psn_<ProcessSerialNumber> when launching .app bundles
        main_args = [arg for arg in main_args if not arg.startswith('-psn_')]

    try:
         # Use parse_known_args when in daemon mode to allow daemon-specific arguments
         # (e.g., --listen-socket <path>) to pass through to zfs_daemon.main()
         if '--daemon' in main_args:
             args, unknown = parser.parse_known_args(args=main_args)
         else:
             args = parser.parse_args(args=main_args)
    except SystemExit:
         # parser.parse_args exits if '--help' is used, allow this.
         sys.exit(0)
    except Exception as e:
         print(f"Argument Parsing Error: {e}", file=sys.stderr)
         parser.print_help()
         sys.exit(1)


    # --- Mode Dispatch ---
    zfs_manager_client: Optional[ZfsManagerClient] = None
    daemon_process = None

    if args.daemon:
        # --- Daemon Mode --- (Launched via privilege escalation, this handles its own args)
        # The daemon is now expected to be launched via privilege escalation (pkexec/doas/sudo) by daemon_utils.
        # This direct daemon launch logic is kept in case it's needed for debugging
        # but normal operation (GUI/Web) will launch it indirectly.
        if args.uid is None or args.gid is None:
            parser.error("--daemon requires --uid and --gid when run directly.")

        print("MAIN: Standalone Daemon mode requested.", file=sys.stderr)
        try:
            import zfs_daemon
            zfs_daemon.main() # Assumes zfs_daemon.main uses argparse
        except ImportError as e:
            print(f"MAIN: Error importing zfs_daemon: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"MAIN: Error running zfs_daemon: {e}\n{traceback.format_exc()}", file=sys.stderr)
            sys.exit(1)

    elif args.stop_daemon is not None:
        # --- Stop Daemon Mode ---
        from paths import get_daemon_socket_path
        socket_path = args.stop_daemon if args.stop_daemon else get_daemon_socket_path(os.getuid())
        
        print(f"MAIN: Stopping daemon at {socket_path}...", file=sys.stderr)
        try:
            stop_socket_daemon(socket_path)
        except Exception as e:
            print(f"MAIN: Failed to stop daemon: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    elif args.launch_daemon is not None:
        # --- Launch Daemon Mode (launch and exit) ---
        from paths import get_daemon_socket_path
        socket_path = args.launch_daemon if args.launch_daemon else get_daemon_socket_path(os.getuid())
        
        # Check if already running
        if os.path.exists(socket_path):
            try:
                transport = connect_to_existing_socket_daemon(socket_path)
                transport.close()
                print(f"MAIN: Daemon already running at {socket_path}", file=sys.stderr)
                
                # Ask to restart if interactive
                if sys.stdin.isatty():
                    try:
                        response = input("Restart daemon? [y/N]: ").strip().lower()
                        if response in ('y', 'yes'):
                            stop_socket_daemon(socket_path)
                            # Wait for daemon to fully shutdown
                            import time
                            for _ in range(10):  # Up to 5 seconds
                                time.sleep(0.5)
                                try:
                                    test = connect_to_existing_socket_daemon(socket_path)
                                    test.close()
                                except Exception:
                                    break  # Daemon is down
                        else:
                            sys.exit(0)
                    except (EOFError, KeyboardInterrupt):
                        sys.exit(0)
                else:
                    sys.exit(0)
            except Exception:
                pass  # Not running (stale socket), will launch
        
        print(f"MAIN: Launching daemon at {socket_path}...", file=sys.stderr)
        try:
            daemon_process, transport = launch_daemon(use_socket=True, debug=args.debug)
            print(f"MAIN: Daemon launched successfully (PID: {daemon_process.pid})", file=sys.stderr)
            print(f"MAIN: Socket: {socket_path}", file=sys.stderr)
            transport.close()  # Disconnect, daemon keeps running
        except Exception as e:
            print(f"MAIN: Failed to launch daemon: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    elif args.web or not (args.web or args.daemon):
        # --- Web UI or GUI Mode --- (Both need a daemon)
        mode = "Web UI" if args.web else "GUI"
        
        # Determine connection mode: socket (--socket or --connect-socket) vs pipe (default)
        use_socket_mode = args.socket is not None or args.connect_socket is not None
        
        if use_socket_mode:
            # --- Socket Mode ---
            from paths import get_daemon_socket_path
            
            # Determine socket path and whether we can auto-launch
            if args.connect_socket is not None:
                # --connect-socket: connect only, no auto-launch
                allow_launch = False
                socket_path = args.connect_socket if args.connect_socket else get_daemon_socket_path(os.getuid())
            else:
                # --socket: connect or launch
                allow_launch = True
                socket_path = args.socket if args.socket else get_daemon_socket_path(os.getuid())
            
            print(f"MAIN: {mode} using socket mode (path: {socket_path}, auto-launch: {allow_launch})", file=sys.stderr)
            
            try:
                # Try connecting to existing socket daemon
                transport = connect_to_existing_socket_daemon(socket_path)
                
                # Socket mode: daemon persists, we don't own it
                zfs_manager_client = ZfsManagerClient(None, transport, owns_daemon=False)
                _zfs_client = zfs_manager_client  # Register for cleanup
                
                print("MAIN: ZFS Manager client created. Proceeding with UI launch.", file=sys.stderr)
                
            except (FileNotFoundError, RuntimeError) as e:
                # Socket doesn't exist or connection failed
                if not allow_launch:
                    _show_startup_error(f"{mode} Connection Error", str(e))
                    sys.exit(1)
                
                # --socket mode: launch new daemon
                print(f"MAIN: {e}", file=sys.stderr)
                print(f"MAIN: Launching new socket daemon...", file=sys.stderr)
                try:
                    daemon_process, transport = launch_daemon(use_socket=True, debug=args.debug)
                    print(f"MAIN: Daemon launched (PID: {daemon_process.pid}). Socket: {socket_path}", file=sys.stderr)
                    
                    # Socket mode: daemon persists, we don't own it (don't track daemon_process)
                    zfs_manager_client = ZfsManagerClient(None, transport, owns_daemon=False)
                    _zfs_client = zfs_manager_client  # Register for cleanup
                    
                    print("MAIN: ZFS Manager client created. Proceeding with UI launch.", file=sys.stderr)
                except Exception as launch_e:
                    _show_startup_error(f"{mode} Startup Error", 
                                      f"Failed to launch daemon:\n{launch_e}")
                    sys.exit(1)
        else:
            # --- Pipe Mode (default) ---
            print(f"MAIN: {mode} mode requested. Launching pipe-mode daemon...", file=sys.stderr)
            try:
                print("MAIN: Launching daemon...", file=sys.stderr)
                daemon_process, transport = launch_daemon(use_socket=False, debug=args.debug)
                _daemon_process = daemon_process  # Register for cleanup (before client created)
                print(f"MAIN: Daemon launched successfully (PID: {daemon_process.pid}). Creating client...", file=sys.stderr)

                # Pipe mode: we own the daemon, it dies when we close
                zfs_manager_client = ZfsManagerClient(daemon_process, transport, owns_daemon=True)
                _zfs_client = zfs_manager_client  # Register for cleanup

                print("MAIN: ZFS Manager client created. Proceeding with UI launch.", file=sys.stderr)
            except (RuntimeError, TimeoutError, ValueError) as e:
                _show_startup_error(f"{mode} Startup Error", f"Failed to launch or connect to the ZFS daemon:\n{e}\n\nPlease check system logs or Polkit permissions.")
                sys.exit(1) # Exit after showing the error
            except ImportError as e:
                _show_startup_error("Import Error", f"Failed to import required {mode} or utility components:\n{e}")
                sys.exit(1)
            except Exception as e:
                _show_startup_error(f"{mode} Startup Error", f"An unexpected error occurred during {mode} startup or daemon interaction:\n{e}\n\n{traceback.format_exc()}")
                sys.exit(1)
        
        # Common UI launch code for both connection methods
        try:
            # --- Launch the requested UI ---
            if args.web:
                import web_ui
                web_ui.run_web_ui(host=args.host, port=args.port, debug=args.debug, zfs_client=zfs_manager_client)
            else:
                # GUI Mode (Default)
                import gui_runner
                exit_code = gui_runner.start_gui(zfs_client=zfs_manager_client)
                sys.exit(exit_code)

        except ImportError as e:
            _show_startup_error("Import Error", f"Failed to import required {mode} components:\n{e}")
            sys.exit(1)
        except Exception as e:
             _show_startup_error(f"{mode} Runtime Error", f"An unexpected error occurred during {mode} execution:\n{e}\n\n{traceback.format_exc()}")
             sys.exit(1)
        # Cleanup handled by atexit/_signal_handler via _cleanup()


# --- END OF FILE src/main.py ---
