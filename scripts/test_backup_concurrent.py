#!/usr/bin/env python3
"""
Test script for concurrent backup functionality.

Tests the new async backup system:
1. Start backup and verify job_id is returned
2. Query job status during backup (simulated)
3. List all backup jobs
4. Cancel a backup job

Usage:
    # Start two agents on different ports:
    sudo python3 src/main.py --agent --agent-port 5555 &
    sudo python3 src/main.py --agent --agent-port 5556 &
    
    # Run tests:
    python3 scripts/test_backup_concurrent.py --source-port 5555 --dest-port 5556
"""

import sys
import os
import argparse
import json
import time

# Add src directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(os.path.dirname(script_dir), 'src')
sys.path.insert(0, src_dir)

from ipc_tcp_client import connect_to_agent
from ipc_tcp_auth import AuthError


def send_command(transport, command, **kwargs):
    """Send a command and return the response."""
    request = {
        "command": command,
        "args": [],
        "kwargs": kwargs,
        "meta": {"request_id": f"{command}_{int(time.time())}"}
    }
    transport.send_line(json.dumps(request).encode('utf-8'))
    response_line = transport.receive_line()
    return json.loads(response_line.decode('utf-8'))


def test_list_backup_jobs(transport):
    """Test listing backup jobs."""
    print("\n=== Test: List Backup Jobs ===")
    response = send_command(transport, "list_backup_jobs", include_completed=True)
    
    if response.get("status") == "success":
        jobs = response.get("data", {})
        print(f"✓ Found {len(jobs)} backup job(s)")
        for job_id, job in jobs.items():
            print(f"  - {job_id}: {job.get('state')} ({job.get('direction')})")
        return True
    else:
        print(f"✗ Failed: {response.get('error')}")
        return False


def test_get_backup_status(transport, job_id):
    """Test getting specific job status."""
    print(f"\n=== Test: Get Backup Status for {job_id} ===")
    response = send_command(transport, "get_backup_status", job_id=job_id)
    
    if response.get("status") == "success":
        job = response.get("data", {})
        print(f"✓ Job {job_id}:")
        print(f"  State: {job.get('state')}")
        print(f"  Bytes: {job.get('bytes_transferred', 0)}")
        print(f"  Progress: {job.get('progress_percent', 'N/A')}%")
        return True
    else:
        print(f"✗ Failed: {response.get('error')}")
        return False


def test_cancel_nonexistent(transport):
    """Test canceling a non-existent job."""
    print("\n=== Test: Cancel Non-existent Job ===")
    response = send_command(transport, "cancel_backup", job_id="nonexistent123")
    
    if response.get("status") == "error":
        print(f"✓ Correctly rejected: {response.get('error')}")
        return True
    else:
        print(f"✗ Should have failed but got: {response}")
        return False


def test_start_receive_backup(transport, dest_dataset="testpool/backup"):
    """Test starting a receive backup job."""
    print(f"\n=== Test: Start Receive Backup to {dest_dataset} ===")
    response = send_command(
        transport, 
        "start_receive_backup",
        dest_dataset=dest_dataset,
        source_dataset="test/source",
        remote_host="localhost",
        remote_port=0,
        use_tls=True
    )
    
    if response.get("status") == "success":
        data = response.get("data", {})
        job_id = data.get("job_id")
        data_port = data.get("data_port")
        print(f"✓ Created job {job_id} with data port {data_port}")
        return job_id
    else:
        print(f"✗ Failed: {response.get('error')}")
        return None


def test_concurrent_commands(transport):
    """Test that we can run other commands while jobs exist."""
    print("\n=== Test: Concurrent Commands ===")
    
    # Try to list pools (should work even if backup is running)
    response = send_command(transport, "list_pools")
    
    if response.get("status") == "success":
        pools = response.get("data", [])
        print(f"✓ list_pools succeeded: {len(pools)} pool(s) found")
        return True
    else:
        print(f"✗ list_pools failed: {response.get('error')}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test Concurrent Backup")
    parser.add_argument('--host', default='127.0.0.1', help='Agent host')
    parser.add_argument('--port', type=int, default=5555, help='Agent port')
    parser.add_argument('--password', default='admin', help='Admin password')
    parser.add_argument('--no-tls', action='store_true', help='Disable TLS')
    args = parser.parse_args()
    
    use_tls = not args.no_tls
    
    print(f"Connecting to agent at {args.host}:{args.port}...")
    
    try:
        transport, tls_active = connect_to_agent(
            args.host, args.port, args.password,
            timeout=30.0, use_tls=use_tls
        )
        print(f"✓ Connected (TLS={tls_active})")
        
        # Wait for ready signal
        ready = transport.receive_line()
        ready_msg = json.loads(ready.decode('utf-8'))
        if ready_msg.get("status") != "ready":
            print(f"✗ Unexpected ready response: {ready_msg}")
            return 1
        print(f"✓ Ready signal received")
        
        # Run tests
        results = []
        
        # Test 1: List jobs (should be empty initially)
        results.append(("List Jobs", test_list_backup_jobs(transport)))
        
        # Test 2: Cancel non-existent job
        results.append(("Cancel Non-existent", test_cancel_nonexistent(transport)))
        
        # Test 3: Concurrent commands
        results.append(("Concurrent Commands", test_concurrent_commands(transport)))
        
        # Test 4: Start a receive backup (this will create a data channel)
        job_id = test_start_receive_backup(transport)
        results.append(("Start Receive Backup", job_id is not None))
        
        if job_id:
            # Test 5: Get status of the job we just created
            results.append(("Get Job Status", test_get_backup_status(transport, job_id)))
            
            # Test 6: List jobs again (should now have our job)
            results.append(("List Jobs (with job)", test_list_backup_jobs(transport)))
            
            # Test 7: Cancel the job we created
            print(f"\n=== Test: Cancel Job {job_id} ===")
            cancel_response = send_command(transport, "cancel_backup", job_id=job_id)
            if cancel_response.get("status") == "success":
                print(f"✓ Job {job_id} cancelled")
                results.append(("Cancel Job", True))
            else:
                print(f"✗ Failed to cancel: {cancel_response.get('error')}")
                results.append(("Cancel Job", False))
        
        # Summary
        print("\n" + "=" * 50)
        print("SUMMARY")
        print("=" * 50)
        passed = sum(1 for _, r in results if r)
        total = len(results)
        for name, result in results:
            status = "✓ PASS" if result else "✗ FAIL"
            print(f"  {status}: {name}")
        print(f"\nTotal: {passed}/{total} tests passed")
        
        transport.close()
        return 0 if passed == total else 1
        
    except AuthError as e:
        print(f"✗ Authentication failed: {e}")
        return 2
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 3


if __name__ == "__main__":
    sys.exit(main())
