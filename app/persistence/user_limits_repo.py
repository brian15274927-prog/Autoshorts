"""
User Limits Repository.
Manages user quotas, usage tracking, and tier-based limits.
"""
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, Dict, Any
from enum import Enum

from .database import get_connection

logger = logging.getLogger(__name__)


class UserTier(str, Enum):
    """User subscription tiers."""
    FREE = "free"
    PRO = "pro"
    BUSINESS = "business"


@dataclass
class TierLimits:
    """Limits for each tier."""
    videos_per_day: int
    max_duration_seconds: int
    max_segments: int
    watermark: bool
    priority: int  # Higher = faster queue
    dalle_quality: str  # "standard" or "hd"


# Tier configurations
TIER_LIMITS = {
    UserTier.FREE: TierLimits(
        videos_per_day=100,  # Increased for development
        max_duration_seconds=180,  # Increased for development
        max_segments=12,
        watermark=False,
        priority=5,
        dalle_quality="standard"
    ),
    UserTier.PRO: TierLimits(
        videos_per_day=50,
        max_duration_seconds=90,
        max_segments=12,
        watermark=False,
        priority=5,
        dalle_quality="standard"
    ),
    UserTier.BUSINESS: TierLimits(
        videos_per_day=999,  # Effectively unlimited
        max_duration_seconds=180,
        max_segments=24,
        watermark=False,
        priority=10,
        dalle_quality="hd"
    )
}


@dataclass
class UserUsage:
    """User usage statistics."""
    user_id: str
    tier: str
    videos_today: int
    videos_total: int
    last_video_at: Optional[str]
    created_at: str

    # Computed limits
    videos_remaining_today: int
    max_duration: int
    can_generate: bool
    reason: Optional[str] = None


def init_user_limits_schema(conn) -> None:
    """Initialize user_limits table."""
    conn.executescript("""
        -- User limits and usage tracking
        CREATE TABLE IF NOT EXISTS user_limits (
            user_id TEXT PRIMARY KEY,
            tier TEXT NOT NULL DEFAULT 'free',
            videos_today INTEGER NOT NULL DEFAULT 0,
            videos_total INTEGER NOT NULL DEFAULT 0,
            last_video_at TEXT,
            last_reset_date TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Index for tier-based queries
        CREATE INDEX IF NOT EXISTS idx_user_limits_tier
            ON user_limits(tier);
    """)
    logger.info("User limits schema initialized")


class UserLimitsRepository:
    """Repository for user limits and usage tracking."""

    def __init__(self):
        conn = get_connection()
        init_user_limits_schema(conn)

    def get_or_create_user(self, user_id: str, tier: str = "free") -> UserUsage:
        """Get user usage or create new user with default limits."""
        conn = get_connection()

        # Check if user exists
        cursor = conn.execute(
            "SELECT * FROM user_limits WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()

        if not row:
            # Create new user
            now = datetime.utcnow().isoformat()
            today = datetime.utcnow().date().isoformat()
            conn.execute("""
                INSERT INTO user_limits (user_id, tier, videos_today, videos_total, last_reset_date, created_at)
                VALUES (?, ?, 0, 0, ?, ?)
            """, (user_id, tier, today, now))

            return self.get_or_create_user(user_id, tier)

        # Reset daily count if new day
        last_reset = row["last_reset_date"]
        today = datetime.utcnow().date().isoformat()

        if last_reset != today:
            conn.execute("""
                UPDATE user_limits
                SET videos_today = 0, last_reset_date = ?, updated_at = datetime('now')
                WHERE user_id = ?
            """, (today, user_id))
            videos_today = 0
        else:
            videos_today = row["videos_today"]

        # Get tier limits
        user_tier = UserTier(row["tier"])
        limits = TIER_LIMITS[user_tier]

        # Calculate remaining
        videos_remaining = max(0, limits.videos_per_day - videos_today)
        can_generate = videos_remaining > 0
        reason = None if can_generate else f"Daily limit reached ({limits.videos_per_day} videos/day for {user_tier.value} tier)"

        return UserUsage(
            user_id=user_id,
            tier=row["tier"],
            videos_today=videos_today,
            videos_total=row["videos_total"],
            last_video_at=row["last_video_at"],
            created_at=row["created_at"],
            videos_remaining_today=videos_remaining,
            max_duration=limits.max_duration_seconds,
            can_generate=can_generate,
            reason=reason
        )

    def check_can_generate(self, user_id: str, duration: int = 60) -> Dict[str, Any]:
        """
        Check if user can generate a video.

        Returns:
            {
                "allowed": bool,
                "reason": str or None,
                "usage": UserUsage,
                "limits": TierLimits
            }
        """
        usage = self.get_or_create_user(user_id)
        user_tier = UserTier(usage.tier)
        limits = TIER_LIMITS[user_tier]

        # Check daily limit
        if not usage.can_generate:
            return {
                "allowed": False,
                "reason": usage.reason,
                "usage": usage,
                "limits": limits
            }

        # Check duration limit
        if duration > limits.max_duration_seconds:
            return {
                "allowed": False,
                "reason": f"Duration {duration}s exceeds your limit ({limits.max_duration_seconds}s for {user_tier.value} tier)",
                "usage": usage,
                "limits": limits
            }

        return {
            "allowed": True,
            "reason": None,
            "usage": usage,
            "limits": limits
        }

    def record_video_generation(self, user_id: str) -> bool:
        """Record that a user generated a video (increment counters)."""
        conn = get_connection()
        now = datetime.utcnow().isoformat()

        cursor = conn.execute("""
            UPDATE user_limits
            SET videos_today = videos_today + 1,
                videos_total = videos_total + 1,
                last_video_at = ?,
                updated_at = datetime('now')
            WHERE user_id = ?
        """, (now, user_id))

        if cursor.rowcount == 0:
            # User doesn't exist, create them first
            self.get_or_create_user(user_id)
            return self.record_video_generation(user_id)

        logger.info(f"Recorded video generation for user {user_id}")
        return True

    def upgrade_tier(self, user_id: str, new_tier: str) -> bool:
        """Upgrade user to a new tier."""
        conn = get_connection()

        # Validate tier
        try:
            UserTier(new_tier)
        except ValueError:
            logger.error(f"Invalid tier: {new_tier}")
            return False

        cursor = conn.execute("""
            UPDATE user_limits
            SET tier = ?, updated_at = datetime('now')
            WHERE user_id = ?
        """, (new_tier, user_id))

        if cursor.rowcount == 0:
            # Create user with new tier
            self.get_or_create_user(user_id, new_tier)

        logger.info(f"User {user_id} upgraded to {new_tier}")
        return True

    def get_tier_info(self, tier: str = None) -> Dict[str, Any]:
        """Get information about tiers and their limits."""
        if tier:
            try:
                user_tier = UserTier(tier)
                limits = TIER_LIMITS[user_tier]
                return {
                    "tier": tier,
                    "limits": {
                        "videos_per_day": limits.videos_per_day,
                        "max_duration_seconds": limits.max_duration_seconds,
                        "max_segments": limits.max_segments,
                        "watermark": limits.watermark,
                        "priority": limits.priority,
                        "dalle_quality": limits.dalle_quality
                    }
                }
            except ValueError:
                return {"error": f"Unknown tier: {tier}"}

        # Return all tiers
        return {
            tier.value: {
                "videos_per_day": limits.videos_per_day,
                "max_duration_seconds": limits.max_duration_seconds,
                "max_segments": limits.max_segments,
                "watermark": limits.watermark,
                "priority": limits.priority,
                "dalle_quality": limits.dalle_quality
            }
            for tier, limits in TIER_LIMITS.items()
        }


# Global instance
_user_limits_repo: Optional[UserLimitsRepository] = None


def get_user_limits_repository() -> UserLimitsRepository:
    """Get or create the user limits repository singleton."""
    global _user_limits_repo
    if _user_limits_repo is None:
        _user_limits_repo = UserLimitsRepository()
    return _user_limits_repo
