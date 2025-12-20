"""
Backup Local - Local pool-to-pool replication using zfs send | zfs receive.

Provides LocalBackup class that:
- Runs zfs send piped directly to zfs receive
- Tracks progress via BackupRegistry
- Supports incremental and force rollback options
"""

import subprocess
import sys
from typing import Dict, Any, Optional

from debug_logging import daemon_log

try:
    from zfs_manager_core import ZFS_CMD_PATH
except ImportError:
    ZFS_CMD_PATH = "/sbin/zfs"


class LocalBackup:
    """
    Local pool-to-pool backup using direct pipe.
    
    Usage:
        backup = LocalBackup(
            source_snapshot="tank/data@snap1",
            dest_dataset="backup/data",
            incremental_base="tank/data@snap0",  # Optional
            force_rollback=True
        )
        result = backup.run()
    """
    
    CHUNK_SIZE = 65536  # 64KB for progress tracking
    
    def __init__(
        self,
        source_snapshot: str,
        dest_dataset: str,
        incremental_base: Optional[str] = None,
        force_rollback: bool = True,
    ):
        """
        Initialize local backup.
        
        Args:
            source_snapshot: Source snapshot name (e.g., tank/data@snap1)
            dest_dataset: Destination dataset path (e.g., backup/data)
            incremental_base: Base snapshot for incremental send
            force_rollback: Use -F flag for zfs receive
        """
        self.source_snapshot = source_snapshot
        self.dest_dataset = dest_dataset
        self.incremental_base = incremental_base
        self.force_rollback = force_rollback
        
        self._job_id = None
        self._registry = None
    
    def run(self) -> Dict[str, Any]:
        """
        Execute the local backup.
        
        Returns:
            Dict with status and data/error
        """
        try:
            # Validate source exists
            error = self._validate_source()
            if error:
                return error
            
            # Create job for tracking
            self._create_job()
            
            # Execute pipe
            result = self._execute_pipe()
            return result
            
        except Exception as e:
            daemon_log(f"LOCAL_BACKUP: Failed: {e}", "ERROR")
            if self._job_id and self._registry:
                from backup_core import BackupState
                self._registry.update_state(self._job_id, BackupState.FAILED, error=str(e))
            return {"status": "error", "error": f"Local backup failed: {e}"}
    
    def _validate_source(self) -> Optional[Dict[str, Any]]:
        """Validate source snapshot exists."""
        from zfs_manager_core import ZfsCommandBuilder
        
        print(f"LOCAL_BACKUP: {self.source_snapshot} -> {self.dest_dataset}", file=sys.stderr)
        
        builder = ZfsCommandBuilder('list').type('snapshot').target(self.source_snapshot)
        retcode, _, _ = builder.run()
        
        if retcode != 0:
            return {"status": "error", "error": f"Source snapshot '{self.source_snapshot}' does not exist"}
        
        # Validate incremental base if specified
        if self.incremental_base:
            builder = ZfsCommandBuilder('list').type('snapshot').target(self.incremental_base)
            retcode, _, _ = builder.run()
            if retcode != 0:
                return {"status": "error", "error": f"Incremental base '{self.incremental_base}' does not exist"}
        
        return None
    
    def _create_job(self) -> None:
        """Create job for progress tracking."""
        from backup_core import get_backup_registry
        
        self._registry = get_backup_registry()
        job = self._registry.create_job(
            direction='send',
            source_dataset=self.source_snapshot,
            dest_dataset=self.dest_dataset,
            remote_host='localhost',
            remote_port=0,
        )
        self._job_id = job.job_id
        daemon_log(f"LOCAL_BACKUP: Created job {self._job_id}", "INFO")
    
    def _execute_pipe(self) -> Dict[str, Any]:
        """Execute zfs send | zfs receive pipe."""
        from backup_core import BackupState
        
        # Build send command
        send_cmd = [ZFS_CMD_PATH, "send"]
        if self.incremental_base:
            send_cmd.extend(["-i", self.incremental_base])
        send_cmd.append(self.source_snapshot)
        
        # Build receive command
        recv_cmd = [ZFS_CMD_PATH, "receive"]
        if self.force_rollback:
            recv_cmd.append("-F")
        recv_cmd.append(self.dest_dataset)
        
        self._registry.update_state(self._job_id, BackupState.STREAMING)
        
        # Create pipe
        send_proc = subprocess.Popen(
            send_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        
        recv_proc = subprocess.Popen(
            recv_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        
        bytes_transferred = 0
        
        try:
            # Stream data through
            while True:
                chunk = send_proc.stdout.read(self.CHUNK_SIZE)
                if not chunk:
                    break
                recv_proc.stdin.write(chunk)
                bytes_transferred += len(chunk)
                
                # Update progress every ~1MB
                if bytes_transferred % (1024 * 1024) < self.CHUNK_SIZE:
                    self._registry.update_progress(self._job_id, bytes_transferred)
            
            # Close pipes and wait
            recv_proc.stdin.close()
            send_proc.wait()
            recv_proc.wait()
            
            # Check results
            send_stderr = send_proc.stderr.read().decode('utf-8', errors='replace')
            recv_stderr = recv_proc.stderr.read().decode('utf-8', errors='replace')
            
            if send_proc.returncode != 0:
                error_msg = f"zfs send failed: {send_stderr}"
                self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
                return {"status": "error", "error": error_msg}
            
            if recv_proc.returncode != 0:
                error_msg = f"zfs receive failed: {recv_stderr}"
                self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
                return {"status": "error", "error": error_msg}
            
            # Success
            self._registry.update_progress(self._job_id, bytes_transferred)
            self._registry.update_state(self._job_id, BackupState.COMPLETE)
            daemon_log(f"LOCAL_BACKUP: Completed {self._job_id} - {bytes_transferred} bytes", "INFO")
            
            return {
                "status": "success",
                "data": {
                    "job_id": self._job_id,
                    "bytes_transferred": bytes_transferred,
                    "message": f"Local replication complete: {bytes_transferred} bytes"
                }
            }
            
        except Exception as e:
            send_proc.kill()
            recv_proc.kill()
            error_msg = f"Pipe error: {e}"
            self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
            return {"status": "error", "error": error_msg}


def handle_local_backup(**kwargs) -> Dict[str, Any]:
    """
    Command handler for local_backup daemon command.
    """
    backup = LocalBackup(
        source_snapshot=kwargs.get("source_snapshot"),
        dest_dataset=kwargs.get("dest_dataset"),
        incremental_base=kwargs.get("incremental_base"),
        force_rollback=kwargs.get("force_rollback", True),
    )
    return backup.run()
