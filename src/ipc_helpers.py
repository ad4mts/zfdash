"""
IPC Helper Functions

Shared utilities for socket operations and daemon communication.
Used by: ipc_client.py, ipc_server.py, scripts/connect_webui_to_daemon.py

This module contains NO privilege escalation or daemon launching code.
It's safe to import from both client and server sides.
"""

import os
import sys
import socket
import select
import json
import time
import subprocess
from typing import Optional, TYPE_CHECKING

import constants

if TYPE_CHECKING:
    from ipc_client import LineBufferedTransport


# ============================================================================
# Socket Helper Functions
# ============================================================================

def check_socket_in_use(socket_path: str) -> bool:
    """
    Check if a Unix socket is currently in use (daemon listening).

    Args:
        socket_path: Path to Unix domain socket file

    Returns:
        True if socket exists and daemon is listening, False otherwise
    """
    if not os.path.exists(socket_path):
        return False

    test_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        test_sock.connect(socket_path)
        test_sock.close()
        return True  # Socket is in use
    except (ConnectionRefusedError, FileNotFoundError):
        return False  # Socket file exists but not listening (stale)
    finally:
        try:
            test_sock.close()
        except Exception:
            pass


def check_and_remove_stale_socket(socket_path: str) -> bool:
    """
    Check if a socket file is stale (no daemon listening) and remove it.

    Args:
        socket_path: Path to Unix domain socket file

    Returns:
        True if socket was stale and removed, False if no socket exists,
        raises RuntimeError if socket is active (daemon already running)

    Raises:
        RuntimeError: If socket exists and daemon is listening on it
    """
    if not os.path.exists(socket_path):
        return False

    # Check if socket is in use
    if check_socket_in_use(socket_path):
        raise RuntimeError(
            f"A daemon is already running on socket {socket_path}. "
            f"Use 'python scripts/connect_webui_to_daemon.py --socket {socket_path}' "
            f"to connect to it, or stop the existing daemon first."
        )

    # Socket file exists but no daemon listening - it's stale
    try:
        os.unlink(socket_path)
        print(f"IPC: Removed stale socket at {socket_path}")
        return True
    except OSError as e:
        print(f"IPC: Warning - could not remove stale socket: {e}", file=sys.stderr)
        return False


def connect_to_unix_socket(socket_path: str,
                          timeout: float = constants.IPC_CONNECT_TIMEOUT,
                          check_process: Optional[subprocess.Popen] = None) -> socket.socket:
    """
    Connect to Unix domain socket with retry logic and optional process monitoring.

    This function:
    - Polls for socket file to exist
    - Retries connection attempts (socket may exist but not be listening yet)
    - Optionally monitors a process for premature exit

    Args:
        socket_path: Path to Unix domain socket
        timeout: Total timeout in seconds
        check_process: Optional subprocess to monitor for premature exit

    Returns:
        Connected socket.socket object

    Raises:
        RuntimeError: If process exits prematurely
        TimeoutError: If connection not established within timeout
        OSError: If socket connection fails
    """
    start_time = time.time()
    client_sock = None

    while time.time() - start_time < timeout:
        # Check if monitored process died
        if check_process and check_process.poll() is not None:
            raise RuntimeError(
                f"Process exited prematurely (exit code: {check_process.returncode})"
            )

        # Try to connect to socket
        if os.path.exists(socket_path):
            try:
                client_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client_sock.connect(socket_path)
                return client_sock  # Success!
            except (socket.error, ConnectionRefusedError):
                # Socket exists but not ready yet - retry
                if client_sock:
                    try:
                        client_sock.close()
                    except Exception:
                        pass
                    client_sock = None
                time.sleep(constants.POLL_INTERVAL)
        else:
            # Socket not created yet - retry
            time.sleep(constants.POLL_INTERVAL)

    # Timeout reached
    raise TimeoutError(
        f"Could not connect to socket within {timeout} seconds at {socket_path}. "
        f"If the daemon is running, another client may be actively connected (sequential mode). "
        f"Wait for the other client to disconnect, or increase --timeout."
    )


def wait_for_ready_signal(transport: 'LineBufferedTransport',
                          process: Optional[subprocess.Popen] = None,
                          timeout: int = constants.IPC_READY_TIMEOUT) -> None:
    """
    Wait for daemon to send ready signal via transport.

    Generic version that works with or without process monitoring.

    Args:
        transport: LineBufferedTransport to read from
        process: Optional daemon subprocess to monitor for premature exit
        timeout: Timeout in seconds

    Raises:
        RuntimeError: If daemon exits prematurely or sends invalid signal
        TimeoutError: If ready signal not received within timeout
    """
    if process:
        print(f"IPC: Waiting for ready signal from daemon (PID: {process.pid})...")
    else:
        print("IPC: Waiting for ready signal from daemon...")

    start_time = time.monotonic()

    try:
        while time.monotonic() - start_time < timeout:
            # Check if daemon exited prematurely (if monitoring)
            if process:
                proc_status = process.poll()
                if proc_status is not None:
                    raise RuntimeError(
                        f"Daemon exited prematurely (status {proc_status}). "
                        "Authentication likely failed or cancelled."
                    )

            # Check for data with select (non-blocking check)
            readable, _, _ = select.select([transport.fileno()], [], [], constants.READY_SELECT_TIMEOUT)

            if readable:
                try:
                    line_bytes = transport.receive_line()

                    if not line_bytes:  # EOF
                        if process:
                            proc_status = process.poll()
                            raise RuntimeError(
                                f"Daemon closed connection (EOF) before ready signal. "
                                f"Exit status: {proc_status}"
                            )
                        else:
                            raise RuntimeError(
                                "Daemon closed connection (EOF) before ready signal."
                            )

                    line = line_bytes.decode('utf-8', errors='replace').strip()
                    print(f"IPC: Received from daemon: {line}")

                    try:
                        signal = json.loads(line)
                        if isinstance(signal, dict) and signal.get("status") == "ready":
                            print("IPC: Received valid ready signal.")
                            return  # Success!
                        else:
                            print(f"IPC: Unexpected JSON (not ready signal): {line}",
                                 file=sys.stderr)
                    except json.JSONDecodeError:
                        print(f"IPC: Non-JSON line from daemon: {line}",
                             file=sys.stderr)

                except BlockingIOError:
                    pass  # No data right now
                except OSError as e:
                    if process:
                        proc_status = process.poll()
                        raise RuntimeError(f"Error reading from daemon: {e} (status {proc_status})")
                    else:
                        raise RuntimeError(f"Error reading from daemon: {e}")

    # Timeout reached
        raise TimeoutError(f"Daemon did not send ready signal within {timeout} seconds.")

    except Exception:
        raise  # Re-raise to caller
