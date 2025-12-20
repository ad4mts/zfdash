"""
Backup Commands - Command handlers for backup-related daemon commands.

Provides a BACKUP_COMMAND_MAP for zfs_daemon to dispatch backup commands.
All handlers follow the same pattern: (kwargs) -> response dict.
"""

import sys
import json as json_mod
from typing import Dict, Any, Optional

from debug_logging import daemon_log


def handle_start_receive_backup(kwargs):
    """
    Create a new receive backup job with data channel.
    
    Delegates to backup_receiver.start_receive_backup() which handles:
    - Job creation in registry
    - Data channel server setup
    - Returns connection info for sender
    """
    from backup_receiver import start_receive_backup
    
    return start_receive_backup(
        dest_dataset=kwargs.get("dest_dataset"),
        source_dataset=kwargs.get("source_dataset", "unknown"),
        remote_host=kwargs.get("remote_host", "unknown"),
        remote_port=kwargs.get("remote_port", 0),
        use_tls=kwargs.get("use_tls", True),
    )


def handle_get_backup_status(kwargs):
    """Get status of a specific backup job."""
    job_id = kwargs.get("job_id")
    if not job_id:
        return {"status": "error", "error": "Missing job_id parameter"}
    
    try:
        from backup_core import get_backup_registry
        registry = get_backup_registry()
        job = registry.get_job(job_id)
        
        if job:
            return {"status": "success", "data": job.to_dict()}
        else:
            return {"status": "error", "error": f"Job {job_id} not found"}
    except Exception as e:
        return {"status": "error", "error": f"Error getting job status: {e}"}


def handle_list_backup_jobs(kwargs):
    """List all backup jobs."""
    include_completed = kwargs.get("include_completed", True)
    try:
        from backup_core import get_backup_registry
        registry = get_backup_registry()
        jobs = registry.list_jobs(include_completed=include_completed)
        return {"status": "success", "data": jobs}
    except Exception as e:
        return {"status": "error", "error": f"Error listing jobs: {e}"}


def handle_cancel_backup(kwargs):
    """Cancel a running backup job."""
    job_id = kwargs.get("job_id")
    if not job_id:
        return {"status": "error", "error": "Missing job_id parameter"}
    
    try:
        from backup_core import get_backup_registry
        from backup_receiver import stop_data_server
        
        registry = get_backup_registry()
        cancelled = registry.cancel_job(job_id)
        
        if cancelled:
            stop_data_server(job_id)  # Also stop data server if running
            daemon_log(f"BACKUP: Cancelled job {job_id}", "INFO")
            return {"status": "success", "data": f"Job {job_id} cancelled"}
        else:
            return {"status": "error", "error": f"Job {job_id} not found or already completed"}
    except Exception as e:
        return {"status": "error", "error": f"Error cancelling job: {e}"}


def handle_receive_backup_deprecated(kwargs):
    """Legacy receive_backup - redirect to new system."""
    return {
        "status": "error", 
        "error": "receive_backup is deprecated. Use start_receive_backup instead."
    }



def handle_send_backup(kwargs) -> Dict[str, Any]:
    """
    Send a ZFS dataset/snapshot to a remote agent via dedicated data channel.
    
    Delegates to BackupSender class which handles:
    1. Connect to destination control port
    2. Send start_receive_backup command  
    3. Get data channel port and token
    4. Connect to data channel and stream zfs send output
    
    Returns:
        Dict with status and data containing 'job_id', 'bytes_transferred', 'message'
    """
    from backup_sender import BackupSender
    
    sender = BackupSender(
        source_dataset=kwargs.get("source_dataset"),
        dest_host=kwargs.get("dest_host"),
        dest_port=kwargs.get("dest_port"),
        dest_password=kwargs.get("dest_password"),
        dest_dataset=kwargs.get("dest_dataset"),
        incremental_base=kwargs.get("incremental_base"),
        resume_token=kwargs.get("resume_token"),
        use_tls=kwargs.get("use_tls", True),
    )
    return sender.run()


def handle_delete_backup_job(kwargs) -> Dict[str, Any]:
    """Delete a completed/failed/cancelled backup job from registry and disk."""
    job_id = kwargs.get("job_id")
    if not job_id:
        return {"status": "error", "error": "Missing job_id parameter"}
    
    try:
        from backup_core import get_backup_registry, BackupState
        
        registry = get_backup_registry()
        
        # Check memory first for state validation
        job = registry.get_job(job_id)
        if job:
            # Only allow deleting terminal jobs
            if job.state not in (BackupState.COMPLETE, BackupState.FAILED, BackupState.CANCELLED):
                return {"status": "error", "error": f"Cannot delete job in state {job.state.value}"}
        # If not in memory, it's from disk (another daemon) - allow deletion
        
        # delete_job removes from both memory and disk
        deleted = registry.delete_job(job_id)
        if deleted:
            daemon_log(f"BACKUP: Deleted job {job_id}", "INFO")
            return {"status": "success", "data": f"Job {job_id} deleted"}
        else:
            return {"status": "error", "error": f"Job {job_id} not found"}
    except Exception as e:
        return {"status": "error", "error": f"Error deleting job: {e}"}


def handle_clear_completed_jobs(kwargs) -> Dict[str, Any]:
    """Clear all completed/failed/cancelled backup jobs from registry and disk."""
    try:
        from backup_core import get_backup_registry, BackupState
        from paths import BACKUP_JOBS_FILE_PATH
        import json
        import os
        import fcntl
        
        registry = get_backup_registry()
        terminal_states = {BackupState.COMPLETE, BackupState.FAILED, BackupState.CANCELLED}
        terminal_state_strs = {'complete', 'failed', 'cancelled'}
        
        # Get list of terminal jobs from memory
        jobs_to_delete = []
        with registry._lock:
            for job_id, job in registry._jobs.items():
                if job.state in terminal_states:
                    jobs_to_delete.append(job_id)
        
        # Delete each one from memory
        deleted_count = 0
        for job_id in jobs_to_delete:
            if registry.delete_job(job_id):
                deleted_count += 1
        
        # Also clear completed jobs from disk file (jobs from other daemons)
        if os.path.exists(BACKUP_JOBS_FILE_PATH):
            try:
                with open(BACKUP_JOBS_FILE_PATH, 'r+') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        disk_jobs = json.load(f)
                        # Remove completed jobs
                        ids_to_remove = [
                            jid for jid, job in disk_jobs.items()
                            if job.get('state', 'pending') in terminal_state_strs
                        ]
                        for jid in ids_to_remove:
                            del disk_jobs[jid]
                            if jid not in jobs_to_delete:
                                deleted_count += 1
                        f.seek(0)
                        f.truncate()
                        json.dump(disk_jobs, f, indent=2)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except (json.JSONDecodeError, IOError):
                pass
        
        daemon_log(f"BACKUP: Cleared {deleted_count} completed jobs", "INFO")
        return {"status": "success", "data": {"cleared_count": deleted_count}}
    except Exception as e:
        return {"status": "error", "error": f"Error clearing jobs: {e}"}


def handle_get_resume_token(kwargs) -> Dict[str, Any]:
    """
    Get the ZFS resume token for a dataset with a partial receive.
    
    This can be used to check if a dataset can be resumed.
    """
    dataset = kwargs.get("dataset")
    if not dataset:
        return {"status": "error", "error": "Missing dataset parameter"}
    
    try:
        from zfs_manager_core import ZFS_CMD_PATH
        import subprocess
        
        result = subprocess.run(
            [ZFS_CMD_PATH, "get", "-H", "-o", "value", "receive_resume_token", dataset],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return {"status": "error", "error": f"Failed to get resume token: {result.stderr}"}
        
        token = result.stdout.strip()
        if token == "-":
            return {"status": "success", "data": {"has_token": False, "token": None}}
        
        return {"status": "success", "data": {"has_token": True, "token": token}}
    except Exception as e:
        return {"status": "error", "error": f"Error getting resume token: {e}"}


def handle_resume_backup(kwargs) -> Dict[str, Any]:
    """
    Resume a failed backup job.
    
    Takes a job_id, looks up the stored resume token, and calls send_backup with it.
    """
    job_id = kwargs.get("job_id")
    if not job_id:
        return {"status": "error", "error": "Missing job_id parameter"}
    
    try:
        from backup_core import get_backup_registry, BackupState
        
        registry = get_backup_registry()
        job = registry.get_job(job_id)
        
        if not job:
            return {"status": "error", "error": f"Job {job_id} not found"}
        
        if job.state != BackupState.FAILED:
            return {"status": "error", "error": f"Job {job_id} is not in failed state"}
        
        if not job.resume_token:
            return {"status": "error", "error": f"Job {job_id} has no resume token"}
        
        # Need destination info to resume - stored in the original job
        dest_host = kwargs.get("dest_host") or job.remote_host
        dest_port = kwargs.get("dest_port") or job.remote_port
        dest_password = kwargs.get("dest_password")
        
        if not dest_password:
            return {"status": "error", "error": "Missing dest_password - required for resume"}
        
        daemon_log(f"BACKUP: Resuming job {job_id} with token", "INFO")
        
        # Call send_backup with resume token
        return handle_send_backup({
            "source_dataset": job.source_dataset,  # Will be ignored if token is present
            "dest_host": dest_host,
            "dest_port": dest_port,
            "dest_password": dest_password,
            "dest_dataset": job.dest_dataset,
            "resume_token": job.resume_token,
            "use_tls": kwargs.get("use_tls", True),
        })
    except Exception as e:
        daemon_log(f"BACKUP: Resume failed: {e}", "ERROR")
        return {"status": "error", "error": f"Failed to resume backup: {e}"}


def handle_fetch_resume_token(kwargs) -> Dict[str, Any]:
    """
    Manually fetch resume token from the receiver for a failed job.
    
    Used when automatic token fetch failed (network down during failure).
    Requires the user to provide connection details to the receiver.
    """
    job_id = kwargs.get("job_id")
    dest_host = kwargs.get("dest_host")
    dest_port = kwargs.get("dest_port")
    dest_password = kwargs.get("dest_password")
    
    if not job_id:
        return {"status": "error", "error": "Missing job_id parameter"}
    if not all([dest_host, dest_port, dest_password]):
        return {"status": "error", "error": "Missing dest_host, dest_port, or dest_password"}
    
    try:
        from backup_core import get_backup_registry
        from ipc_tcp_client import connect_to_agent
        from ipc_security import AuthError, TlsNegotiationError
        import json as json_mod
        
        registry = get_backup_registry()
        job = registry.get_job(job_id)  # Now checks both memory and disk
        
        if not job:
            return {"status": "error", "error": f"Job {job_id} not found"}
        
        if not job.needs_token_fetch:
            if job.has_resume_token:
                return {"status": "success", "data": {"message": "Job already has a resume token", "token": job.resume_token}}
            return {"status": "error", "error": "Job does not need token fetch"}
        
        # Connect to receiver
        try:
            transport, _ = connect_to_agent(
                dest_host, int(dest_port), dest_password,
                timeout=30.0, use_tls=True
            )
        except (AuthError, TlsNegotiationError) as e:
            return {"status": "error", "error": f"Authentication failed: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Connection failed: {e}"}
        
        try:
            # Fetch token from receiver's ZFS
            cmd = {
                "command": "get_resume_token",
                "args": [],
                "kwargs": {"dataset": job.dest_dataset},
                "meta": {"request_id": "manual_fetch"}
            }
            transport.send_line(json_mod.dumps(cmd).encode('utf-8'))
            
            response_line = transport.receive_line()
            if not response_line:
                return {"status": "error", "error": "Connection closed unexpectedly"}
            
            response = json_mod.loads(response_line.decode('utf-8'))
            if response.get("status") != "success":
                return {"status": "error", "error": response.get("error", "Unknown error")}
            
            data = response.get("data", {})
            if data.get("has_token") and data.get("token"):
                token = data["token"]
                registry.set_resume_token(job_id, token)  # Handles both memory and disk
                
                daemon_log(f"BACKUP: Manually fetched resume token for {job_id}", "INFO")
                return {
                    "status": "success",
                    "data": {
                        "job_id": job_id,
                        "token": token,
                        "message": "Resume token fetched successfully"
                    }
                }
            else:
                return {"status": "error", "error": "No resume token available on destination"}
        finally:
            transport.close()
            
    except Exception as e:
        daemon_log(f"BACKUP: Manual token fetch failed: {e}", "ERROR")
        return {"status": "error", "error": f"Failed to fetch token: {e}"}


# Command map for backup commands - maps command name to handler function
BACKUP_COMMAND_MAP = {
    "start_receive_backup": handle_start_receive_backup,
    "get_backup_status": handle_get_backup_status,
    "list_backup_jobs": handle_list_backup_jobs,
    "cancel_backup": handle_cancel_backup,
    "delete_backup_job": handle_delete_backup_job,
    "clear_completed_jobs": handle_clear_completed_jobs,
    "get_resume_token": handle_get_resume_token,
    "resume_backup": handle_resume_backup,
    "fetch_resume_token": handle_fetch_resume_token,  # Manual token fetch for UI
    "receive_backup": handle_receive_backup_deprecated,  # Deprecated
    "send_backup": handle_send_backup,
    # New backup types
    "local_backup": lambda kwargs: __import__('backup_local').handle_local_backup(**kwargs),
    "export_to_file": lambda kwargs: __import__('backup_file').handle_export_to_file(**kwargs),
    "send_ssh": lambda kwargs: __import__('backup_ssh').handle_send_ssh(**kwargs),
}
