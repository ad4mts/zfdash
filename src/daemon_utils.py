# --- START OF FILE src/daemon_utils.py ---
# Utility functions for daemon interaction, callable without GUI dependencies.
import os
import shutil #for pkexec path
import sys # Added for stderr printing
import subprocess # Added for launch_daemon
import shlex      # Added for launch_daemon
import traceback  # Added for launch_daemon error reporting
import json       # Added for parsing ready signal
import time       # Added for timeout
import select     # Added for non-blocking read

# --- Constants ---
# Removed SOCKET_NAME, SOCKET_PATH

# Constants moved from gui_runner.py for launch_daemon
POLKIT_DAEMON_LAUNCH_ACTION_ID = "org.zfsgui.pkexec.daemon.launch"
# It assumes main.py is in the same directory as daemon_utils.py
# Adjust if daemon_utils.py is moved relative to main.py
DAEMON_SCRIPT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))


# --- Helper Functions ---

# Moved from gui_runner.py - needed for launch_daemon
def get_user_ids():
    """Gets the current real user ID and group ID."""
    uid = os.getuid()
    gid = os.getgid()
    return uid, gid

# Removed get_socket_path function
# Removed is_daemon_running function

# Modified from gui_runner.py
def launch_daemon():
    """Launches the daemon mode using pkexec (if needed) or directly (if root)
    and establishes pipe communication.

    Waits for a 'ready' signal from the daemon after potential pkexec authentication.

    Returns:
        tuple: (Popen object, write_pipe_fd, read_pipe_fd) on success.
               write_pipe_fd: File descriptor to write commands TO the daemon (parent's write end).
               read_pipe_fd: File descriptor to read responses FROM the daemon (parent's read end).

    Raises:
        RuntimeError: If pkexec is not found (when needed), user ID cannot be obtained,
                      script/executable is missing, pipe creation fails, or the daemon launch fails.
        TimeoutError: If the daemon does not send the 'ready' signal within the timeout period.
        ValueError: If the daemon sends an invalid ready signal.
    """
    print("DAEMON_UTILS(launch_daemon): Attempting to launch ZFS daemon...")

    # --- Get User and Group ID ---
    try:
        user_uid, user_gid = get_user_ids()
        print(f"DAEMON_UTILS(launch_daemon): Current User UID={user_uid}, GID={user_gid}")
    except Exception as e:
        print(f"ERROR: User ID Error\nCould not determine current user/group ID: {e}", file=sys.stderr)
        raise RuntimeError("User ID error") from e

    # --- Determine if we need pkexec ---
    is_running_as_root = (user_uid == 0)
    print(f"DAEMON_UTILS(launch_daemon): Running as root: {is_running_as_root}")

    # --- Find pkexec path dynamically (only if needed) ---
    pkexec_path = None
    if not is_running_as_root:
        pkexec_path = shutil.which("pkexec")
        if not pkexec_path:
            print("ERROR: pkexec command not found\n"
                  "The 'pkexec' command is required to launch the daemon with root privileges when not already running as root.\n"
                  "Please install the 'pkexec' package (or equivalent for your distribution).", file=sys.stderr)
            raise RuntimeError("pkexec command not found")
        print(f"DAEMON_UTILS(launch_daemon): Found pkexec at: {pkexec_path}")


    # --- Determine how to call the script/executable ---
    python_executable = sys.executable
    is_frozen = getattr(sys, 'frozen', False)
    cmd_to_execute = [] # Will hold the final command list

    if is_frozen:
        # --- Running as a bundled executable ---
        print("DAEMON_UTILS(launch_daemon): Detected frozen executable execution.")
        if not python_executable or not os.path.exists(python_executable):
             print(f"ERROR: Executable Error\nBundled executable path '{python_executable}' not found.", file=sys.stderr)
             raise RuntimeError("Executable error")

        base_cmd = [python_executable, '--daemon', '--uid', str(user_uid), '--gid', str(user_gid)]
        if is_running_as_root:
            cmd_to_execute = base_cmd
            print("DAEMON_UTILS(launch_daemon): Will execute daemon directly (frozen, as root).")
        else:
            cmd_to_execute = [pkexec_path] + base_cmd
            print("DAEMON_UTILS(launch_daemon): Will execute daemon via pkexec (frozen, non-root).")

    else:
        # --- Running as a Python script ---
        print("DAEMON_UTILS(launch_daemon): Detected script execution.")
        if not python_executable or not os.path.exists(python_executable):
             print(f"ERROR: Python Error\nPython interpreter '{python_executable}' not found.", file=sys.stderr)
             raise RuntimeError("Python error")
        if not os.path.exists(DAEMON_SCRIPT_PATH):
             print(f"ERROR: Script Error\nMain script '{DAEMON_SCRIPT_PATH}' not found for execution.", file=sys.stderr)
             raise RuntimeError("Script error")

        base_cmd = [python_executable, DAEMON_SCRIPT_PATH, '--daemon', '--uid', str(user_uid), '--gid', str(user_gid)]
        if is_running_as_root:
            cmd_to_execute = base_cmd
            print("DAEMON_UTILS(launch_daemon): Will execute daemon directly (script, as root).")
        else:
            cmd_to_execute = [pkexec_path] + base_cmd
            print("DAEMON_UTILS(launch_daemon): Will execute daemon via pkexec (script, non-root).")


    # Removed Policy File Check - pkexec handles policy inherently

    # --- Create Communication Pipes ---
    pipe_to_daemon_r, pipe_to_daemon_w = -1, -1
    pipe_from_daemon_r, pipe_from_daemon_w = -1, -1
    try:
        # Pipe for Parent -> Daemon communication (Parent writes, Daemon reads from stdin)
        pipe_to_daemon_r, pipe_to_daemon_w = os.pipe()
        # Pipe for Daemon -> Parent communication (Daemon writes to stdout, Parent reads)
        pipe_from_daemon_r, pipe_from_daemon_w = os.pipe()

        print(f"DAEMON_UTILS(launch_daemon): Pipes created: "
              f"P->D ({pipe_to_daemon_r}, {pipe_to_daemon_w}), "
              f"D->P ({pipe_from_daemon_r}, {pipe_from_daemon_w})")

    except OSError as e:
        print(f"ERROR: Pipe Creation Failed\nCould not create communication pipes: {e}", file=sys.stderr)
        # Clean up any partially created pipes
        if pipe_to_daemon_r != -1: os.close(pipe_to_daemon_r)
        if pipe_to_daemon_w != -1: os.close(pipe_to_daemon_w)
        if pipe_from_daemon_r != -1: os.close(pipe_from_daemon_r)
        if pipe_from_daemon_w != -1: os.close(pipe_from_daemon_w)
        raise RuntimeError(f"Pipe creation failed: {e}") from e

    # --- Execute cmd_to_execute (either direct or via pkexec) with Pipe Redirection ---
    print(f"DAEMON_UTILS(launch_daemon): Executing: {shlex.join(cmd_to_execute)}") # Changed pkexec_cmd to cmd_to_execute
    process = None
    try:
        current_env = os.environ.copy()
        process = subprocess.Popen(
            cmd_to_execute, # Changed pkexec_cmd to cmd_to_execute
            env=current_env,
            stdin=pipe_to_daemon_r,      # Daemon reads from this pipe's read end
            stdout=pipe_from_daemon_w,   # Daemon writes to this pipe's write end
            stderr=subprocess.DEVNULL,   # Or redirect stderr if needed later
            # close_fds=True is default and generally good, but Popen handles
            # the passed stdin/stdout FDs correctly on POSIX.
            # We MUST close the parent's copies of the child's ends manually.
        )

        # --- Parent Closes Unused Pipe Ends ---
        # Parent doesn't need the daemon's reading end of the first pipe
        os.close(pipe_to_daemon_r)
        # Parent doesn't need the daemon's writing end of the second pipe
        os.close(pipe_from_daemon_w)

        # Prevent resource leaks if Popen failed after pipes were created
        pipe_to_daemon_r = -1 # Mark as closed in parent
        pipe_from_daemon_w = -1 # Mark as closed in parent

        print(f"DAEMON_UTILS(launch_daemon): Daemon process launched (PID: {process.pid}). Parent keeps pipe ends: "
              f"Write={pipe_to_daemon_w}, Read={pipe_from_daemon_r}")

        # --- Wait for Daemon Ready Signal ---
        print(f"DAEMON_UTILS(launch_daemon): Waiting for ready signal from daemon (PID: {process.pid})...")
        READY_TIMEOUT = 60 # seconds (adjust as needed, pkexec prompt can take time)
        start_time = time.monotonic()
        ready = False
        read_buffer = b"" # Buffer for accumulating reads
        try:
            # Set the read pipe to non-blocking mode temporarily
            import fcntl
            flags = fcntl.fcntl(pipe_from_daemon_r, fcntl.F_GETFL)
            fcntl.fcntl(pipe_from_daemon_r, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            while time.monotonic() - start_time < READY_TIMEOUT:
                # --- MOVED: Check for premature exit FIRST --- 
                proc_status = process.poll()
                if proc_status is not None:
                    print(f"DAEMON_UTILS(launch_daemon): Daemon process exited prematurely with status {proc_status} before sending ready signal.", file=sys.stderr)
                    # Restore blocking mode before raising
                    fcntl.fcntl(pipe_from_daemon_r, fcntl.F_SETFL, flags)
                    raise RuntimeError(f"Daemon exited prematurely (status {proc_status}). Authentication likely failed or cancelled.")
                # --- END MOVE --- 

                # Check if data is available to read without blocking
                readable, _, _ = select.select([pipe_from_daemon_r], [], [], 0.1) # 100ms timeout

                if readable:
                    try:
                        chunk = os.read(pipe_from_daemon_r, 1024) # Read up to 1KB
                        if not chunk: # EOF, process exited
                            print(f"DAEMON_UTILS(launch_daemon): Reached EOF reading from daemon FD {pipe_from_daemon_r} before ready signal.", file=sys.stderr)
                            # --- MODIFIED: Get status again, but raise specific error if it exited here ---
                            proc_status = process.poll() # Check status again
                            # Restore blocking mode before raising
                            fcntl.fcntl(pipe_from_daemon_r, fcntl.F_SETFL, flags)
                            if proc_status is not None:
                                raise RuntimeError(f"Daemon exited prematurely (status {proc_status}) causing EOF, before sending ready signal. Authentication likely failed or cancelled.")
                            else:
                                # Should be rare if poll() above didn't catch it, but handle just in case
                                raise RuntimeError(f"Daemon closed connection unexpectedly causing EOF (unknown exit status) before sending ready signal.")
                            # --- END MODIFICATION ---
                        
                        read_buffer += chunk
                        # Check if we have a complete line in the buffer
                        if b'\n' in read_buffer:
                            line_bytes, read_buffer = read_buffer.split(b'\n', 1)
                            line = line_bytes.decode('utf-8', errors='replace').strip()
                            print(f"DAEMON_UTILS(launch_daemon): Received line from daemon: {line}")
                            try:
                                signal = json.loads(line)
                                if isinstance(signal, dict) and signal.get("status") == "ready":
                                    print(f"DAEMON_UTILS(launch_daemon): Received valid ready signal from daemon.")
                                    ready = True
                                    break # Exit the while loop
                                else:
                                    print(f"DAEMON_UTILS(launch_daemon): Received unexpected non-ready JSON from daemon: {line}", file=sys.stderr)
                                    # Continue waiting, maybe it's just log output before ready signal
                            except json.JSONDecodeError:
                                print(f"DAEMON_UTILS(launch_daemon): Received non-JSON line from daemon: {line}", file=sys.stderr)
                                # Continue waiting
                        # Else: keep accumulating data
                    except BlockingIOError:
                        # This shouldn't happen often due to select, but handle it just in case
                        pass # No data available right now, continue loop
                    except OSError as read_err:
                        # Handle potential errors during read (e.g., if pipe closes unexpectedly)
                        print(f"DAEMON_UTILS(launch_daemon): Error reading from daemon pipe FD {pipe_from_daemon_r}: {read_err}", file=sys.stderr)
                        proc_status = process.poll() # Check status again
                        raise RuntimeError(f"Error reading from daemon pipe (status {proc_status}): {read_err}")

            # --- MODIFIED: Restore blocking mode --- 
            fcntl.fcntl(pipe_from_daemon_r, fcntl.F_SETFL, flags) # Restore original flags

            if not ready:
                print(f"DAEMON_UTILS(launch_daemon): Timeout ({READY_TIMEOUT}s) waiting for ready signal from daemon.", file=sys.stderr)
                raise TimeoutError(f"Daemon did not send ready signal within {READY_TIMEOUT} seconds.")

        except Exception as wait_err:
            # Catch errors during the wait/read process and re-raise
            print(f"DAEMON_UTILS(launch_daemon): Error during wait for ready signal: {wait_err}", file=sys.stderr)
            # Ensure cleanup happens in the outer finally block
            # --- MODIFIED: Ensure blocking mode is restored on error too --- 
            try:
                fcntl.fcntl(pipe_from_daemon_r, fcntl.F_SETFL, flags) # Restore original flags on error path
            except Exception as fcntl_err:
                 print(f"DAEMON_UTILS(launch_daemon): Warning - failed to restore pipe blocking mode on error: {fcntl_err}", file=sys.stderr)
            raise # Re-raise the caught exception (RuntimeError, TimeoutError, etc.)
        finally:
            # --- REMOVED: No daemon_stdout_reader to manage --- 
            # --- MODIFIED: Ensure blocking mode is restored in finally too (belt and suspenders) --- 
            try:
                fcntl.fcntl(pipe_from_daemon_r, fcntl.F_SETFL, flags) # Restore original flags in finally
            except Exception as fcntl_err:
                 print(f"DAEMON_UTILS(launch_daemon): Warning - failed to restore pipe blocking mode in finally: {fcntl_err}", file=sys.stderr)
            # If an error occurred, the outer exception handler will close the FDs.
            # pass # No longer needed
        # --- END Wait for Daemon Ready Signal ---

        # Return the process object and the pipe FDs the parent will use
        return process, pipe_to_daemon_w, pipe_from_daemon_r

    except Exception as e:
        print(f"ERROR: Daemon Launch Error\nAn unexpected error occurred launching the daemon or waiting for ready signal:\n{e}", file=sys.stderr) # Updated error message

        # --- Cleanup on Failure ---
        # Close any remaining pipe FDs that the parent might still hold
        if pipe_to_daemon_r != -1: os.close(pipe_to_daemon_r) # Child's stdin read end
        if pipe_to_daemon_w != -1: os.close(pipe_to_daemon_w) # Parent's stdin write end
        if pipe_from_daemon_r != -1: os.close(pipe_from_daemon_r) # Parent's stdout read end
        if pipe_from_daemon_w != -1: os.close(pipe_from_daemon_w) # Child's stdout write end

        # Try to terminate the process if it started
        if process and process.poll() is None:
            try:
                print("DAEMON_UTILS(launch_daemon): Terminating potentially started daemon process due to error.")
                process.terminate()
                process.wait(timeout=1)
            except Exception as term_e:
                print(f"DAEMON_UTILS(launch_daemon): Error during cleanup termination: {term_e}", file=sys.stderr)

        # --- Re-raise the original exception or a new RuntimeError --- <<< MODIFIED
        if isinstance(e, (RuntimeError, TimeoutError, ValueError)): # If it was one of our specific errors
            raise e
        else: # Otherwise wrap it
            raise RuntimeError(f"Daemon launch failed: {e}") from e

# --- END OF FILE src/daemon_utils.py ---
