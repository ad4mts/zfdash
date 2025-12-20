"""
Backup File - Export ZFS snapshot to file with optional compression.

Provides FileExporter class that:
- Exports zfs send output to a file
- Supports compression (gzip, lz4, zstd)
- Tracks progress via BackupRegistry
"""

import subprocess
import sys
import os
from typing import Dict, Any, Optional

from debug_logging import daemon_log

try:
    from zfs_manager_core import ZFS_CMD_PATH
except ImportError:
    ZFS_CMD_PATH = "/sbin/zfs"


class FileExporter:
    """
    Export ZFS snapshot to file with optional compression.
    
    Usage:
        exporter = FileExporter(
            source_snapshot="tank/data@snap1",
            file_path="/backup/data.zfs",
            compression="gzip",  # none, gzip, lz4, zstd
            incremental_base="tank/data@snap0"  # Optional
        )
        result = exporter.run()
    """
    
    CHUNK_SIZE = 65536  # 64KB
    
    # Compression command mappings
    COMPRESSION_CMDS = {
        'none': None,
        'gzip': ['gzip', '-c'],
        'lz4': ['lz4', '-c'],
        'zstd': ['zstd', '-c', '-T0'],  # -T0 uses all cores
    }
    
    COMPRESSION_EXTENSIONS = {
        'none': '',
        'gzip': '.gz',
        'lz4': '.lz4',
        'zstd': '.zst',
    }
    
    def __init__(
        self,
        source_snapshot: str,
        file_path: str,
        compression: str = 'none',
        incremental_base: Optional[str] = None,
    ):
        """
        Initialize file exporter.
        
        Args:
            source_snapshot: Source snapshot name
            file_path: Full path for output file
            compression: Compression type (none, gzip, lz4, zstd)
            incremental_base: Base snapshot for incremental stream
        """
        self.source_snapshot = source_snapshot
        self.file_path = file_path
        self.compression = compression
        self.incremental_base = incremental_base
        
        self._job_id = None
        self._registry = None
    
    def run(self) -> Dict[str, Any]:
        """
        Execute the file export.
        
        Returns:
            Dict with status and data/error
        """
        try:
            # Validate source exists
            error = self._validate_source()
            if error:
                return error
            
            # Validate compression tool is available
            error = self._validate_compression()
            if error:
                return error
            
            # Create job for tracking
            self._create_job()
            
            # Execute export
            result = self._execute_export()
            return result
            
        except Exception as e:
            daemon_log(f"FILE_EXPORT: Failed: {e}", "ERROR")
            if self._job_id and self._registry:
                from backup_core import BackupState
                self._registry.update_state(self._job_id, BackupState.FAILED, error=str(e))
            return {"status": "error", "error": f"File export failed: {e}"}
    
    def _validate_source(self) -> Optional[Dict[str, Any]]:
        """Validate source snapshot exists."""
        from zfs_manager_core import ZfsCommandBuilder
        
        print(f"FILE_EXPORT: {self.source_snapshot} -> {self.file_path}", file=sys.stderr)
        
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
    
    def _validate_compression(self) -> Optional[Dict[str, Any]]:
        """Validate compression tool is available."""
        if self.compression == 'none':
            return None
        
        comp_cmd = self.COMPRESSION_CMDS.get(self.compression)
        if not comp_cmd:
            return {"status": "error", "error": f"Unknown compression: {self.compression}"}
        
        # Check if command exists
        import shutil
        if not shutil.which(comp_cmd[0]):
            return {"status": "error", "error": f"Compression tool not found: {comp_cmd[0]}"}
        
        return None
    
    def _create_job(self) -> None:
        """Create job for progress tracking."""
        from backup_core import get_backup_registry
        
        self._registry = get_backup_registry()
        job = self._registry.create_job(
            direction='send',
            source_dataset=self.source_snapshot,
            dest_dataset=f"file:{self.file_path}",
            remote_host='localhost',
            remote_port=0,
        )
        self._job_id = job.job_id
        daemon_log(f"FILE_EXPORT: Created job {self._job_id}", "INFO")
    
    def _execute_export(self) -> Dict[str, Any]:
        """Execute zfs send with optional compression to file."""
        from backup_core import BackupState
        
        # Build send command
        send_cmd = [ZFS_CMD_PATH, "send"]
        if self.incremental_base:
            send_cmd.extend(["-i", self.incremental_base])
        send_cmd.append(self.source_snapshot)
        
        self._registry.update_state(self._job_id, BackupState.STREAMING)
        
        # Adjust file path for compression extension if needed
        output_path = self.file_path
        ext = self.COMPRESSION_EXTENSIONS.get(self.compression, '')
        if ext and not output_path.endswith(ext):
            output_path += ext
        
        # Create output directory if needed
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        send_proc = subprocess.Popen(
            send_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        
        comp_proc = None
        bytes_written = 0
        
        try:
            # Open output file
            with open(output_path, 'wb') as output_file:
                
                if self.compression == 'none':
                    # Direct write to file
                    while True:
                        chunk = send_proc.stdout.read(self.CHUNK_SIZE)
                        if not chunk:
                            break
                        output_file.write(chunk)
                        bytes_written += len(chunk)
                        
                        if bytes_written % (1024 * 1024) < self.CHUNK_SIZE:
                            self._registry.update_progress(self._job_id, bytes_written)
                else:
                    # Pipe through compression
                    comp_cmd = self.COMPRESSION_CMDS[self.compression]
                    comp_proc = subprocess.Popen(
                        comp_cmd,
                        stdin=subprocess.PIPE,
                        stdout=output_file,
                        stderr=subprocess.PIPE,
                        bufsize=0
                    )
                    
                    while True:
                        chunk = send_proc.stdout.read(self.CHUNK_SIZE)
                        if not chunk:
                            break
                        comp_proc.stdin.write(chunk)
                        bytes_written += len(chunk)
                        
                        if bytes_written % (1024 * 1024) < self.CHUNK_SIZE:
                            self._registry.update_progress(self._job_id, bytes_written)
                    
                    comp_proc.stdin.close()
                    comp_proc.wait()
            
            # Wait for send process
            send_proc.wait()
            
            # Check results
            send_stderr = send_proc.stderr.read().decode('utf-8', errors='replace')
            
            if send_proc.returncode != 0:
                error_msg = f"zfs send failed: {send_stderr}"
                self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
                return {"status": "error", "error": error_msg}
            
            if comp_proc and comp_proc.returncode != 0:
                comp_stderr = comp_proc.stderr.read().decode('utf-8', errors='replace')
                error_msg = f"Compression failed: {comp_stderr}"
                self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
                return {"status": "error", "error": error_msg}
            
            # Get actual file size
            file_size = os.path.getsize(output_path)
            
            # Success
            self._registry.update_progress(self._job_id, bytes_written)
            self._registry.update_state(self._job_id, BackupState.COMPLETE)
            daemon_log(f"FILE_EXPORT: Completed {self._job_id} - {bytes_written} bytes sent, {file_size} bytes written", "INFO")
            
            return {
                "status": "success",
                "data": {
                    "job_id": self._job_id,
                    "bytes_sent": bytes_written,
                    "bytes_written": file_size,
                    "file_path": output_path,
                    "message": f"Export complete: {file_size} bytes written to {output_path}"
                }
            }
            
        except Exception as e:
            send_proc.kill()
            if comp_proc:
                comp_proc.kill()
            error_msg = f"Export error: {e}"
            self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
            return {"status": "error", "error": error_msg}


def handle_export_to_file(**kwargs) -> Dict[str, Any]:
    """
    Command handler for export_to_file daemon command.
    """
    exporter = FileExporter(
        source_snapshot=kwargs.get("source_snapshot"),
        file_path=kwargs.get("file_path"),
        compression=kwargs.get("compression", "none"),
        incremental_base=kwargs.get("incremental_base"),
    )
    return exporter.run()
