#!/usr/bin/env python3
# --- START OF FILE src/main.py ---
import sys
import os
import platform
import traceback # Keep for error reporting if needed
import argparse # Import argparse
from typing import Optional

# Import new dependencies
from ipc_client import launch_daemon
from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError
import constants
from paths import IS_FROZEN


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
        "%(prog)s [-h] [-w] [--host HOST] [-p PORT] [--debug] [--socket] [--connect-socket [PATH]]\n"
        "   or: %(prog)s --daemon --uid UID --gid GID [--listen-socket [PATH]]\n"
        "   or: %(prog)s --connect-socket [PATH]  # Connect to existing daemon\n"
    )

    parser = argparse.ArgumentParser(
        usage=usage_str,
        description="ZfDash ZFS Manager",
        formatter_class=RawDefaultsHelpFormatter,
        epilog=(
            "Examples:\n"
            "  Run GUI with auto-launched daemon (default):\n"
            "    python3 src/main.py\n\n"
            "  Run Web UI (auto-launch daemon):\n"
            "    python3 src/main.py --web\n\n"
            "  Connect GUI/Web to existing daemon socket (default path):\n"
            "    python3 src/main.py --connect-socket\n\n"
            "  Connect to explicit daemon socket path:\n"
            "    python3 src/main.py --web --connect-socket /run/user/1000/zfdash.sock\n\n"
            # linux-only: the example above uses '/run/user/1000' which follows systemd/XDG runtime dir layout; other OSes may use different paths
            "  Start the daemon manually (run as root or with privilege escalation):\n"
            "    sudo python3 src/main.py --daemon --uid $(id -u) --gid $(id -g) --listen-socket\n"
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
    client_group.add_argument('--debug', action='store_true', help='Enable debug mode for the Web UI server (verbose logging).')
    client_group.add_argument('--socket', action='store_true', help='Use Unix socket IPC instead of pipes, and launch daemon automatically (experimental).')
    client_group.add_argument('--connect-socket', type=str, metavar='PATH', nargs='?', const='',
                              help='Connect to existing daemon socket instead of launching one. If PATH not specified, uses default from get_daemon_socket_path(uid).')

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

    elif args.web or not (args.web or args.daemon):
        # --- Web UI or GUI Mode --- (Both need a daemon)
        mode = "Web UI" if args.web else "GUI"
        
        # Check if connecting to existing daemon socket
        if args.connect_socket is not None:  # Flag present (with or without path)
            # Determine socket path
            if args.connect_socket == '':  # Flag present but no path specified
                from paths import get_daemon_socket_path
                socket_path = get_daemon_socket_path(os.getuid())
                print(f"MAIN: Using default daemon socket: {socket_path}", file=sys.stderr)
            else:
                socket_path = args.connect_socket
                print(f"MAIN: Using specified daemon socket: {socket_path}", file=sys.stderr)
            
            # Connect to existing daemon socket
            print(f"MAIN: {mode} connecting to existing daemon at {socket_path}...", file=sys.stderr)
            try:
                from ipc_client import SocketTransport, LineBufferedTransport
                from ipc_helpers import connect_to_unix_socket, wait_for_ready_signal
                
                # Check socket exists
                if not os.path.exists(socket_path):
                    raise FileNotFoundError(f"Socket does not exist: {socket_path}")
                
                # Connect to socket
                client_sock = connect_to_unix_socket(socket_path, timeout=constants.IPC_CONNECT_TIMEOUT, check_process=None)
                transport = SocketTransport(client_sock)
                buffered = LineBufferedTransport(transport)
                wait_for_ready_signal(buffered, process=None, timeout=constants.IPC_CONNECT_TIMEOUT)
                
                print(f"MAIN: Successfully connected to daemon socket.", file=sys.stderr)
                
                # Create fake process object (daemon is external, don't terminate it)
                class ExternalDaemonProcess:
                    def __init__(self):
                        self.pid = 0
                        self.returncode = 1
                    def poll(self): return self.returncode
                    def terminate(self): pass
                    def wait(self, timeout=None): return self.returncode
                    def kill(self): pass
                
                fake_process = ExternalDaemonProcess()
                zfs_manager_client = ZfsManagerClient(fake_process, buffered)
                
                print("MAIN: ZFS Manager client created. Proceeding with UI launch.", file=sys.stderr)
                
            except Exception as e:
                # linux-only: sudo and $(id -u) shell syntax in error message
                _show_startup_error(f"{mode} Connection Error", 
                                  f"Failed to connect to daemon socket:\n{e}\n\nMake sure the daemon is running:\n"
                                  f"sudo python3 src/main.py --daemon --uid $(id -u) --gid $(id -g) --listen-socket {socket_path}")
                sys.exit(1)
        else:
            # Launch own daemon (existing code)
            print(f"MAIN: {mode} mode requested. Launching dedicated daemon...", file=sys.stderr)
            try:
                print("MAIN: Launching daemon...", file=sys.stderr)
                daemon_process, transport = launch_daemon(use_socket=args.socket)
                print(f"MAIN: Daemon launched successfully (PID: {daemon_process.pid}). Creating client...", file=sys.stderr)

                # Create the ZFS Manager Client instance
                zfs_manager_client = ZfsManagerClient(daemon_process, transport)

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
                gui_runner.start_gui(zfs_client=zfs_manager_client)

        except ImportError as e:
            _show_startup_error("Import Error", f"Failed to import required {mode} components:\n{e}")
            sys.exit(1)
        except Exception as e:
             _show_startup_error(f"{mode} Runtime Error", f"An unexpected error occurred during {mode} execution:\n{e}\n\n{traceback.format_exc()}")
             sys.exit(1)
        finally:
            # --- Cleanup --- #
            if zfs_manager_client:
                if args.connect_socket is not None:
                    # External daemon - just close connection, don't terminate
                    print("MAIN: Closing connection to external daemon...", file=sys.stderr)
                    zfs_manager_client.close()
                else:
                    # Own daemon - close and terminate
                    print("MAIN: Shutting down ZFS Manager client and daemon...", file=sys.stderr)
                    zfs_manager_client.close()
            elif 'daemon_process' in locals() and daemon_process and daemon_process.poll() is None:
                 # If client wasn't created but process was, ensure termination (only for own daemon)
                 if args.connect_socket is None:
                     print("MAIN: Terminating daemon process due to early exit...", file=sys.stderr)
                     try:
                         daemon_process.terminate()
                         daemon_process.wait(timeout=constants.TERMINATE_TIMEOUT)
                     except: pass # Ignore errors during cleanup
            print("MAIN: Exiting.", file=sys.stderr)


# --- END OF FILE src/main.py ---
