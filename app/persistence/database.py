"""
SQLite Database Connection and Schema Management.
"""
import os
import sqlite3
import logging
from pathlib import Path
from threading import Lock
from typing import Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_PATH = "data/app.db"

_connection_lock = Lock()
_connection: Optional[sqlite3.Connection] = None


def get_database_path() -> str:
    """Get database path from environment or default."""
    return os.environ.get("DATABASE_PATH", DEFAULT_DATABASE_PATH)


def get_connection() -> sqlite3.Connection:
    """
    Get or create SQLite connection.
    Thread-safe singleton pattern.
    """
    global _connection

    with _connection_lock:
        if _connection is None:
            db_path = get_database_path()

            parent_dir = Path(db_path).parent
            parent_dir.mkdir(parents=True, exist_ok=True)

            _connection = sqlite3.connect(
                db_path,
                check_same_thread=False,
                isolation_level=None,
            )
            _connection.row_factory = sqlite3.Row

            _connection.execute("PRAGMA journal_mode=WAL")
            _connection.execute("PRAGMA foreign_keys=ON")
            _connection.execute("PRAGMA busy_timeout=5000")

            logger.info(f"SQLite connection established: {db_path}")

            init_schema(_connection)

        return _connection


@contextmanager
def transaction():
    """
    Context manager for database transactions.
    Auto-commits on success, rolls back on exception.
    """
    conn = get_connection()

    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def init_schema(conn: sqlite3.Connection) -> None:
    """
    Initialize database schema.
    Creates tables if they don't exist.
    """
    conn.executescript("""
        -- Users table
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            email TEXT,
            plan TEXT NOT NULL DEFAULT 'free',
            credits INTEGER NOT NULL DEFAULT 3,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Job ownership table
        CREATE TABLE IF NOT EXISTS job_ownership (
            task_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        -- Credit ledger table
        CREATE TABLE IF NOT EXISTS credit_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            delta INTEGER NOT NULL,
            reason TEXT NOT NULL,
            related_job_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        -- Idempotency keys table
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            task_id TEXT,
            job_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            response_data TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, key)
        );

        -- Indexes for performance
        CREATE INDEX IF NOT EXISTS idx_job_ownership_user_id
            ON job_ownership(user_id);
        CREATE INDEX IF NOT EXISTS idx_credit_ledger_user_id
            ON credit_ledger(user_id);
        CREATE INDEX IF NOT EXISTS idx_credit_ledger_created_at
            ON credit_ledger(created_at);
        CREATE INDEX IF NOT EXISTS idx_idempotency_keys_user_key
            ON idempotency_keys(user_id, key);
        CREATE INDEX IF NOT EXISTS idx_idempotency_keys_task_id
            ON idempotency_keys(task_id);
    """)

    logger.info("Database schema initialized")


def close_connection() -> None:
    """Close database connection."""
    global _connection

    with _connection_lock:
        if _connection is not None:
            _connection.close()
            _connection = None
            logger.info("SQLite connection closed")


def recalculate_user_credits(conn: sqlite3.Connection, user_id: str) -> int:
    """
    Recalculate user credits from ledger.
    Returns the computed balance.
    """
    cursor = conn.execute(
        "SELECT COALESCE(SUM(delta), 0) as balance FROM credit_ledger WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    balance = row["balance"] if row else 0

    conn.execute(
        "UPDATE users SET credits = ?, updated_at = datetime('now') WHERE user_id = ?",
        (balance, user_id)
    )

    return balance
