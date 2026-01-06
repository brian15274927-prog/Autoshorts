"""
SQLite Job Ownership Repository.
"""
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List

from .database import get_connection

logger = logging.getLogger(__name__)


@dataclass
class JobRecord:
    """Job ownership record."""
    task_id: str
    job_id: str
    user_id: str
    created_at: datetime


class SQLiteJobOwnershipTracker:
    """
    SQLite-backed job ownership tracker.
    Implements same interface as InMemoryJobOwnershipTracker.
    """

    def track_job(self, task_id: str, job_id: str, user_id: str) -> None:
        """Record job ownership."""
        conn = get_connection()
        now = datetime.utcnow().isoformat()

        conn.execute(
            """
            INSERT OR REPLACE INTO job_ownership (task_id, job_id, user_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (task_id, job_id, user_id, now)
        )

        logger.debug(f"Tracked job: task_id={task_id}, job_id={job_id}, user_id={user_id}")

    def is_owner(self, task_id: str, user_id: str) -> bool:
        """Check if user owns the task."""
        conn = get_connection()
        cursor = conn.execute(
            "SELECT user_id FROM job_ownership WHERE task_id = ?",
            (task_id,)
        )
        row = cursor.fetchone()

        if not row:
            return False

        return row["user_id"] == user_id

    def get_owner(self, task_id: str) -> Optional[str]:
        """Get owner of a task."""
        conn = get_connection()
        cursor = conn.execute(
            "SELECT user_id FROM job_ownership WHERE task_id = ?",
            (task_id,)
        )
        row = cursor.fetchone()

        return row["user_id"] if row else None

    def get_job_record(self, task_id: str) -> Optional[JobRecord]:
        """Get full job record."""
        conn = get_connection()
        cursor = conn.execute(
            "SELECT * FROM job_ownership WHERE task_id = ?",
            (task_id,)
        )
        row = cursor.fetchone()

        if not row:
            return None

        return self._row_to_record(row)

    def get_user_jobs(self, user_id: str, limit: int = 100) -> List[JobRecord]:
        """Get all jobs for a user."""
        conn = get_connection()
        cursor = conn.execute(
            """
            SELECT * FROM job_ownership
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit)
        )
        rows = cursor.fetchall()

        return [self._row_to_record(row) for row in rows]

    def delete_job(self, task_id: str) -> bool:
        """Delete job record."""
        conn = get_connection()
        cursor = conn.execute(
            "DELETE FROM job_ownership WHERE task_id = ?",
            (task_id,)
        )
        return cursor.rowcount > 0

    def count_user_jobs(self, user_id: str) -> int:
        """Count jobs for a user."""
        conn = get_connection()
        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM job_ownership WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        return row["cnt"] if row else 0

    def _row_to_record(self, row) -> JobRecord:
        """Convert database row to JobRecord."""
        return JobRecord(
            task_id=row["task_id"],
            job_id=row["job_id"],
            user_id=row["user_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
