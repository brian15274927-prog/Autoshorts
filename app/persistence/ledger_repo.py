"""
Credit Ledger Repository.
All credit operations go through the ledger.
"""
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum

from .database import get_connection, transaction, recalculate_user_credits

logger = logging.getLogger(__name__)


class CreditReason(str, Enum):
    """Reasons for credit changes."""
    INITIAL = "initial"
    RENDER = "render"
    ROLLBACK = "rollback"
    ADMIN = "admin"
    REFUND = "refund"
    PURCHASE = "purchase"
    PLAN_UPGRADE = "plan_upgrade"


@dataclass
class LedgerEntry:
    """Credit ledger entry."""
    id: int
    user_id: str
    delta: int
    reason: str
    related_job_id: Optional[str]
    created_at: datetime


class CreditLedgerRepository:
    """
    Credit ledger repository.
    All credit operations MUST go through this repository.
    """

    def record_debit(
        self,
        user_id: str,
        amount: int,
        reason: CreditReason,
        related_job_id: Optional[str] = None,
    ) -> LedgerEntry:
        """
        Record a debit (credit deduction).
        Amount should be positive, will be stored as negative delta.
        Returns the ledger entry.
        """
        if amount <= 0:
            raise ValueError("Debit amount must be positive")

        return self._record_entry(
            user_id=user_id,
            delta=-amount,
            reason=reason,
            related_job_id=related_job_id,
        )

    def record_credit(
        self,
        user_id: str,
        amount: int,
        reason: CreditReason,
        related_job_id: Optional[str] = None,
    ) -> LedgerEntry:
        """
        Record a credit (credit addition).
        Amount should be positive.
        Returns the ledger entry.
        """
        if amount <= 0:
            raise ValueError("Credit amount must be positive")

        return self._record_entry(
            user_id=user_id,
            delta=amount,
            reason=reason,
            related_job_id=related_job_id,
        )

    def _record_entry(
        self,
        user_id: str,
        delta: int,
        reason: CreditReason,
        related_job_id: Optional[str] = None,
    ) -> LedgerEntry:
        """
        Record a ledger entry and update user's cached credits.
        Uses transaction for atomicity.
        """
        conn = get_connection()
        now = datetime.utcnow().isoformat()

        with transaction():
            cursor = conn.execute(
                """
                INSERT INTO credit_ledger (user_id, delta, reason, related_job_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, delta, reason.value, related_job_id, now)
            )
            entry_id = cursor.lastrowid

            conn.execute(
                """
                UPDATE users
                SET credits = credits + ?, updated_at = ?
                WHERE user_id = ?
                """,
                (delta, now, user_id)
            )

        logger.info(
            f"Ledger entry: user={user_id}, delta={delta}, "
            f"reason={reason.value}, job={related_job_id}"
        )

        return LedgerEntry(
            id=entry_id,
            user_id=user_id,
            delta=delta,
            reason=reason.value,
            related_job_id=related_job_id,
            created_at=datetime.fromisoformat(now),
        )

    def get_balance(self, user_id: str) -> int:
        """
        Get current balance from ledger (computed).
        """
        conn = get_connection()
        cursor = conn.execute(
            "SELECT COALESCE(SUM(delta), 0) as balance FROM credit_ledger WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        return row["balance"] if row else 0

    def get_cached_balance(self, user_id: str) -> int:
        """
        Get cached balance from users table.
        Faster but may be stale.
        """
        conn = get_connection()
        cursor = conn.execute(
            "SELECT credits FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        return row["credits"] if row else 0

    def sync_balance(self, user_id: str) -> int:
        """
        Recalculate and sync balance from ledger to users table.
        Returns the synced balance.
        """
        conn = get_connection()
        with transaction():
            return recalculate_user_credits(conn, user_id)

    def get_user_history(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[LedgerEntry]:
        """Get credit history for user."""
        conn = get_connection()
        cursor = conn.execute(
            """
            SELECT * FROM credit_ledger
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, limit, offset)
        )
        rows = cursor.fetchall()

        return [self._row_to_entry(row) for row in rows]

    def get_job_entries(self, job_id: str) -> List[LedgerEntry]:
        """Get all ledger entries for a job."""
        conn = get_connection()
        cursor = conn.execute(
            """
            SELECT * FROM credit_ledger
            WHERE related_job_id = ?
            ORDER BY created_at ASC
            """,
            (job_id,)
        )
        rows = cursor.fetchall()

        return [self._row_to_entry(row) for row in rows]

    def _row_to_entry(self, row) -> LedgerEntry:
        """Convert database row to LedgerEntry."""
        return LedgerEntry(
            id=row["id"],
            user_id=row["user_id"],
            delta=row["delta"],
            reason=row["reason"],
            related_job_id=row["related_job_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


_ledger_repo: Optional[CreditLedgerRepository] = None


def get_ledger_repository() -> CreditLedgerRepository:
    """Get or create ledger repository singleton."""
    global _ledger_repo
    if _ledger_repo is None:
        _ledger_repo = CreditLedgerRepository()
    return _ledger_repo
