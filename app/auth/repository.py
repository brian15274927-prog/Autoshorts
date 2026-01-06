"""
User Repository.
Supports both in-memory and SQLite backends.
"""
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, List, Union
from threading import Lock

from .models import User, Plan, get_plan_credits

logger = logging.getLogger(__name__)


class BaseUserRepository(ABC):
    """Abstract base class for user repositories."""

    @abstractmethod
    def get(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        pass

    @abstractmethod
    def get_or_create(self, user_id: str, email: Optional[str] = None) -> User:
        """Get existing user or create new one."""
        pass

    @abstractmethod
    def save(self, user: User) -> User:
        """Save user."""
        pass

    @abstractmethod
    def delete(self, user_id: str) -> bool:
        """Delete user."""
        pass

    @abstractmethod
    def update_credits(self, user_id: str, delta: int) -> Optional[User]:
        """Update user credits."""
        pass

    @abstractmethod
    def list_all(self) -> List[User]:
        """List all users."""
        pass

    def update(self, user: User) -> User:
        """Update existing user (alias for save)."""
        return self.save(user)

    def exists(self, user_id: str) -> bool:
        """Check if user exists."""
        return self.get(user_id) is not None


class InMemoryUserRepository(BaseUserRepository):
    """
    In-memory user repository.
    Thread-safe, suitable for development/testing.
    """

    def __init__(self):
        self._users: Dict[str, User] = {}
        self._lock = Lock()
        logger.info("UserRepository initialized (in-memory)")

    def get(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        with self._lock:
            return self._users.get(user_id)

    def get_or_create(self, user_id: str, email: Optional[str] = None) -> User:
        """Get existing user or create new one with default credits."""
        with self._lock:
            if user_id in self._users:
                return self._users[user_id]

            user = User(
                user_id=user_id,
                email=email,
                credits=get_plan_credits(Plan.FREE),
                plan=Plan.FREE,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            self._users[user_id] = user

            logger.info(f"Created new user: {user_id}, plan={user.plan.value}, credits={user.credits}")
            return user

    def save(self, user: User) -> User:
        """Save user (create or update)."""
        with self._lock:
            user.updated_at = datetime.utcnow()
            self._users[user.user_id] = user
            return user

    def delete(self, user_id: str) -> bool:
        """Delete user."""
        with self._lock:
            if user_id in self._users:
                del self._users[user_id]
                logger.info(f"Deleted user: {user_id}")
                return True
            return False

    def update_credits(self, user_id: str, delta: int) -> Optional[User]:
        """Update user credits by delta."""
        with self._lock:
            user = self._users.get(user_id)
            if not user:
                return None

            user.add_credits(delta)
            logger.info(f"Updated credits for {user_id}: delta={delta}, new_credits={user.credits}")
            return user

    def list_all(self) -> List[User]:
        """List all users."""
        with self._lock:
            return list(self._users.values())


UserRepository = InMemoryUserRepository

_repository: Optional[BaseUserRepository] = None


def get_user_repository() -> BaseUserRepository:
    """
    Get or create user repository singleton.
    Backend selected via STORAGE_BACKEND environment variable.
    """
    global _repository

    if _repository is None:
        from app.persistence import is_sqlite_backend, SQLiteUserRepository

        if is_sqlite_backend():
            _repository = SQLiteUserRepository()
            logger.info("Using SQLite user repository")
        else:
            _repository = InMemoryUserRepository()
            logger.info("Using in-memory user repository")

    return _repository


def reset_repository() -> None:
    """Reset repository singleton (for testing)."""
    global _repository
    _repository = None
