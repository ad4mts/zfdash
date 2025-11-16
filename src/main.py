# --- START OF FILE src/main.py ---
import sys
import os
import platform
import traceback # Keep for error reporting if needed
import argparse # Import argparse
from typing import Optional

# Import new dependencies
import daemon_utils
from zfs_manager import ZfsManagerClient, ZfsCommandError, ZfsClientCommunicationError
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
    parser = argparse.ArgumentParser(description="ZfDash ZFS Manager")
    parser.add_argument('--daemon', action='store_true', help="Run the background daemon process (requires --uid and --gid).")
    parser.add_argument('--uid', type=int, help="User ID for daemon to target (required with --daemon).")
    parser.add_argument('--gid', type=int, help="Group ID for daemon to target (required with --daemon).")
    parser.add_argument('--web', '-w', action='store_true', help="Run the Web UI interface.")
    parser.add_argument('--host', default='127.0.0.1', help="Host for the Web UI server (default: 127.0.0.1).")
    parser.add_argument('--port', '-p', default=5001, type=int, help="Port for the Web UI server (default: 5001).")
    parser.add_argument('--debug', action='store_true', help="Enable debug mode for Web UI server.")

    # Filter out platform-specific launcher arguments when frozen (for future macOS .app bundle support)
    main_args = sys.argv[1:]
    if IS_FROZEN and platform.system() == "Darwin":
        # macOS Finder injects -psn_<ProcessSerialNumber> when launching .app bundles
        main_args = [arg for arg in main_args if not arg.startswith('-psn_')]

    try:
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
        # --- Daemon Mode --- (Launched via pkexec, this handles its own args)
        # The daemon is now expected to be launched via pkexec by daemon_utils.
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
        print(f"MAIN: {mode} mode requested. Launching dedicated daemon...", file=sys.stderr)
        try:
            # Launch the daemon using daemon_utils
            # This call now blocks until the daemon is ready or fails/times out
            print("MAIN: Calling daemon_utils.launch_daemon()...", file=sys.stderr)
            daemon_process, stdin_fd, stdout_fd = daemon_utils.launch_daemon()
            print(f"MAIN: daemon_utils.launch_daemon() returned successfully (PID: {daemon_process.pid}). Creating client...", file=sys.stderr)

            # Create the ZFS Manager Client instance
            zfs_manager_client = ZfsManagerClient(daemon_process, stdin_fd, stdout_fd)

            print("MAIN: ZFS Manager client created. Proceeding with UI launch.", file=sys.stderr)

            # --- Launch the requested UI ---
            if args.web:
                import web_ui
                web_ui.run_web_ui(host=args.host, port=args.port, debug=args.debug, zfs_client=zfs_manager_client)
            else:
                # GUI Mode (Default)
                import gui_runner
                gui_runner.start_gui(zfs_client=zfs_manager_client)

        except (RuntimeError, TimeoutError, ValueError) as e:
            # Catch specific errors from daemon_utils.launch_daemon
            _show_startup_error(f"{mode} Startup Error", f"Failed to launch or connect to the ZFS daemon:\n{e}\n\nPlease check system logs or Polkit permissions.")
            sys.exit(1) # Exit after showing the error
        except ImportError as e:
            _show_startup_error("Import Error", f"Failed to import required {mode} or utility components:\n{e}")
            sys.exit(1)
        except Exception as e:
             _show_startup_error(f"{mode} Startup Error", f"An unexpected error occurred during {mode} startup or daemon interaction:\n{e}\n\n{traceback.format_exc()}")
             sys.exit(1)
        finally:
            # --- Cleanup --- #
            if zfs_manager_client:
                print("MAIN: Shutting down ZFS Manager client and daemon...", file=sys.stderr)
                zfs_manager_client.close()
            elif daemon_process and daemon_process.poll() is None:
                 # If client wasn't created but process was, ensure termination
                 print("MAIN: Terminating daemon process due to early exit...", file=sys.stderr)
                 try:
                     daemon_process.terminate()
                     daemon_process.wait(timeout=2)
                 except: pass # Ignore errors during cleanup
            print("MAIN: Exiting.", file=sys.stderr)


# --- END OF FILE src/main.py ---
