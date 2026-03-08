"""
Backup SSH - Send ZFS snapshot to remote host via SSH.

Provides SSHBackup class that:
- Runs zfs send | ssh "zfs receive" pipe
- Supports multiple auth methods: SSH keys, paramiko, sshpass
- Tracks progress via BackupRegistry

Auth Priority:
1. SSH Key / Auto - Direct ssh command (SSH handles key discovery)
2. Password with paramiko - Pure Python, no external tools
3. Password with sshpass - Fallback when paramiko not available
"""

import subprocess
import sys
import shutil
from typing import Dict, Any, Optional

from debug_logging import daemon_log

try:
    from zfs_manager_core import ZFS_CMD_PATH
except ImportError:
    ZFS_CMD_PATH = "/sbin/zfs"

# Check for optional dependencies
try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

HAS_SSHPASS = shutil.which('sshpass') is not None


class SSHBackup:
    """
    Send ZFS snapshot to remote host via SSH.
    
    Supports three authentication modes:
    - 'auto': Use SSH agent / default keys (~/.ssh/id_*)
    - 'password': Use password auth (paramiko or sshpass)
    - 'key': Use specific SSH key file
    
    Usage:
        # Auto mode - uses SSH keys
        backup = SSHBackup(
            source_snapshot="tank/data@snap1",
            ssh_host="192.168.1.100",
            ssh_user="root",
            dest_dataset="backup/data",
            auth_method="auto"
        )
        
        # Password mode
        backup = SSHBackup(
            source_snapshot="tank/data@snap1",
            ssh_host="192.168.1.100",
            ssh_user="root",
            ssh_password="secret",
            dest_dataset="backup/data",
            auth_method="password"
        )
        
        # Key mode with specific key
        backup = SSHBackup(
            source_snapshot="tank/data@snap1",
            ssh_host="192.168.1.100",
            ssh_user="root",
            dest_dataset="backup/data",
            auth_method="key",
            ssh_key_path="/root/.ssh/backup_key",
            ssh_key_passphrase="keypass"  # Optional
        )
        
        result = backup.run()
    """
    
    CHUNK_SIZE = 65536  # 64KB
    
    def __init__(
        self,
        source_snapshot: str,
        ssh_host: str,
        ssh_user: str,
        dest_dataset: str,
        ssh_port: int = 22,
        auth_method: str = "password",  # 'password' or 'key'
        ssh_password: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        ssh_key_passphrase: Optional[str] = None,
        incremental_base: Optional[str] = None,
        force_rollback: bool = True,
    ):
        """
        Initialize SSH backup.
        
        Args:
            source_snapshot: Source snapshot name (e.g., "tank/data@snap1")
            ssh_host: Remote SSH host
            ssh_user: SSH username
            dest_dataset: Destination dataset on remote host
            ssh_port: SSH port (default 22)
            auth_method: 'auto', 'password', or 'key'
            ssh_password: Password for 'password' auth method
            ssh_key_path: Path to SSH key for 'key' auth method
            ssh_key_passphrase: Passphrase for encrypted SSH key
            incremental_base: Base snapshot for incremental send
            force_rollback: Use -F flag for zfs receive
        """
        self.source_snapshot = source_snapshot
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port
        self.ssh_user = ssh_user
        self.dest_dataset = dest_dataset
        self.auth_method = auth_method
        self.ssh_password = ssh_password
        self.ssh_key_path = ssh_key_path
        self.ssh_key_passphrase = ssh_key_passphrase
        self.incremental_base = incremental_base
        self.force_rollback = force_rollback
        
        self._job_id = None
        self._registry = None
    
    def run(self) -> Dict[str, Any]:
        """
        Execute the SSH backup.
        
        Returns:
            Dict with status and data/error
        """
        try:
            # Validate source exists
            error = self._validate_source()
            if error:
                return error
            
            # Validate auth method is available
            error = self._validate_auth()
            if error:
                return error
            
            # Create job for tracking
            self._create_job()
            
            # Execute based on auth method
            if self.auth_method == 'key':
                result = self._execute_with_ssh_key()
            elif self.auth_method == 'password':
                if HAS_PARAMIKO:
                    result = self._execute_with_paramiko()
                elif HAS_SSHPASS:
                    result = self._execute_with_sshpass()
                else:
                    return {"status": "error", "error": "No SSH password auth available. Install paramiko or sshpass."}
            else:
                return {"status": "error", "error": f"Unknown auth method: {self.auth_method}. Use 'password' or 'key'."}
            
            return result
            
        except Exception as e:
            daemon_log(f"SSH_BACKUP: Failed: {e}", "ERROR")
            if self._job_id and self._registry:
                from backup_core import BackupState
                self._registry.update_state(self._job_id, BackupState.FAILED, error=str(e))
            return {"status": "error", "error": f"SSH backup failed: {e}"}
    
    def _validate_source(self) -> Optional[Dict[str, Any]]:
        """Validate source snapshot exists."""
        from zfs_manager_core import ZfsCommandBuilder
        
        daemon_log(f"SSH_BACKUP: {self.source_snapshot} -> {self.ssh_user}@{self.ssh_host}:{self.dest_dataset} (auth={self.auth_method})", "INFO")
        
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
    
    def _validate_auth(self) -> Optional[Dict[str, Any]]:
        """Validate authentication method is available."""
        if self.auth_method == 'key':
            # Key auth uses the ssh binary directly
            if not shutil.which('ssh'):
                return {"status": "error", "error": "ssh command not found. Install openssh-client."}
            # Validate key file if specified
            if self.ssh_key_path:
                import os
                if not os.path.isfile(self.ssh_key_path):
                    return {"status": "error", "error": f"SSH key not found: {self.ssh_key_path}"}
            return None
        
        elif self.auth_method == 'password':
            if not self.ssh_password:
                return {"status": "error", "error": "SSH password required for password auth"}
            # Paramiko is pure Python - no ssh binary needed
            if HAS_PARAMIKO:
                return None
            # sshpass fallback requires the ssh binary
            if HAS_SSHPASS:
                if not shutil.which('ssh'):
                    return {"status": "error", "error": "ssh command not found. Install openssh-client."}
                return None
            return {"status": "error", "error": "Password auth requires paramiko (pip install paramiko) or sshpass (dnf install sshpass)"}
        
        return {"status": "error", "error": f"Unknown auth method: {self.auth_method}"}
    
    def _create_job(self) -> None:
        """Create job for progress tracking."""
        from backup_core import get_backup_registry
        
        self._registry = get_backup_registry()
        job = self._registry.create_job(
            direction='send',
            source_dataset=self.source_snapshot,
            dest_dataset=self.dest_dataset,
            remote_host=self.ssh_host,
            remote_port=self.ssh_port,
        )
        self._job_id = job.job_id
        daemon_log(f"SSH_BACKUP: Created job {self._job_id}", "INFO")
    
    def _build_send_cmd(self) -> list:
        """Build zfs send command."""
        send_cmd = [ZFS_CMD_PATH, "send"]
        if self.incremental_base:
            send_cmd.extend(["-i", self.incremental_base])
        send_cmd.append(self.source_snapshot)
        return send_cmd
    
    def _build_recv_cmd(self) -> str:
        """Build zfs receive command for remote."""
        recv_cmd = f"{ZFS_CMD_PATH} receive"
        if self.force_rollback:
            recv_cmd += " -F"
        recv_cmd += f" {self.dest_dataset}"
        return recv_cmd
    
    def _execute_with_ssh_key(self) -> Dict[str, Any]:
        """Execute SSH backup using SSH keys (auto or specific key)."""
        from backup_core import BackupState
        
        send_cmd = self._build_send_cmd()
        recv_cmd = self._build_recv_cmd()
        
        # Build ssh command
        ssh_cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "BatchMode=yes",  # Fail instead of prompting for password
            "-p", str(self.ssh_port),
        ]
        
        # Add key file if specified
        if self.ssh_key_path:
            ssh_cmd.extend(["-i", self.ssh_key_path])
        
        ssh_cmd.extend([
            f"{self.ssh_user}@{self.ssh_host}",
            recv_cmd
        ])
        
        self._registry.update_state(self._job_id, BackupState.STREAMING)
        
        # Start send process
        send_proc = subprocess.Popen(
            send_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        
        # Start SSH process with send output as stdin
        ssh_proc = subprocess.Popen(
            ssh_cmd,
            stdin=send_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        
        # Close send stdout in parent to allow SIGPIPE
        send_proc.stdout.close()
        
        # Wait for completion
        ssh_proc.wait()
        send_proc.wait()
        
        # Check results
        send_stderr = send_proc.stderr.read().decode('utf-8', errors='replace')
        ssh_stderr = ssh_proc.stderr.read().decode('utf-8', errors='replace')
        
        if send_proc.returncode != 0:
            error_msg = f"zfs send failed: {send_stderr}"
            self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
            return {"status": "error", "error": error_msg}
        
        if ssh_proc.returncode != 0:
            error_msg = ssh_stderr.strip() or "SSH connection failed. Check SSH keys are set up correctly."
            self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
            return {"status": "error", "error": error_msg}
        
        # Success
        self._registry.update_state(self._job_id, BackupState.COMPLETE)
        daemon_log(f"SSH_BACKUP: Completed {self._job_id} via SSH key", "INFO")
        
        return {
            "status": "success",
            "data": {
                "job_id": self._job_id,
                "message": f"SSH backup complete to {self.ssh_host}"
            }
        }
    
    def _execute_with_paramiko(self) -> Dict[str, Any]:
        """Execute SSH backup using paramiko (password auth)."""
        import paramiko
        from backup_core import BackupState
        
        send_cmd = self._build_send_cmd()
        recv_cmd = self._build_recv_cmd()
        
        self._registry.update_state(self._job_id, BackupState.CONNECTING)
        daemon_log(f"SSH_BACKUP: using paramiko to connect to {self.ssh_host}", "INFO")
        # Connect via paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            client.connect(
                self.ssh_host,
                port=self.ssh_port,
                username=self.ssh_user,
                password=self.ssh_password,
                timeout=30
            )
        except Exception as e:
            error_msg = f"SSH connection failed: {e}"
            self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
            return {"status": "error", "error": error_msg}
        
        self._registry.update_state(self._job_id, BackupState.STREAMING)
        
        # Open channel and execute receive command
        transport = client.get_transport()
        channel = transport.open_session()
        channel.exec_command(recv_cmd)
        
        # Start local zfs send
        send_proc = subprocess.Popen(
            send_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        
        bytes_transferred = 0
        
        try:
            # Stream data through paramiko channel
            while True:
                chunk = send_proc.stdout.read(self.CHUNK_SIZE)
                if not chunk:
                    break
                channel.sendall(chunk)
                bytes_transferred += len(chunk)
                
                if bytes_transferred % (1024 * 1024) < self.CHUNK_SIZE:
                    self._registry.update_progress(self._job_id, bytes_transferred)
            
            # Close channel write side and wait for exit
            channel.shutdown_write()
            exit_status = channel.recv_exit_status()
            
            send_proc.wait()
            send_stderr = send_proc.stderr.read().decode('utf-8', errors='replace')
            
            # Read any stderr from remote
            remote_stderr = ""
            if channel.recv_stderr_ready():
                remote_stderr = channel.recv_stderr(4096).decode('utf-8', errors='replace')
            
            client.close()
            
            if send_proc.returncode != 0:
                error_msg = f"zfs send failed: {send_stderr}"
                self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
                return {"status": "error", "error": error_msg}
            
            if exit_status != 0:
                error_msg = remote_stderr.strip() or f"Remote zfs receive failed (exit code: {exit_status})"
                self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
                return {"status": "error", "error": error_msg}
            
            # Success
            self._registry.update_progress(self._job_id, bytes_transferred)
            self._registry.update_state(self._job_id, BackupState.COMPLETE)
            daemon_log(f"SSH_BACKUP: Completed {self._job_id} via paramiko - {bytes_transferred} bytes", "INFO")
            
            return {
                "status": "success",
                "data": {
                    "job_id": self._job_id,
                    "bytes_transferred": bytes_transferred,
                    "message": f"SSH backup complete: {bytes_transferred} bytes to {self.ssh_host}"
                }
            }
            
        except Exception as e:
            send_proc.kill()
            client.close()
            error_msg = f"SSH stream error: {e}"
            self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
            return {"status": "error", "error": error_msg}
    
    def _execute_with_sshpass(self) -> Dict[str, Any]:
        """Execute SSH backup using sshpass (password fallback)."""
        from backup_core import BackupState
        
        send_cmd = self._build_send_cmd()
        recv_cmd = self._build_recv_cmd()
        daemon_log(f"SSH_BACKUP: using sshpass for {self._job_id}", "INFO")
        # Build SSH command with sshpass
        ssh_cmd = [
            "sshpass", "-p", self.ssh_password,
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-p", str(self.ssh_port),
            f"{self.ssh_user}@{self.ssh_host}",
            recv_cmd
        ]
        
        self._registry.update_state(self._job_id, BackupState.STREAMING)
        
        # Start send process
        send_proc = subprocess.Popen(
            send_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        
        # Start SSH process
        ssh_proc = subprocess.Popen(
            ssh_cmd,
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
                ssh_proc.stdin.write(chunk)
                bytes_transferred += len(chunk)
                
                if bytes_transferred % (1024 * 1024) < self.CHUNK_SIZE:
                    self._registry.update_progress(self._job_id, bytes_transferred)
            
            # Close pipes and wait
            ssh_proc.stdin.close()
            send_proc.wait()
            ssh_proc.wait()
            
            # Check results
            send_stderr = send_proc.stderr.read().decode('utf-8', errors='replace')
            ssh_stderr = ssh_proc.stderr.read().decode('utf-8', errors='replace')
            
            if send_proc.returncode != 0:
                error_msg = f"zfs send failed: {send_stderr}"
                self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
                return {"status": "error", "error": error_msg}
            
            if ssh_proc.returncode != 0:
                error_msg = ssh_stderr.strip() or "SSH connection or receive failed"
                self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
                return {"status": "error", "error": error_msg}
            
            # Success
            self._registry.update_progress(self._job_id, bytes_transferred)
            self._registry.update_state(self._job_id, BackupState.COMPLETE)
            daemon_log(f"SSH_BACKUP: Completed {self._job_id} via sshpass - {bytes_transferred} bytes", "INFO")
            
            return {
                "status": "success",
                "data": {
                    "job_id": self._job_id,
                    "bytes_transferred": bytes_transferred,
                    "message": f"SSH backup complete: {bytes_transferred} bytes to {self.ssh_host}"
                }
            }
            
        except Exception as e:
            send_proc.kill()
            ssh_proc.kill()
            error_msg = f"SSH pipe error: {e}"
            self._registry.update_state(self._job_id, BackupState.FAILED, error=error_msg)
            return {"status": "error", "error": error_msg}


def handle_send_ssh(**kwargs) -> Dict[str, Any]:
    """
    Command handler for send_ssh daemon command.
    """
    backup = SSHBackup(
        source_snapshot=kwargs.get("source_snapshot"),
        ssh_host=kwargs.get("ssh_host"),
        ssh_port=kwargs.get("ssh_port", 22),
        ssh_user=kwargs.get("ssh_user"),
        dest_dataset=kwargs.get("dest_dataset"),
        auth_method=kwargs.get("auth_method", "auto"),
        ssh_password=kwargs.get("ssh_password"),
        ssh_key_path=kwargs.get("ssh_key_path"),
        ssh_key_passphrase=kwargs.get("ssh_key_passphrase"),
        incremental_base=kwargs.get("incremental_base"),
        force_rollback=kwargs.get("force_rollback", True),
    )
    return backup.run()
