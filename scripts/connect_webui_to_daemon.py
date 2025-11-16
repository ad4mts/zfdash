#!/usr/bin/env python3
"""
Connect the WebUI to an already-running ZfDash daemon socket.

This script does NOT attempt to launch a daemon. It expects a daemon
to be listening on the Unix socket (default: paths.get_daemon_socket_path(uid)).

Usage:
    sudo python src/main.py --daemon --uid 1000 --gid 1000 --listen-socket /run/user/1000/zfdash.sock
    python scripts/connect_webui_to_daemon.py --socket /run/user/1000/zfdash.sock --host 127.0.0.1 --port 5001
"""
import os
import sys
import argparse

# Ensure project `src/` is importable when running this script from repository root
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_repo_root, 'src')
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from paths import get_daemon_socket_path
from ipc_client import (
    SocketTransport, 
    LineBufferedTransport,
    connect_to_unix_socket,
    wait_for_ready_signal
)
from zfs_manager import ZfsManagerClient


class _FakeProcessForExternalDaemon:
    """
    Minimal Popen-like object for external daemons not launched by this client.
    
    ZfsManagerClient requires a process object, but for external daemons we don't
    want to terminate them on shutdown. This fake provides the required interface
    but makes terminate/kill no-ops.
    """
    def __init__(self, pid=None):
        self.pid = pid or 0
        self.returncode = 1  # Indicate "not our child"

    def poll(self):
        return self.returncode  # Always return non-None (already exited from our perspective)

    def terminate(self):
        pass  # No-op: do not terminate external daemon

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pass  # No-op: do not kill external daemon


def connect_to_existing_daemon(socket_path: str, timeout: float = 10.0) -> LineBufferedTransport:
    """
    Connect to an existing daemon socket and wait for ready signal.
    
    Args:
        socket_path: Path to Unix domain socket
        timeout: Timeout in seconds for connection and ready signal
        
    Returns:
        LineBufferedTransport ready for communication
        
    Raises:
        RuntimeError: If connection fails or ready signal not received
        TimeoutError: If timeout is reached
    """
    print(f"CONNECT: Connecting to daemon socket at {socket_path}")
    
    # Connect to socket using helper (no process monitoring for external daemon)
    try:
        client_sock = connect_to_unix_socket(socket_path, timeout=timeout, check_process=None)
    except Exception as e:
        raise RuntimeError(f"Failed to connect to socket: {e}")
    
    # Wrap in transport
    transport = SocketTransport(client_sock)
    buffered = LineBufferedTransport(transport)
    
    # Wait for ready signal using helper (no process monitoring)
    try:
        wait_for_ready_signal(buffered, process=None, timeout=int(timeout))
        print("CONNECT: Ready signal received!")
        return buffered
    except Exception as e:
        buffered.close()
        raise


def main():
    parser = argparse.ArgumentParser(description="Connect WebUI to existing ZfDash daemon socket")
    parser.add_argument('--socket', '-s', type=str, help='Path to daemon socket (default: get_daemon_socket_path(uid))')
    parser.add_argument('--host', default='127.0.0.1', help='Host for the Web UI server')
    parser.add_argument('--port', '-p', default=5001, type=int, help='Port for the Web UI server')
    parser.add_argument('--timeout', type=float, default=10.0, help='Seconds to wait for socket ready')
    args = parser.parse_args()

    if args.socket:
        socket_path = args.socket
    else:
        uid = os.getuid()
        socket_path = get_daemon_socket_path(uid)

    # Check socket exists
    if not os.path.exists(socket_path):
        print(f"CONNECT: Socket path does not exist: {socket_path}", file=sys.stderr)
        sys.exit(2)

    # Connect and wait for ready signal
    try:
        buffered = connect_to_existing_daemon(socket_path, timeout=args.timeout)
    except Exception as e:
        print(f"CONNECT: Failed to connect: {e}", file=sys.stderr)
        sys.exit(3)

    # Try to get daemon PID from socket credentials (Linux only)
    pid = None
    try:
        transport = buffered.get_transport()
        if hasattr(transport, 'get_peer_credentials'):
            creds = transport.get_peer_credentials()
            if creds:
                pid = creds[0]
                print(f"CONNECT: Daemon PID: {pid}")
    except Exception:
        pass

    # Create fake process object (ZfsManagerClient requires it, but won't terminate external daemon)
    fake_proc = _FakeProcessForExternalDaemon(pid=pid)

    # Construct the manager client
    try:
        client = ZfsManagerClient(fake_proc, buffered)
    except Exception as e:
        print(f"CONNECT: Failed to create ZfsManagerClient: {e}", file=sys.stderr)
        buffered.close()
        sys.exit(4)

    # Inject into web_ui and run the Flask server
    try:
        import web_ui
        web_ui.app.zfs_client = client
        print(f"CONNECT: Starting WebUI on {args.host}:{args.port}")
        web_ui.run_web_ui(host=args.host, port=args.port, debug=False, zfs_client=client)
    except Exception as e:
        print(f"CONNECT: Error running WebUI: {e}", file=sys.stderr)
        client.close()
        sys.exit(5)


if __name__ == '__main__':
    main()
