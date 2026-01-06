"""
User and Plan models.
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Plan(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


PLAN_CREDITS = {
    Plan.FREE: 3,
    Plan.PRO: 30,
    Plan.ENTERPRISE: -1,
}


def get_plan_credits(plan: Plan) -> int:
    """Get initial credits for plan. -1 means unlimited."""
    return PLAN_CREDITS.get(plan, 3)


class User(BaseModel):
    """User model."""
    user_id: str = Field(..., min_length=1)
    email: Optional[str] = Field(default=None)
    credits: int = Field(default=3)
    plan: Plan = Field(default=Plan.FREE)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def has_unlimited_credits(self) -> bool:
        """Check if user has unlimited credits (enterprise)."""
        return self.plan == Plan.ENTERPRISE

    @property
    def can_render(self) -> bool:
        """Check if user can start a render job."""
        if self.has_unlimited_credits:
            return True
        return self.credits >= 1

    @property
    def credits_display(self) -> str:
        """Human-readable credits display."""
        if self.has_unlimited_credits:
            return "unlimited"
        return str(self.credits)

    def deduct_credit(self, amount: int = 1) -> bool:
        """
        Deduct credits from user.
        Returns True if successful, False if insufficient credits.
        """
        if self.has_unlimited_credits:
            return True

        if self.credits < amount:
            return False

        self.credits -= amount
        self.updated_at = datetime.utcnow()
        return True

    def add_credits(self, amount: int) -> None:
        """Add credits to user."""
        if self.has_unlimited_credits:
            return

        self.credits = max(0, self.credits + amount)
        self.updated_at = datetime.utcnow()

    class Config:
        use_enum_values = False


class UserResponse(BaseModel):
    """User response for API."""
    user_id: str
    email: Optional[str]
    credits: str
    plan: str
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        return cls(
            user_id=user.user_id,
            email=user.email,
            credits=user.credits_display,
            plan=user.plan.value if isinstance(user.plan, Plan) else user.plan,
            created_at=user.created_at,
        )
