#!/usr/bin/env python3
"""
Test script for TCP transport with TLS negotiation and authentication.

Usage:
1. Start daemon with agent mode (TLS enabled by default):
   sudo python3 src/main.py --daemon --uid $(id -u) --gid $(id -g) --listen-socket --agent --agent-port 5555

2. Start daemon without TLS:
   sudo python3 src/main.py --daemon --uid $(id -u) --gid $(id -g) --listen-socket --agent --agent-port 5555 --no-tls

3. Run this test script:
   python3 scripts/test_tcp_agent.py --host 127.0.0.1 --port 5555 --password admin [--tls|--no-tls]

Test matrix:
- Server TLS + Client TLS → should connect with TLS
- Server no-TLS + Client no-TLS → should connect without TLS
- Server TLS + Client no-TLS → should fail with TLS_REQUIRED
- Server no-TLS + Client TLS → should fail with TLS_UNAVAILABLE
"""

import sys
import os
import argparse
import json

# Add src directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(os.path.dirname(script_dir), 'src')
sys.path.insert(0, src_dir)

from ipc_tcp_client import connect_to_agent, TlsNegotiationError
from ipc_tcp_auth import AuthError


def main():
    parser = argparse.ArgumentParser(description="Test TCP Agent Connection")
    parser.add_argument('--host', default='127.0.0.1', help='Agent host (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=5555, help='Agent port (default: 5555)')
    parser.add_argument('--password', default='admin', help='Admin password (default: admin)')
    
    # TLS options
    tls_group = parser.add_mutually_exclusive_group()
    tls_group.add_argument('--tls', action='store_true', default=True, 
                           help='Use TLS (default)')
    tls_group.add_argument('--no-tls', action='store_true', 
                           help='Disable TLS')
    
    args = parser.parse_args()
    
    use_tls = not args.no_tls
    
    print(f"Connecting to agent at {args.host}:{args.port} (TLS: {use_tls})...")
    
    try:
        # Connect and authenticate
        transport, tls_active = connect_to_agent(
            args.host, args.port, args.password, 
            timeout=30.0, use_tls=use_tls
        )
        
        if tls_active:
            print("✓ Connected and authenticated successfully (TLS active)!")
        else:
            print("✓ Connected and authenticated successfully (no TLS)!")
        
        # Wait for ready signal
        ready_line = transport.receive_line()
        ready = json.loads(ready_line.decode('utf-8'))
        print(f"✓ Received ready signal: {ready}")
        
        # Send a simple command (shutdown_daemon as test)
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
        
    except TlsNegotiationError as e:
        print(f"✗ TLS negotiation failed: {e}")
        print(f"  Error code: {e.code}")
        if e.code == "TLS_REQUIRED":
            print("  Hint: Server requires TLS. Try with --tls")
        elif e.code == "TLS_UNAVAILABLE":
            print("  Hint: Server doesn't support TLS. Try with --no-tls")
        return 1
    except AuthError as e:
        print(f"✗ Authentication failed: {e}")
        return 2
    except ConnectionError as e:
        print(f"✗ Connection failed: {e}")
        return 3
    except TimeoutError as e:
        print(f"✗ Timeout: {e}")
        return 4
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 5


if __name__ == "__main__":
    sys.exit(main())
