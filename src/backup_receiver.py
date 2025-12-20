"""
Backup Receiver - Application-layer receiver for ZFS backup streams.

Provides BackupReceiver class that:
- Uses DataChannelServer transport for network/TLS/auth
- Pipes data to zfs receive subprocess
- Updates progress in BackupRegistry
- Cleans up automatically
"""

import subprocess
import threading
from typing import Optional, Tuple, TYPE_CHECKING

from debug_logging import daemon_log

# Use the new transport layer
from backup_data_channel import DataChannelServer

if TYPE_CHECKING:
    from backup_core import BackupRegistry


# Import ZFS command path
try:
    from zfs_manager_core import ZFS_CMD_PATH
except ImportError:
    ZFS_CMD_PATH = "/sbin/zfs"


class BackupReceiver:
    """
    High-level backup receiver that uses DataChannelServer transport.
    
    Lifecycle:
    1. Create receiver with job info
    2. Call start() -> returns (host, port, token)
    3. Background thread accepts connection and pipes to zfs receive
    4. Auto-cleans up when complete or on error
    """
    
    CHUNK_SIZE = 65536  # 64KB chunks for progress tracking
    
    def __init__(
        self,
        job_id: str,
        dest_dataset: str,
        registry: "BackupRegistry",
        use_tls: bool = True,
        force_overwrite: bool = True,
    ):
        """
        Initialize backup receiver.
        
        Args:
            job_id: Associated backup job ID
            dest_dataset: Target dataset for zfs receive
            registry: BackupRegistry for progress updates
            use_tls: Whether to use TLS encryption
            force_overwrite: Use -F flag for zfs receive
        """
        self.job_id = job_id
        self.dest_dataset = dest_dataset
        self.registry = registry
        self.use_tls = use_tls
        self.force_overwrite = force_overwrite
        
        self._transport: Optional[DataChannelServer] = None
        self._thread: Optional[threading.Thread] = None
        self._stopped = threading.Event()
    
    def start(self) -> Tuple[str, int, str]:
        """
        Start the backup receiver.
        
        Returns:
            Tuple of (host, port, token) for sender to connect to
            
        Raises:
            RuntimeError: If server fails to start
        """
        # Create transport
        self._transport = DataChannelServer(use_tls=self.use_tls)
        port, token = self._transport.start()
        
        daemon_log(f"BACKUP DATA: Server started on port {port} for job {self.job_id}", "INFO")
        
        # Start background thread for accept + receive
        self._thread = threading.Thread(
            target=self._receive_loop,
            name=f"backup_recv_{self.job_id}",
            daemon=True,
        )
        self._thread.start()
        
        return ("0.0.0.0", port, token)
    
    def stop(self) -> None:
        """Stop the receiver and cleanup resources."""
        self._stopped.set()
        if self._transport:
            self._transport.close()
            self._transport = None
        daemon_log(f"BACKUP DATA: Receiver stopped for job {self.job_id}", "DEBUG")
    
    def _receive_loop(self) -> None:
        """
        Accept connection and pipe received chunks to zfs receive.
        Runs in background thread.
        """
        process = None
        
        try:
            # Wait for sender to connect and verify token
            daemon_log(f"BACKUP DATA: Waiting for connection on port {self._transport.port}", "DEBUG")
            
            try:
                self._transport.accept_and_verify()
                daemon_log(f"BACKUP DATA: Token verified, starting zfs receive", "DEBUG")
            except TimeoutError:
                self._fail_job("Sender did not connect within timeout")
                return
            except PermissionError as e:
                daemon_log(f"BACKUP DATA: Invalid token received", "ERROR")
                self._fail_job("Invalid authentication token")
                return
            except Exception as e:
                self._fail_job(f"Connection failed: {e}")
                return
            
            # Update job state to streaming
            from backup_core import BackupState
            self.registry.update_state(self.job_id, BackupState.STREAMING)
            
            # Build zfs receive command
            recv_cmd = [ZFS_CMD_PATH, "receive"]
            if self.force_overwrite:
                recv_cmd.append("-F")
            recv_cmd.append(self.dest_dataset)
            
            # Start zfs receive subprocess
            process = subprocess.Popen(
                recv_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            
            # Receive chunks and pipe to zfs
            bytes_received = 0
            cancel_event = self.registry.get_cancel_event(self.job_id)
            
            while not self._stopped.is_set():
                # Check for cancellation
                if cancel_event and cancel_event.is_set():
                    daemon_log(f"BACKUP DATA: Job {self.job_id} cancelled", "INFO")
                    process.kill()
                    return
                
                # Receive next chunk from transport (may raise TimeoutError on dead sender)
                try:
                    chunk = self._transport.recv_chunk()
                except TimeoutError as e:
                    # Sender stopped sending data - likely crashed or network partition
                    daemon_log(f"BACKUP DATA: Streaming timeout for job {self.job_id}: {e}", "ERROR")
                    self._fail_job(f"Sender stopped responding - {e}")
                    process.kill()
                    return
                
                if chunk is None:
                    # End of stream or error
                    if bytes_received > 0:
                        daemon_log(f"BACKUP DATA: End of stream marker received", "DEBUG")
                    else:
                        self._fail_job("Connection closed unexpectedly during stream")
                        process.kill()
                        return
                    break
                
                # Write to zfs receive
                try:
                    process.stdin.write(chunk)
                except BrokenPipeError:
                    stderr = process.stderr.read().decode('utf-8', errors='replace')
                    self._fail_job(f"zfs receive failed: {stderr}")
                    return
                
                bytes_received += len(chunk)
                
                # Update progress (every ~1MB to avoid lock contention)
                if bytes_received % (1024 * 1024) < self.CHUNK_SIZE:
                    self.registry.update_progress(self.job_id, bytes_received)
            
            # Close stdin and wait for zfs receive to complete
            process.stdin.close()
            process.wait()
            
            stderr_output = process.stderr.read().decode('utf-8', errors='replace')
            
            if process.returncode != 0:
                self._fail_job(f"zfs receive failed: {stderr_output}")
                return
            
            # Success!
            self.registry.update_progress(self.job_id, bytes_received)
            from backup_core import BackupState
            self.registry.update_state(self.job_id, BackupState.COMPLETE)
            
            daemon_log(f"BACKUP DATA: Job {self.job_id} complete - {bytes_received} bytes received", "INFO")
            
            # Send success response to sender
            self._transport.send_response({"status": "success"})
            
        except Exception as e:
            daemon_log(f"BACKUP DATA: Unexpected error in job {self.job_id}: {e}", "ERROR")
            self._fail_job(f"Unexpected error: {e}")
            if process:
                process.kill()
        
        finally:
            # Cleanup
            if process:
                try:
                    process.stdin.close()
                except:
                    pass
                try:
                    process.terminate()
                except:
                    pass
            
            self.stop()
    
    def _fail_job(self, error: str) -> None:
        """Mark job as failed with error message, capturing resume token if available."""
        daemon_log(f"BACKUP DATA: Job {self.job_id} failed: {error}", "ERROR")
        try:
            from backup_core import BackupState
            self.registry.update_state(self.job_id, BackupState.FAILED, error=error)
            
            # Send error response to sender so they get the actual error message
            if self._transport:
                self._transport.send_response({"status": "error", "error": error})
            
            # Try to capture resume token for interrupted receives
            self._capture_resume_token()
        except:
            pass
    
    def _capture_resume_token(self) -> None:
        """Try to capture ZFS resume token for a failed receive."""
        try:
            result = subprocess.run(
                [ZFS_CMD_PATH, "get", "-H", "-o", "value", "receive_resume_token", self.dest_dataset],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                token = result.stdout.strip()
                if token and token != "-":
                    daemon_log(f"BACKUP DATA: Captured resume token for job {self.job_id}", "INFO")
                    self.registry.set_resume_token(self.job_id, token)
        except Exception as e:
            daemon_log(f"BACKUP DATA: Could not capture resume token: {e}", "DEBUG")


# Active receivers (for cleanup if needed)
_active_receivers: dict = {}
_receivers_lock = threading.Lock()


def start_receive_backup(
    dest_dataset: str,
    source_dataset: str = "unknown",
    remote_host: str = "unknown",
    remote_port: int = 0,
    use_tls: bool = True,
) -> dict:
    """
    Start a backup receive operation.
    
    Creates a job, starts data channel server, and returns connection info.
    This is the main entry point, symmetric with BackupSender.run().
    
    Args:
        dest_dataset: Target dataset for zfs receive
        source_dataset: Source dataset name (for logging)
        remote_host: Sender's hostname (for logging)
        remote_port: Sender's port (for logging)
        use_tls: Whether to use TLS
        
    Returns:
        Dict with status and data containing job_id, data_port, data_token
    """
    if not dest_dataset:
        return {"status": "error", "error": "Missing dest_dataset parameter"}
    
    try:
        from backup_core import get_backup_registry, BackupState
        
        registry = get_backup_registry()
        
        # Create job in registry
        job = registry.create_job(
            direction="receive",
            source_dataset=source_dataset,
            dest_dataset=dest_dataset,
            remote_host=remote_host,
            remote_port=remote_port,
        )
        
        # Create and start receiver
        receiver = BackupReceiver(job.job_id, dest_dataset, registry, use_tls)
        host, port, token = receiver.start()
        
        # Track active receiver
        with _receivers_lock:
            _active_receivers[job.job_id] = receiver
        
        # Store data channel info in job
        registry.set_data_channel(job.job_id, port, token)
        registry.update_state(job.job_id, BackupState.CONNECTING)
        
        daemon_log(f"BACKUP: Created receive job {job.job_id} on data port {port}", "INFO")
        
        return {
            "status": "success",
            "data": {
                "job_id": job.job_id,
                "data_port": port,
                "data_token": token,
            }
        }
    except Exception as e:
        daemon_log(f"BACKUP: Failed to create receive job: {e}", "ERROR")
        return {"status": "error", "error": f"Failed to create backup job: {e}"}


def create_data_server(
    job_id: str,
    dest_dataset: str,
    registry: "BackupRegistry",
    use_tls: bool = True,
) -> Tuple[str, int, str]:
    """
    Create and start a backup receiver for a job.
    
    DEPRECATED: Use start_receive_backup() instead for new code.
    Kept for backward compatibility.
    """
    receiver = BackupReceiver(job_id, dest_dataset, registry, use_tls)
    host, port, token = receiver.start()
    
    with _receivers_lock:
        _active_receivers[job_id] = receiver
    
    return host, port, token


def stop_data_server(job_id: str) -> bool:
    """Stop a receiver by job ID."""
    with _receivers_lock:
        receiver = _active_receivers.pop(job_id, None)
    
    if receiver:
        receiver.stop()
        return True
    return False

