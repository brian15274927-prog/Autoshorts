"""
Job Ownership Tracker.
Maps task_id → user_id for access control.
Supports both in-memory and SQLite backends.
"""
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, List, Union
from threading import Lock
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class JobRecord:
    """Record of a render job."""
    task_id: str
    job_id: str
    user_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    credits_charged: int = 1


class BaseJobOwnershipTracker(ABC):
    """Abstract base class for job ownership trackers."""

    @abstractmethod
    def track_job(
        self,
        task_id: str,
        job_id: str,
        user_id: str,
        credits_charged: int = 1,
    ) -> JobRecord:
        """Track a new job."""
        pass

    @abstractmethod
    def get_job(self, task_id: str) -> Optional[JobRecord]:
        """Get job record by task_id."""
        pass

    @abstractmethod
    def is_owner(self, task_id: str, user_id: str) -> bool:
        """Check if user_id owns task_id."""
        pass

    @abstractmethod
    def get_user_jobs(self, user_id: str) -> List[JobRecord]:
        """Get all jobs for a user."""
        pass

    def get_owner(self, task_id: str) -> Optional[str]:
        """Get owner user_id for task_id."""
        record = self.get_job(task_id)
        return record.user_id if record else None


class InMemoryJobOwnershipTracker(BaseJobOwnershipTracker):
    """
    In-memory job ownership tracker.
    Thread-safe, suitable for development/testing.
    """

    def __init__(self):
        self._jobs: Dict[str, JobRecord] = {}
        self._user_jobs: Dict[str, List[str]] = {}
        self._lock = Lock()
        logger.info("JobOwnershipTracker initialized (in-memory)")

    def track_job(
        self,
        task_id: str,
        job_id: str,
        user_id: str,
        credits_charged: int = 1,
    ) -> JobRecord:
        """Track a new job."""
        with self._lock:
            record = JobRecord(
                task_id=task_id,
                job_id=job_id,
                user_id=user_id,
                credits_charged=credits_charged,
            )

            self._jobs[task_id] = record

            if user_id not in self._user_jobs:
                self._user_jobs[user_id] = []
            self._user_jobs[user_id].append(task_id)

            logger.info(f"Tracked job: task_id={task_id}, job_id={job_id}, user_id={user_id}")
            return record

    def get_job(self, task_id: str) -> Optional[JobRecord]:
        """Get job record by task_id."""
        with self._lock:
            return self._jobs.get(task_id)

    def is_owner(self, task_id: str, user_id: str) -> bool:
        """Check if user_id owns task_id."""
        owner = self.get_owner(task_id)
        return owner == user_id

    def get_user_jobs(self, user_id: str) -> List[JobRecord]:
        """Get all jobs for a user."""
        with self._lock:
            task_ids = self._user_jobs.get(user_id, [])
            return [self._jobs[tid] for tid in task_ids if tid in self._jobs]

    def delete_job(self, task_id: str) -> bool:
        """Delete job record."""
        with self._lock:
            record = self._jobs.pop(task_id, None)
            if record:
                if record.user_id in self._user_jobs:
                    try:
                        self._user_jobs[record.user_id].remove(task_id)
                    except ValueError:
                        pass
                return True
            return False

    def clear(self) -> None:
        """Clear all records (for testing)."""
        with self._lock:
            self._jobs.clear()
            self._user_jobs.clear()


class SQLiteJobOwnershipTrackerAdapter(BaseJobOwnershipTracker):
    """
    Adapter for SQLite job ownership tracker.
    Wraps SQLiteJobOwnershipTracker to match JobRecord interface.
    """

    def __init__(self):
        from app.persistence import SQLiteJobOwnershipTracker
        self._tracker = SQLiteJobOwnershipTracker()
        logger.info("JobOwnershipTracker initialized (SQLite)")

    def track_job(
        self,
        task_id: str,
        job_id: str,
        user_id: str,
        credits_charged: int = 1,
    ) -> JobRecord:
        """Track a new job."""
        self._tracker.track_job(task_id, job_id, user_id)
        return JobRecord(
            task_id=task_id,
            job_id=job_id,
            user_id=user_id,
            credits_charged=credits_charged,
        )

    def get_job(self, task_id: str) -> Optional[JobRecord]:
        """Get job record by task_id."""
        record = self._tracker.get_job_record(task_id)
        if not record:
            return None

        return JobRecord(
            task_id=record.task_id,
            job_id=record.job_id,
            user_id=record.user_id,
            created_at=record.created_at,
        )

    def is_owner(self, task_id: str, user_id: str) -> bool:
        """Check if user_id owns task_id."""
        return self._tracker.is_owner(task_id, user_id)

    def get_user_jobs(self, user_id: str) -> List[JobRecord]:
        """Get all jobs for a user."""
        records = self._tracker.get_user_jobs(user_id)
        return [
            JobRecord(
                task_id=r.task_id,
                job_id=r.job_id,
                user_id=r.user_id,
                created_at=r.created_at,
            )
            for r in records
        ]

    def delete_job(self, task_id: str) -> bool:
        """Delete job record."""
        return self._tracker.delete_job(task_id)


JobOwnershipTracker = InMemoryJobOwnershipTracker

_tracker: Optional[BaseJobOwnershipTracker] = None


def get_job_tracker() -> BaseJobOwnershipTracker:
    """
    Get or create job tracker singleton.
    Backend selected via STORAGE_BACKEND environment variable.
    """
    global _tracker

    if _tracker is None:
        try:
            from app.persistence import is_sqlite_backend

            if is_sqlite_backend():
                _tracker = SQLiteJobOwnershipTrackerAdapter()
            else:
                _tracker = InMemoryJobOwnershipTracker()
        except ImportError:
            _tracker = InMemoryJobOwnershipTracker()

    return _tracker


def reset_job_tracker() -> None:
    """Reset job tracker singleton (for testing)."""
    global _tracker
    _tracker = None
