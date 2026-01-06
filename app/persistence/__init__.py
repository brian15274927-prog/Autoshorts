"""
Persistence Module.
Provides SQLite-backed storage for users, jobs, and credit ledger.
"""
import os
import logging

from .database import get_connection, transaction, close_connection, init_schema
from .users_repo import SQLiteUserRepository
from .jobs_repo import SQLiteJobOwnershipTracker, JobRecord
from .ledger_repo import (
    CreditLedgerRepository,
    CreditReason,
    LedgerEntry,
    get_ledger_repository,
)
from .idempotency_repo import (
    IdempotencyRepository,
    IdempotencyStatus,
    IdempotencyRecord,
    get_idempotency_repository,
)
from .clips_repo import (
    SQLiteClipsRepository,
    ClipRecord,
    Subtitle,
    get_clips_repository,
)

logger = logging.getLogger(__name__)

STORAGE_BACKEND_ENV = "STORAGE_BACKEND"
STORAGE_BACKEND_SQLITE = "sqlite"
STORAGE_BACKEND_MEMORY = "memory"


def get_storage_backend() -> str:
    """Get storage backend from environment."""
    backend = os.environ.get(STORAGE_BACKEND_ENV, STORAGE_BACKEND_SQLITE)
    return backend.lower()


def is_sqlite_backend() -> bool:
    """Check if using SQLite backend."""
    return get_storage_backend() == STORAGE_BACKEND_SQLITE


__all__ = [
    "get_connection",
    "transaction",
    "close_connection",
    "init_schema",
    "SQLiteUserRepository",
    "SQLiteJobOwnershipTracker",
    "JobRecord",
    "CreditLedgerRepository",
    "CreditReason",
    "LedgerEntry",
    "get_ledger_repository",
    "IdempotencyRepository",
    "IdempotencyStatus",
    "IdempotencyRecord",
    "get_idempotency_repository",
    "SQLiteClipsRepository",
    "ClipRecord",
    "Subtitle",
    "get_clips_repository",
    "get_storage_backend",
    "is_sqlite_backend",
    "STORAGE_BACKEND_SQLITE",
    "STORAGE_BACKEND_MEMORY",
]
