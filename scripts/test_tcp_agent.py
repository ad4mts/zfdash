#!/usr/bin/env python3
"""
Test script for TCP transport and authentication.

Usage:
1. Start daemon with agent mode:
   sudo python3 src/main.py --daemon --uid $(id -u) --gid $(id -g) --listen-socket --agent --agent-port 5555

2. Run this test script:
   python3 scripts/test_tcp_agent.py --host 127.0.0.1 --port 5555 --password admin
"""

import sys
import os
import argparse
import json

# Add src directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(os.path.dirname(script_dir), 'src')
sys.path.insert(0, src_dir)

from ipc_tcp_client import connect_to_agent
from ipc_tcp_auth import AuthError


def main():
    parser = argparse.ArgumentParser(description="Test TCP Agent Connection")
    parser.add_argument('--host', default='127.0.0.1', help='Agent host (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=5555, help='Agent port (default: 5555)')
    parser.add_argument('--password', default='admin', help='Admin password (default: admin)')
    args = parser.parse_args()
    
    print(f"Connecting to agent at {args.host}:{args.port}...")
    
    try:
        # Connect and authenticate
        transport = connect_to_agent(args.host, args.port, args.password)
        print("✓ Connected and authenticated successfully!")
        
        # Wait for ready signal
        ready_line = transport.receive_line()
        ready = json.loads(ready_line.decode('utf-8'))
        print(f"✓ Received ready signal: {ready}")
        
        # Send a simple command (get version info)
        request = {
            "command": "shutdown_daemon",
            "args": [],
            "kwargs": {},
            "meta": {"request_id": 1}
        }
        print(f"Sending command: {request['command']}")
        transport.send_line(json.dumps(request).encode('utf-8'))
        
        # Receive response
        response_line = transport.receive_line()
        response = json.loads(response_line.decode('utf-8'))
        print(f"✓ Received response: {json.dumps(response, indent=2)}")
        
        # Close connection
        transport.close()
        print("✓ Connection closed cleanly")
        
        return 0
        
    except AuthError as e:
        print(f"✗ Authentication failed: {e}")
        return 1
    except ConnectionError as e:
        print(f"✗ Connection failed: {e}")
        return 2
    except TimeoutError as e:
        print(f"✗ Timeout: {e}")
        return 3
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 4


if __name__ == "__main__":
    sys.exit(main())
