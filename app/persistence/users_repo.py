"""
SQLite User Repository.
"""
import logging
from datetime import datetime
from typing import Optional, List

from app.auth.models import User, Plan, PLAN_CREDITS
from .database import get_connection, transaction

logger = logging.getLogger(__name__)


class SQLiteUserRepository:
    """
    SQLite-backed user repository.
    Implements same interface as InMemoryUserRepository.
    """

    def get(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        conn = get_connection()
        cursor = conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()

        if not row:
            return None

        return self._row_to_user(row)

    def get_or_create(self, user_id: str, email: Optional[str] = None) -> User:
        """Get existing user or create new one."""
        user = self.get(user_id)

        if user:
            return user

        return self._create_user(user_id, email)

    def _create_user(self, user_id: str, email: Optional[str] = None) -> User:
        """Create new user with initial credits from ledger."""
        conn = get_connection()
        now = datetime.utcnow().isoformat()
        initial_credits = PLAN_CREDITS[Plan.FREE]

        with transaction():
            conn.execute(
                """
                INSERT INTO users (user_id, email, plan, credits, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, email, Plan.FREE.value, initial_credits, now, now)
            )

            conn.execute(
                """
                INSERT INTO credit_ledger (user_id, delta, reason, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, initial_credits, "initial", now)
            )

        logger.info(f"Created new user: {user_id} with {initial_credits} credits")

        return User(
            user_id=user_id,
            email=email,
            plan=Plan.FREE,
            credits=initial_credits,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    def save(self, user: User) -> None:
        """Save user (update only, credits managed via ledger)."""
        conn = get_connection()
        now = datetime.utcnow().isoformat()

        conn.execute(
            """
            UPDATE users
            SET email = ?, plan = ?, credits = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (user.email, user.plan.value, user.credits, now, user.user_id)
        )

        user.updated_at = datetime.fromisoformat(now)

    def update_credits(self, user_id: str, delta: int) -> Optional[User]:
        """
        Update user credits.
        DEPRECATED: Use CreditLedgerRepository instead.
        """
        user = self.get(user_id)
        if not user:
            return None

        user.add_credits(delta)
        self.save(user)
        return user

    def list_all(self) -> List[User]:
        """List all users."""
        conn = get_connection()
        cursor = conn.execute("SELECT * FROM users ORDER BY created_at DESC")
        rows = cursor.fetchall()

        return [self._row_to_user(row) for row in rows]

    def delete(self, user_id: str) -> bool:
        """Delete user."""
        conn = get_connection()
        cursor = conn.execute(
            "DELETE FROM users WHERE user_id = ?",
            (user_id,)
        )
        return cursor.rowcount > 0

    def _row_to_user(self, row) -> User:
        """Convert database row to User model."""
        return User(
            user_id=row["user_id"],
            email=row["email"],
            plan=Plan(row["plan"]),
            credits=row["credits"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
