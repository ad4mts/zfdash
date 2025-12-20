"""
Backup Core - Job Model and Registry

Central module for backup job management:
- BackupState: Job lifecycle states
- BackupJob: Individual job with progress tracking
- BackupRegistry: Thread-safe job storage with automatic cleanup

All components use stdlib only for daemon compatibility.
"""

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Any

from constants import RESUME_TOKEN_PENDING


class BackupState(Enum):
    """Backup job lifecycle states."""
    PENDING = "pending"          # Job created, not yet started
    CONNECTING = "connecting"    # Establishing connection to remote
    STREAMING = "streaming"      # Binary data transfer in progress
    COMPLETE = "complete"        # Successfully finished
    FAILED = "failed"            # Error occurred
    CANCELLED = "cancelled"      # User cancelled


@dataclass
class BackupJob:
    """
    Individual backup job with progress tracking.
    
    Attributes:
        job_id: Unique identifier
        direction: 'send' or 'receive'
        source_dataset: Source snapshot/dataset name
        dest_dataset: Target dataset name
        remote_host: Remote agent host
        remote_port: Remote agent port
        state: Current job state
        bytes_transferred: Bytes sent/received so far
        total_bytes: Estimated total bytes (may be None)
        created_at: Job creation timestamp
        started_at: Stream start timestamp (or None)
        completed_at: Completion timestamp (or None)
        error: Error message if failed
        data_port: Ephemeral data channel port (receiver only)
        data_token: Authentication token for data channel
    """
    job_id: str
    direction: str  # 'send' or 'receive'
    source_dataset: str
    dest_dataset: str
    remote_host: str
    remote_port: int
    state: BackupState = BackupState.PENDING
    bytes_transferred: int = 0
    total_bytes: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    data_port: Optional[int] = None
    data_token: Optional[str] = None
    resume_token: Optional[str] = None  # ZFS resume token for failed receives
    
    @property
    def progress_percent(self) -> Optional[float]:
        """Calculate progress percentage (0-100), or None if total unknown."""
        if self.total_bytes and self.total_bytes > 0:
            return min(100.0, (self.bytes_transferred / self.total_bytes) * 100)
        return None
    
    @property
    def elapsed_seconds(self) -> float:
        """Time elapsed since job started."""
        if self.started_at is None:
            return 0.0
        end_time = self.completed_at or time.time()
        return end_time - self.started_at
    
    @property
    def transfer_rate(self) -> Optional[float]:
        """Bytes per second transfer rate."""
        elapsed = self.elapsed_seconds
        if elapsed > 0 and self.bytes_transferred > 0:
            return self.bytes_transferred / elapsed
        return None
    
    @property
    def eta_seconds(self) -> Optional[float]:
        """Estimated time remaining in seconds."""
        if self.total_bytes is None or self.transfer_rate is None:
            return None
        remaining = self.total_bytes - self.bytes_transferred
        if remaining <= 0:
            return 0.0
        return remaining / self.transfer_rate
    
    @property
    def needs_token_fetch(self) -> bool:
        """True if job failed and needs manual token fetch (network was down during failure)."""
        return self.resume_token == RESUME_TOKEN_PENDING
    
    @property
    def has_resume_token(self) -> bool:
        """True if job has a valid resume token (not pending and not None)."""
        return self.resume_token is not None and self.resume_token != RESUME_TOKEN_PENDING
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize job to dictionary for JSON responses."""
        return {
            "job_id": self.job_id,
            "direction": self.direction,
            "source_dataset": self.source_dataset,
            "dest_dataset": self.dest_dataset,
            "remote_host": self.remote_host,
            "remote_port": self.remote_port,
            "state": self.state.value,
            "bytes_transferred": self.bytes_transferred,
            "total_bytes": self.total_bytes,
            "progress_percent": self.progress_percent,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "transfer_rate": round(self.transfer_rate, 0) if self.transfer_rate else None,
            "eta_seconds": round(self.eta_seconds, 0) if self.eta_seconds else None,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            # Save actual resume_token (including PENDING marker) for disk persistence
            # The UI should use has_resume_token to determine valid tokens for display
            "resume_token": self.resume_token,
            "needs_token_fetch": self.needs_token_fetch,
            "has_resume_token": self.has_resume_token,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackupJob":
        """Deserialize job from dictionary (for loading from disk)."""
        return cls(
            job_id=data["job_id"],
            direction=data["direction"],
            source_dataset=data["source_dataset"],
            dest_dataset=data["dest_dataset"],
            remote_host=data["remote_host"],
            remote_port=data["remote_port"],
            state=BackupState(data.get("state", "pending")),
            bytes_transferred=data.get("bytes_transferred", 0),
            total_bytes=data.get("total_bytes"),
            created_at=data.get("created_at", time.time()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
            data_port=data.get("data_port"),
            data_token=data.get("data_token"),
            resume_token=data.get("resume_token"),
        )


class BackupRegistry:
    """
    Thread-safe registry for backup jobs.
    
    Features:
    - Create, update, and query jobs
    - Automatic cleanup of old completed jobs
    - Cancel support with threading.Event
    """
    
    DEFAULT_TTL_SECONDS = 3600  # Keep completed jobs for 1 hour
    
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._jobs: Dict[str, BackupJob] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._ttl = ttl_seconds
    
    # --- Private disk I/O helpers ---
    
    def _load_job_from_disk(self, job_id: str) -> Optional[BackupJob]:
        """
        Load a single job from disk by ID.
        
        Returns None if job not found or disk read fails.
        """
        import json
        import os
        from paths import BACKUP_JOBS_FILE_PATH
        
        if not os.path.exists(BACKUP_JOBS_FILE_PATH):
            return None
        
        try:
            with open(BACKUP_JOBS_FILE_PATH, 'r') as f:
                disk_jobs = json.load(f)
            if job_id in disk_jobs:
                return BackupJob.from_dict(disk_jobs[job_id])
        except (json.JSONDecodeError, IOError):
            pass
        
        return None
    
    def _update_job_on_disk(self, job_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update specific fields of a job on disk.
        
        Args:
            job_id: Job ID to update
            updates: Dict of field_name -> new_value
        
        Returns True if job was found and updated, False otherwise.
        """
        import json
        import os
        import fcntl
        from paths import BACKUP_JOBS_FILE_PATH
        
        if not os.path.exists(BACKUP_JOBS_FILE_PATH):
            return False
        
        try:
            with open(BACKUP_JOBS_FILE_PATH, 'r+') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    disk_jobs = json.load(f)
                    if job_id not in disk_jobs:
                        return False
                    
                    for key, value in updates.items():
                        disk_jobs[job_id][key] = value
                    
                    f.seek(0)
                    f.truncate()
                    json.dump(disk_jobs, f, indent=2)
                    return True
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except (json.JSONDecodeError, IOError):
            return False
    
    def _delete_job_from_disk(self, job_id: str) -> bool:
        """
        Delete a job from disk storage.
        
        Returns True if job was found and deleted, False otherwise.
        """
        import json
        import os
        import fcntl
        from paths import BACKUP_JOBS_FILE_PATH
        
        if not os.path.exists(BACKUP_JOBS_FILE_PATH):
            return False
        
        try:
            with open(BACKUP_JOBS_FILE_PATH, 'r+') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    disk_jobs = json.load(f)
                    if job_id not in disk_jobs:
                        return False
                    
                    del disk_jobs[job_id]
                    f.seek(0)
                    f.truncate()
                    json.dump(disk_jobs, f, indent=2)
                    return True
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except (json.JSONDecodeError, IOError):
            return False
    
    def create_job(
        self,
        direction: str,
        source_dataset: str,
        dest_dataset: str,
        remote_host: str,
        remote_port: int,
        total_bytes: Optional[int] = None,
    ) -> BackupJob:
        """
        Create a new backup job.
        
        Args:
            direction: 'send' or 'receive'
            source_dataset: Source snapshot/dataset
            dest_dataset: Target dataset
            remote_host: Remote agent host
            remote_port: Remote agent port
            total_bytes: Estimated total (if known)
        
        Returns:
            New BackupJob instance
        """
        job_id = str(uuid.uuid4())[:8]  # Short ID for readability
        
        with self._lock:
            job = BackupJob(
                job_id=job_id,
                direction=direction,
                source_dataset=source_dataset,
                dest_dataset=dest_dataset,
                remote_host=remote_host,
                remote_port=remote_port,
                total_bytes=total_bytes,
            )
            self._jobs[job_id] = job
            self._cancel_events[job_id] = threading.Event()
            
            # Cleanup old jobs while we hold the lock
            self._cleanup_expired_locked()
            
            return job
    
    def get_job(self, job_id: str) -> Optional[BackupJob]:
        """
        Get job by ID, checking memory first then disk.
        
        Jobs may be on disk if created by another daemon instance or
        if they were saved before this daemon started.
        """
        # Check memory first
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                return job
        
        # Check disk if not in memory
        return self._load_job_from_disk(job_id)
    
    def list_jobs(self, include_completed: bool = True) -> Dict[str, Dict[str, Any]]:
        """
        List all jobs as dictionaries.
        
        Merges jobs from disk with in-memory jobs. In-memory jobs
        take precedence (they have real-time progress updates).
        
        Args:
            include_completed: If False, exclude COMPLETE/FAILED/CANCELLED jobs
        
        Returns:
            Dict mapping job_id to job dict
        """
        import json
        import os
        from paths import BACKUP_JOBS_FILE_PATH
        
        terminal_states = {'complete', 'failed', 'cancelled'}
        
        # Read jobs from disk first
        disk_jobs = {}
        if os.path.exists(BACKUP_JOBS_FILE_PATH):
            try:
                with open(BACKUP_JOBS_FILE_PATH, 'r') as f:
                    disk_jobs = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        
        with self._lock:
            # Start with disk jobs
            result = dict(disk_jobs)
            
            # Overlay in-memory jobs (they have real-time progress)
            for job_id, job in self._jobs.items():
                result[job_id] = job.to_dict()
            
            # Filter if needed
            if not include_completed:
                result = {
                    k: v for k, v in result.items() 
                    if v.get('state', 'pending') not in terminal_states
                }
            
            return result
    
    def update_state(self, job_id: str, state: BackupState, error: Optional[str] = None) -> bool:
        """
        Update job state.
        
        Args:
            job_id: Job ID
            state: New state
            error: Error message (for FAILED state)
        
        Returns:
            True if updated, False if job not found
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            
            job.state = state
            
            if state == BackupState.STREAMING and job.started_at is None:
                job.started_at = time.time()
            
            if state in (BackupState.COMPLETE, BackupState.FAILED, BackupState.CANCELLED):
                job.completed_at = time.time()
                # Auto-save to disk on terminal state changes
                self._trigger_save()
            
            if error:
                job.error = error
            
            return True
    
    def _trigger_save(self) -> None:
        """Trigger async save to disk. Called after terminal state changes."""
        try:
            from paths import BACKUP_JOBS_FILE_PATH
            # Note: save_to_disk acquires lock, so we release ours first by scheduling
            # For now, do sync save (fast enough for small job counts)
            # Could make async with threading.Thread if needed
            import threading
            def do_save():
                self.save_to_disk(BACKUP_JOBS_FILE_PATH)
            # Run in background thread to not block
            threading.Thread(target=do_save, daemon=True).start()
        except Exception:
            pass  # Don't fail on save errors
    
    def update_progress(self, job_id: str, bytes_transferred: int, total_bytes: Optional[int] = None) -> bool:
        """
        Update transfer progress.
        
        Args:
            job_id: Job ID
            bytes_transferred: Current bytes transferred
            total_bytes: Updated total estimate (optional)
        
        Returns:
            True if updated, False if job not found
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            
            job.bytes_transferred = bytes_transferred
            if total_bytes is not None:
                job.total_bytes = total_bytes
            
            return True
    
    def set_data_channel(self, job_id: str, port: int, token: str) -> bool:
        """
        Set data channel info for receive jobs.
        
        Args:
            job_id: Job ID
            port: Ephemeral data channel port
            token: Authentication token
        
        Returns:
            True if updated, False if job not found
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            
            job.data_port = port
            job.data_token = token
            return True
    
    def cancel_job(self, job_id: str) -> bool:
        """
        Request cancellation of a job.
        
        The actual cancellation happens asynchronously when the
        streaming code checks the cancel event.
        
        Args:
            job_id: Job ID
        
        Returns:
            True if cancel requested, False if job not found or already terminal
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            
            # Can't cancel already-finished jobs
            if job.state in (BackupState.COMPLETE, BackupState.FAILED, BackupState.CANCELLED):
                return False
            
            # Signal cancellation
            cancel_event = self._cancel_events.get(job_id)
            if cancel_event:
                cancel_event.set()
            
            job.state = BackupState.CANCELLED
            job.completed_at = time.time()
            return True
    
    def is_cancelled(self, job_id: str) -> bool:
        """Check if a job has been cancelled."""
        with self._lock:
            event = self._cancel_events.get(job_id)
            return event.is_set() if event else False
    
    def get_cancel_event(self, job_id: str) -> Optional[threading.Event]:
        """Get cancel event for a job (for streaming code to check)."""
        with self._lock:
            return self._cancel_events.get(job_id)
    
    def delete_job(self, job_id: str) -> bool:
        """
        Explicitly delete a job from registry and disk.
        
        Removes from both in-memory registry and the disk file
        to ensure the job doesn't reappear on reload.
        """
        deleted_from_memory = False
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                self._cancel_events.pop(job_id, None)
                deleted_from_memory = True
        
        # Also delete from disk file
        deleted_from_disk = self._delete_job_from_disk(job_id)
        
        return deleted_from_memory or deleted_from_disk
    
    def set_resume_token(self, job_id: str, token: str) -> bool:
        """
        Set resume token for a failed job.
        
        Checks memory first, then disk if job not in memory.
        """
        # Try memory first
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.resume_token = token
                return True
        
        # Try disk if not in memory
        return self._update_job_on_disk(job_id, {'resume_token': token})
    
    def save_to_disk(self, path: str) -> int:
        """
        Save all jobs to disk for persistence.
        
        Merges with existing file data to support multiple daemons
        writing to the same file. Jobs in memory take precedence
        over jobs on disk for the same job_id.
        
        Uses exclusive lock for entire read-modify-write cycle to prevent
        race conditions between multiple agents.
        
        Args:
            path: File path to save jobs to
            
        Returns:
            Number of jobs saved
        """
        import json
        import os
        import fcntl
        
        with self._lock:
            # Collect our in-memory jobs
            our_jobs = {}
            for job_id, job in self._jobs.items():
                our_jobs[job_id] = job.to_dict()
            
            try:
                # Ensure directory exists
                os.makedirs(os.path.dirname(path), exist_ok=True)
                
                # Open with 'a+' to create if needed, then use exclusive lock
                # for entire read-modify-write cycle to prevent race conditions
                with open(path, 'a+') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        # Read existing content
                        f.seek(0)
                        content = f.read()
                        
                        existing_jobs = {}
                        if content.strip():
                            try:
                                existing_jobs = json.loads(content)
                            except json.JSONDecodeError:
                                existing_jobs = {}
                        
                        # Merge: existing jobs + our jobs (ours take precedence)
                        merged_jobs = {**existing_jobs, **our_jobs}
                        
                        # Truncate and write merged content
                        f.seek(0)
                        f.truncate()
                        json.dump(merged_jobs, f, indent=2)
                        
                        return len(merged_jobs)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                        
            except Exception as e:
                # Log error but don't fail
                import sys
                print(f"BACKUP_CORE: Failed to save jobs to disk: {e}", file=sys.stderr)
                return 0
    
    def load_from_disk(self, path: str) -> int:
        """
        Load jobs from disk.
        
        Only loads jobs that don't already exist in registry.
        Skips jobs in active states (pending, connecting, streaming)
        since those can't be resumed after restart.
        
        Args:
            path: File path to load jobs from
            
        Returns:
            Number of jobs loaded
        """
        import json
        import os
        
        if not os.path.exists(path):
            return 0
        
        try:
            with open(path, 'r') as f:
                jobs_data = json.load(f)
            
            loaded_count = 0
            with self._lock:
                for job_id, data in jobs_data.items():
                    # Skip if already in memory
                    if job_id in self._jobs:
                        continue
                    
                    # Only load terminal state jobs (can't resume active ones)
                    state = data.get('state', 'pending')
                    if state not in ('complete', 'failed', 'cancelled'):
                        continue
                    
                    try:
                        job = BackupJob.from_dict(data)
                        self._jobs[job_id] = job
                        self._cancel_events[job_id] = threading.Event()
                        loaded_count += 1
                    except Exception as e:
                        import sys
                        print(f"BACKUP_CORE: Failed to load job {job_id}: {e}", file=sys.stderr)
            
            return loaded_count
        except Exception as e:
            import sys
            print(f"BACKUP_CORE: Failed to load jobs from disk: {e}", file=sys.stderr)
            return 0
    
    def _cleanup_expired_locked(self) -> None:
        """Remove expired completed jobs. Must be called with lock held."""
        now = time.time()
        expired = []
        
        for job_id, job in self._jobs.items():
            if job.completed_at and (now - job.completed_at) > self._ttl:
                expired.append(job_id)
        
        for job_id in expired:
            del self._jobs[job_id]
            self._cancel_events.pop(job_id, None)


# Global registry instance (used by daemon)
_backup_registry: Optional[BackupRegistry] = None


def get_backup_registry() -> BackupRegistry:
    """Get or create the global backup registry."""
    global _backup_registry
    if _backup_registry is None:
        _backup_registry = BackupRegistry()
        # Load persisted jobs from disk on first access
        try:
            from paths import BACKUP_JOBS_FILE_PATH
            loaded = _backup_registry.load_from_disk(BACKUP_JOBS_FILE_PATH)
            if loaded > 0:
                import sys
                print(f"BACKUP_CORE: Loaded {loaded} jobs from disk", file=sys.stderr)
        except Exception as e:
            import sys
            print(f"BACKUP_CORE: Failed to load jobs: {e}", file=sys.stderr)
    return _backup_registry
