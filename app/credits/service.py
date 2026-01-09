"""
Credit Service.
Handles credit checking and deduction.
All operations go through the ledger when using SQLite backend.
"""
import logging
from typing import Optional

from app.auth.models import User
from app.auth.repository import get_user_repository

from .exceptions import InsufficientCreditsError

logger = logging.getLogger(__name__)


class CreditService:
    """
    Service for managing user credits.
    Uses ledger for all credit operations when SQLite backend is active.
    """

    RENDER_COST = 1

    def __init__(self):
        self._repo = get_user_repository()
        self._ledger = None
        self._use_ledger = False

        self._init_ledger()
        logger.info(f"CreditService initialized (ledger={self._use_ledger})")

    def _init_ledger(self) -> None:
        """Initialize ledger if using SQLite backend."""
        try:
            from app.persistence import is_sqlite_backend, get_ledger_repository

            if is_sqlite_backend():
                self._ledger = get_ledger_repository()
                self._use_ledger = True
        except ImportError:
            self._use_ledger = False

    def check_credits(self, user: User, required: int = 1) -> bool:
        """
        Check if user has enough credits.
        Returns True if sufficient, False otherwise.
        """
        if user.has_unlimited_credits:
            return True

        return user.credits >= required

    def check_and_deduct(
        self,
        user: User,
        cost: int = 1,
        reason: str = "render",
        related_job_id: Optional[str] = None,
    ) -> bool:
        """
        Check credits and deduct if sufficient.
        Returns True if successful.
        Raises InsufficientCreditsError if not enough credits.
        Records in ledger when using SQLite backend.

        Uses atomic operation to prevent race conditions.
        """
        if user.has_unlimited_credits:
            logger.info(f"User {user.user_id} has unlimited credits, no deduction")
            return True

        if self._use_ledger and self._ledger:
            from app.persistence import CreditReason

            reason_enum = CreditReason(reason) if reason in [r.value for r in CreditReason] else CreditReason.RENDER

            # Use atomic_debit to prevent race conditions
            entry = self._ledger.atomic_debit(
                user_id=user.user_id,
                amount=cost,
                reason=reason_enum,
                related_job_id=related_job_id,
            )

            if entry is None:
                # Atomic debit failed - insufficient credits
                logger.warning(
                    f"Insufficient credits for user {user.user_id}: "
                    f"required={cost}, available={user.credits}"
                )
                raise InsufficientCreditsError(
                    user_id=user.user_id,
                    required=cost,
                    available=user.credits,
                )

            user.credits -= cost
            logger.info(
                f"Deducted {cost} credit(s) from user {user.user_id} via atomic ledger, "
                f"remaining={user.credits}"
            )
        else:
            # Non-ledger path: check then deduct (less safe but fallback)
            if user.credits < cost:
                logger.warning(
                    f"Insufficient credits for user {user.user_id}: "
                    f"required={cost}, available={user.credits}"
                )
                raise InsufficientCreditsError(
                    user_id=user.user_id,
                    required=cost,
                    available=user.credits,
                )

            success = user.deduct_credit(cost)
            if success:
                self._repo.save(user)
                logger.info(
                    f"Deducted {cost} credit(s) from user {user.user_id}, "
                    f"remaining={user.credits}"
                )

        return True

    def deduct_for_render(
        self,
        user: User,
        job_id: Optional[str] = None,
    ) -> bool:
        """
        Deduct credits for a render job.
        Standard cost is 1 credit.
        """
        return self.check_and_deduct(
            user=user,
            cost=self.RENDER_COST,
            reason="render",
            related_job_id=job_id,
        )

    def add_credits(
        self,
        user_id: str,
        amount: int,
        reason: str = "admin",
        related_job_id: Optional[str] = None,
    ) -> Optional[User]:
        """
        Add credits to a user.
        Returns updated user or None if user not found.
        Records in ledger when using SQLite backend.
        """
        user = self._repo.get(user_id)

        if not user:
            user = self._repo.get_or_create(user_id)

        if self._use_ledger and self._ledger:
            from app.persistence import CreditReason

            reason_enum = CreditReason(reason) if reason in [r.value for r in CreditReason] else CreditReason.ADMIN
            self._ledger.record_credit(
                user_id=user_id,
                amount=amount,
                reason=reason_enum,
                related_job_id=related_job_id,
            )
            user = self._repo.get(user_id)
            logger.info(f"Added {amount} credits to user {user_id} via ledger, new balance={user.credits}")
        else:
            user.add_credits(amount)
            self._repo.save(user)
            logger.info(f"Added {amount} credits to user {user_id}, new balance={user.credits}")

        return user

    def rollback_render_credit(
        self,
        user_id: str,
        job_id: Optional[str] = None,
    ) -> Optional[User]:
        """
        Rollback a render credit deduction.
        Used when task submission fails after credit deduction.
        """
        return self.add_credits(
            user_id=user_id,
            amount=self.RENDER_COST,
            reason="rollback",
            related_job_id=job_id,
        )

    def get_balance(self, user_id: str) -> int:
        """Get credit balance for user."""
        user = self._repo.get(user_id)
        if not user:
            return 0

        if user.has_unlimited_credits:
            return -1

        return user.credits

    def get_ledger_history(
        self,
        user_id: str,
        limit: int = 100,
    ) -> list:
        """Get credit history from ledger."""
        if not self._use_ledger or not self._ledger:
            return []

        return self._ledger.get_user_history(user_id, limit=limit)


_service: Optional[CreditService] = None


def get_credit_service() -> CreditService:
    """Get or create credit service singleton."""
    global _service
    if _service is None:
        _service = CreditService()
    return _service


def reset_credit_service() -> None:
    """Reset credit service singleton (for testing)."""
    global _service
    _service = None
