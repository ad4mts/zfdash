"""
Backup Sender - Application-layer sender for ZFS backup streams.

Provides BackupSender class that:
- Connects to remote agent control channel
- Requests a data channel
- Streams zfs send output to data channel
- Handles errors and resume tokens
"""

import sys
import socket
import subprocess
import json
from typing import Dict, Any, Optional

from debug_logging import daemon_log
from constants import RESUME_TOKEN_PENDING


class BackupSender:
    """
    Send ZFS dataset/snapshot to a remote agent via data channel.
    
    Usage:
        sender = BackupSender(
            source_dataset="tank/data@snap1",
            dest_host="192.168.1.100",
            dest_port=5555,
            dest_password="secret",
            dest_dataset="backup/data",
        )
        result = sender.run()  # Returns {"status": "success/error", ...}
    """
    
    CHUNK_SIZE = 65536  # 64KB chunks
    
    def __init__(
        self,
        source_dataset: Optional[str],
        dest_host: str,
        dest_port: int,
        dest_password: str,
        dest_dataset: str,
        incremental_base: Optional[str] = None,
        resume_token: Optional[str] = None,
        use_tls: bool = True,
    ):
        """
        Initialize backup sender.
        
        Args:
            source_dataset: Source snapshot or dataset (not needed if resume_token)
            dest_host: Destination agent host
            dest_port: Destination agent port
            dest_password: Password for destination agent
            dest_dataset: Target dataset on destination
            incremental_base: Base snapshot for incremental send
            resume_token: Token to resume interrupted transfer
            use_tls: Whether to request TLS encryption
        """
        self.source_dataset = source_dataset
        self.dest_host = dest_host
        self.dest_port = dest_port
        self.dest_password = dest_password
        self.dest_dataset = dest_dataset
        self.incremental_base = incremental_base
        self.resume_token = resume_token
        self.use_tls = use_tls
        
        # Runtime state
        self._transport = None
        self._tls_active = False
        self._data_channel = None
        self._process = None
        self._send_job_id = None
        self._receiver_job_id = None
        self._registry = None
    
    def run(self) -> Dict[str, Any]:
        """
        Execute the backup.
        
        Returns:
            Dict with status and data/error
        """
        try:
            # Validate parameters
            error = self._validate_params()
            if error:
                return error
            
            # Validate source exists
            error = self._validate_source()
            if error:
                return error
            
            # Connect to control channel (includes TLS negotiation)
            error = self._connect_control_channel()
            if error:
                return error
            
            # Create local job for tracking
            self._create_local_job()
            
            try:
                # Request data channel from receiver
                error = self._request_data_channel()
                if error:
                    return error
                
                # Connect to data channel
                error = self._connect_data_channel()
                if error:
                    return error
                
                # Stream data
                result = self._stream_data()
                return result
                
            finally:
                self._cleanup()
                
        except Exception as e:
            daemon_log(f"BACKUP: send_backup failed: {e}", "ERROR")
            # Ensure job is marked as failed if it was created
            if self._send_job_id and self._registry:
                from backup_core import BackupState
                self._registry.update_state(self._send_job_id, BackupState.FAILED, 
                                             error=str(e))
            return {"status": "error", "error": f"Backup failed: {e}"}
    
    def _validate_params(self) -> Optional[Dict[str, Any]]:
        """Validate required parameters."""
        if not self.resume_token and not self.source_dataset:
            return {"status": "error", "error": "Missing source_dataset parameter"}
        if not self.dest_host:
            return {"status": "error", "error": "Missing dest_host parameter"}
        if not self.dest_port:
            return {"status": "error", "error": "Missing dest_port parameter"}
        if not self.dest_password:
            return {"status": "error", "error": "Missing dest_password parameter"}
        if not self.dest_dataset:
            return {"status": "error", "error": "Missing dest_dataset parameter"}
        return None
    
    def _validate_source(self) -> Optional[Dict[str, Any]]:
        """Validate source dataset/snapshot exists."""
        if self.resume_token:
            return None  # Don't need to validate source for resume
        
        from zfs_manager_core import ZfsCommandBuilder
        
        print(f"BACKUP: Starting send: {self.source_dataset} -> {self.dest_host}:{self.dest_port}/{self.dest_dataset}", file=sys.stderr)
        
        if '@' in self.source_dataset:
            builder = ZfsCommandBuilder('list').type('snapshot').target(self.source_dataset)
        else:
            builder = ZfsCommandBuilder('list').type('filesystem,volume').target(self.source_dataset)
        
        retcode, _, _ = builder.run()
        if retcode != 0:
            kind = "snapshot" if '@' in self.source_dataset else "dataset"
            return {"status": "error", "error": f"Source {kind} '{self.source_dataset}' does not exist"}
        return None
    
    def _connect_control_channel(self) -> Optional[Dict[str, Any]]:
        """Connect to destination agent control port."""
        from ipc_tcp_client import connect_to_agent
        from ipc_security import AuthError, TlsNegotiationError
        
        try:
            self._transport, self._tls_active = connect_to_agent(
                self.dest_host, self.dest_port, self.dest_password,
                timeout=30.0, use_tls=self.use_tls
            )
            print(f"BACKUP: Connected to control port (TLS={self._tls_active})", file=sys.stderr)
            return None
        except AuthError as e:
            return {"status": "error", "error": f"Authentication failed to {self.dest_host}:{self.dest_port}: {e}"}
        except TlsNegotiationError as e:
            return {"status": "error", "error": f"TLS negotiation failed to {self.dest_host}:{self.dest_port}: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Failed to connect to {self.dest_host}:{self.dest_port}: {e}"}
    
    def _create_local_job(self) -> None:
        """Create local job for tracking progress."""
        from backup_core import get_backup_registry
        
        self._registry = get_backup_registry()
        job = self._registry.create_job(
            direction='send',
            source_dataset=self.source_dataset or 'resume',
            dest_dataset=self.dest_dataset,
            remote_host=self.dest_host,
            remote_port=self.dest_port,
        )
        self._send_job_id = job.job_id
        print(f"BACKUP: Created local send job {self._send_job_id}", file=sys.stderr)
    
    def _request_data_channel(self) -> Optional[Dict[str, Any]]:
        """Request data channel from receiver."""
        from backup_core import BackupState
        
        receive_cmd = {
            "command": "start_receive_backup",
            "args": [],
            "kwargs": {
                "dest_dataset": self.dest_dataset,
                "source_dataset": self.source_dataset,
                "remote_host": socket.gethostname(),
                "remote_port": 0,
                "use_tls": self._tls_active,
            },
            "meta": {"request_id": "backup_init"}
        }
        self._transport.send_line(json.dumps(receive_cmd).encode('utf-8'))
        print(f"BACKUP: Sent start_receive_backup command", file=sys.stderr)
        
        response_line = self._transport.receive_line()
        if not response_line:
            return {"status": "error", "error": "Destination closed connection unexpectedly"}
        
        response = json.loads(response_line.decode('utf-8'))
        print(f"BACKUP: Response: {response}", file=sys.stderr)
        
        if response.get("status") != "success":
            error_msg = response.get("error", "Unknown error")
            return {"status": "error", "error": f"Failed to start backup on destination: {error_msg}"}
        
        data = response.get("data", {})
        self._receiver_job_id = data.get("job_id")
        self._data_port = data.get("data_port")
        self._data_token = data.get("data_token")
        
        if not all([self._receiver_job_id, self._data_port, self._data_token]):
            self._registry.update_state(self._send_job_id, BackupState.FAILED, 
                                         error="Missing data channel info")
            return {"status": "error", "error": "Missing data channel info from destination"}
        
        print(f"BACKUP: Receiver job {self._receiver_job_id}, data port {self._data_port}", file=sys.stderr)
        return None
    
    def _connect_data_channel(self) -> Optional[Dict[str, Any]]:
        """Connect to data channel."""
        from backup_data_channel import DataChannelClient
        from backup_core import BackupState
        
        self._registry.update_state(self._send_job_id, BackupState.STREAMING)
        
        self._data_channel = DataChannelClient(
            self.dest_host, self._data_port, self._data_token, 
            use_tls=self._tls_active
        )
        
        try:
            self._data_channel.connect()
            print(f"BACKUP: Data channel connected", file=sys.stderr)
            return None
        except Exception as e:
            self._registry.update_state(self._send_job_id, BackupState.FAILED, 
                                         error=f"Data channel failed: {e}")
            return {"status": "error", "error": f"Data channel connection failed: {e}"}
    
    def _stream_data(self) -> Dict[str, Any]:
        """Stream zfs send output to data channel."""
        from zfs_manager_core import ZFS_CMD_PATH
        from backup_core import BackupState
        
        # Build zfs send command
        send_cmd = [ZFS_CMD_PATH, "send"]
        if self.resume_token:
            send_cmd.extend(["-t", self.resume_token])
            print(f"BACKUP: Using resume token", file=sys.stderr)
        elif self.incremental_base:
            send_cmd.extend(["-i", self.incremental_base])
            send_cmd.append(self.source_dataset)
        else:
            send_cmd.append(self.source_dataset)
        
        self._process = subprocess.Popen(
            send_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        
        bytes_sent = 0
        
        try:
            while True:
                chunk = self._process.stdout.read(self.CHUNK_SIZE)
                if not chunk:
                    break
                self._data_channel.send_chunk(chunk)
                bytes_sent += len(chunk)
                if bytes_sent % (1024 * 1024) < self.CHUNK_SIZE:
                    self._registry.update_progress(self._send_job_id, bytes_sent)
        except Exception as e:
            self._process.kill()
            self._try_fetch_resume_token()
            error_msg = f"Error streaming data: {e}"
            self._registry.update_state(self._send_job_id, BackupState.FAILED, error=error_msg)
            return {"status": "error", "error": error_msg}
        
        # Wait for zfs send
        self._process.wait()
        stderr = self._process.stderr.read().decode('utf-8', errors='replace')
        
        if self._process.returncode != 0:
            self._try_fetch_resume_token()
            error_msg = f"zfs send failed: {stderr}"
            self._registry.update_state(self._send_job_id, BackupState.FAILED, error=error_msg)
            return {"status": "error", "error": error_msg}
        
        # Signal end of stream
        self._data_channel.send_end_of_stream()
        
        # Get final response
        final_result = self._data_channel.receive_response()
        if final_result.get("status") != "success":
            error_msg = f"Destination receive failed: {final_result.get('error', 'Unknown')}"
            self._registry.update_state(self._send_job_id, BackupState.FAILED, error=error_msg)
            return {"status": "error", "error": error_msg}
        
        # Success!
        self._registry.update_progress(self._send_job_id, bytes_sent)
        self._registry.update_state(self._send_job_id, BackupState.COMPLETE)
        print(f"BACKUP: Completed {self._send_job_id} - {bytes_sent} bytes", file=sys.stderr)
        
        return {
            "status": "success",
            "data": {
                "job_id": self._send_job_id,
                "receiver_job_id": self._receiver_job_id,
                "bytes_transferred": bytes_sent,
                "message": f"Backup completed: {bytes_sent} bytes"
            }
        }
    
    def _try_fetch_resume_token(self) -> bool:
        """
        Try to fetch resume token from receiver.
        
        If fetch fails (e.g., network down), stores RESUME_TOKEN_PENDING marker
        so the UI can offer manual fetch after network is restored.
        """
        if not self._transport or not self._registry:
            # No connection at all - store pending marker
            if self._registry and self._send_job_id:
                self._registry.set_resume_token(self._send_job_id, RESUME_TOKEN_PENDING)
                daemon_log(f"BACKUP: Marked job {self._send_job_id} for pending token fetch", "INFO")
            return False
        
        try:
            cmd = {
                "command": "get_resume_token",
                "args": [],
                "kwargs": {"dataset": self.dest_dataset},
                "meta": {"request_id": "get_token"}
            }
            self._transport.send_line(json.dumps(cmd).encode('utf-8'))
            
            response_line = self._transport.receive_line()
            if not response_line:
                # Connection closed - store pending marker
                self._registry.set_resume_token(self._send_job_id, RESUME_TOKEN_PENDING)
                daemon_log(f"BACKUP: Connection lost, marked {self._send_job_id} for pending token fetch", "INFO")
                return False
            
            response = json.loads(response_line.decode('utf-8'))
            if response.get("status") == "success":
                data = response.get("data", {})
                if data.get("has_token") and data.get("token"):
                    self._registry.set_resume_token(self._send_job_id, data["token"])
                    daemon_log(f"BACKUP: Stored resume token for {self._send_job_id}", "INFO")
                    return True
            return False
        except Exception as e:
            daemon_log(f"BACKUP: Could not fetch resume token: {e}", "DEBUG")
            # Network error - store pending marker for later manual fetch
            if self._registry and self._send_job_id:
                self._registry.set_resume_token(self._send_job_id, RESUME_TOKEN_PENDING)
                daemon_log(f"BACKUP: Network error, marked {self._send_job_id} for pending token fetch", "INFO")
            return False
    
    def _cleanup(self) -> None:
        """Cleanup resources."""
        if self._data_channel:
            self._data_channel.close()
        if self._process:
            try:
                self._process.terminate()
            except:
                pass
        if self._transport:
            self._transport.close()
