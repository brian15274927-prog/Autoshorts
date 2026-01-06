"""
Idempotency Key Repository.
Prevents duplicate requests and double credit deduction.
"""
import json
import hashlib
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
from enum import Enum

from .database import get_connection, transaction

logger = logging.getLogger(__name__)


class IdempotencyStatus(str, Enum):
    """Idempotency request status."""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IdempotencyRecord:
    """Idempotency key record."""
    id: int
    user_id: str
    key: str
    request_hash: str
    task_id: Optional[str]
    job_id: Optional[str]
    status: IdempotencyStatus
    response_data: Optional[dict]
    created_at: datetime
    updated_at: datetime


class IdempotencyRepository:
    """
    Idempotency repository.
    Ensures requests with same Idempotency-Key return same result.
    """

    def find_by_key(self, user_id: str, key: str) -> Optional[IdempotencyRecord]:
        """
        Find existing idempotency record.
        Returns None if not found.
        """
        conn = get_connection()
        cursor = conn.execute(
            """
            SELECT * FROM idempotency_keys
            WHERE user_id = ? AND key = ?
            """,
            (user_id, key)
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_record(row)

    def create_pending(
        self,
        user_id: str,
        key: str,
        request_hash: str,
    ) -> IdempotencyRecord:
        """
        Create a new pending idempotency record.
        Uses transaction for atomicity.
        Raises IntegrityError if key already exists.
        """
        conn = get_connection()
        now = datetime.utcnow().isoformat()

        with transaction():
            cursor = conn.execute(
                """
                INSERT INTO idempotency_keys
                (user_id, key, request_hash, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, key, request_hash, IdempotencyStatus.PENDING.value, now, now)
            )
            record_id = cursor.lastrowid

        logger.info(f"Idempotency record created: user={user_id}, key={key}")

        return IdempotencyRecord(
            id=record_id,
            user_id=user_id,
            key=key,
            request_hash=request_hash,
            task_id=None,
            job_id=None,
            status=IdempotencyStatus.PENDING,
            response_data=None,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    def update_completed(
        self,
        user_id: str,
        key: str,
        task_id: str,
        job_id: str,
        response_data: Optional[dict] = None,
    ) -> None:
        """
        Mark idempotency record as completed.
        Stores the response for future replays.
        """
        conn = get_connection()
        now = datetime.utcnow().isoformat()
        response_json = json.dumps(response_data) if response_data else None

        with transaction():
            conn.execute(
                """
                UPDATE idempotency_keys
                SET task_id = ?, job_id = ?, status = ?, response_data = ?, updated_at = ?
                WHERE user_id = ? AND key = ?
                """,
                (
                    task_id,
                    job_id,
                    IdempotencyStatus.COMPLETED.value,
                    response_json,
                    now,
                    user_id,
                    key,
                )
            )

        logger.info(
            f"Idempotency completed: user={user_id}, key={key}, "
            f"task_id={task_id}, job_id={job_id}"
        )

    def update_failed(self, user_id: str, key: str, error: Optional[str] = None) -> None:
        """
        Mark idempotency record as failed.
        Allows retry with same key.
        """
        conn = get_connection()
        now = datetime.utcnow().isoformat()
        response_json = json.dumps({"error": error}) if error else None

        with transaction():
            conn.execute(
                """
                UPDATE idempotency_keys
                SET status = ?, response_data = ?, updated_at = ?
                WHERE user_id = ? AND key = ?
                """,
                (
                    IdempotencyStatus.FAILED.value,
                    response_json,
                    now,
                    user_id,
                    key,
                )
            )

        logger.info(f"Idempotency failed: user={user_id}, key={key}")

    def delete_failed(self, user_id: str, key: str) -> bool:
        """
        Delete a failed idempotency record to allow retry.
        Returns True if deleted, False if not found or not failed.
        """
        conn = get_connection()

        with transaction():
            cursor = conn.execute(
                """
                DELETE FROM idempotency_keys
                WHERE user_id = ? AND key = ? AND status = ?
                """,
                (user_id, key, IdempotencyStatus.FAILED.value)
            )
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info(f"Idempotency record deleted: user={user_id}, key={key}")

        return deleted

    def find_by_task_id(self, task_id: str) -> Optional[IdempotencyRecord]:
        """Find idempotency record by task_id."""
        conn = get_connection()
        cursor = conn.execute(
            """
            SELECT * FROM idempotency_keys
            WHERE task_id = ?
            """,
            (task_id,)
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_record(row)

    def _row_to_record(self, row) -> IdempotencyRecord:
        """Convert database row to IdempotencyRecord."""
        response_data = None
        if row["response_data"]:
            try:
                response_data = json.loads(row["response_data"])
            except json.JSONDecodeError:
                pass

        return IdempotencyRecord(
            id=row["id"],
            user_id=row["user_id"],
            key=row["key"],
            request_hash=row["request_hash"],
            task_id=row["task_id"],
            job_id=row["job_id"],
            status=IdempotencyStatus(row["status"]),
            response_data=response_data,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def compute_request_hash(request_data: dict) -> str:
        """
        Compute hash of request data for conflict detection.
        Same key + different payload = conflict.
        """
        serialized = json.dumps(request_data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()[:32]


_idempotency_repo: Optional[IdempotencyRepository] = None


def get_idempotency_repository() -> IdempotencyRepository:
    """Get or create idempotency repository singleton."""
    global _idempotency_repo
    if _idempotency_repo is None:
        _idempotency_repo = IdempotencyRepository()
    return _idempotency_repo
