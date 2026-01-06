"""
Admin endpoints.
Protected by X-Admin-Secret header.
"""
import os
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Header, Depends
from pydantic import BaseModel, Field

from app.auth.repository import get_user_repository
from app.auth.models import User, Plan

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

ADMIN_SECRET_ENV_KEY = "ADMIN_SECRET"
ADMIN_SECRET_DEFAULT = "admin-secret-key-change-in-production"

_admin_secret: Optional[str] = None


def _get_admin_secret() -> str:
    """
    Get admin secret from environment.
    Logs warning if using default value.
    """
    global _admin_secret

    if _admin_secret is not None:
        return _admin_secret

    _admin_secret = os.environ.get(ADMIN_SECRET_ENV_KEY)

    if not _admin_secret:
        logger.warning(
            f"SECURITY WARNING: {ADMIN_SECRET_ENV_KEY} not set in environment. "
            f"Using insecure default value. Set {ADMIN_SECRET_ENV_KEY} in production!"
        )
        _admin_secret = ADMIN_SECRET_DEFAULT

    return _admin_secret


class AddCreditsRequest(BaseModel):
    """Request to add credits."""
    delta: int = Field(..., description="Credits to add (can be negative)")


class AddCreditsResponse(BaseModel):
    """Response after adding credits."""
    user_id: str
    previous_credits: int
    delta: int
    new_credits: int
    message: str


class SetPlanRequest(BaseModel):
    """Request to set user plan."""
    plan: str = Field(..., description="Plan: free, pro, or enterprise")


class UserListResponse(BaseModel):
    """Response for user list."""
    users: list[dict]
    total: int


async def verify_admin_secret(
    x_admin_secret: Optional[str] = Header(None, alias="X-Admin-Secret"),
) -> bool:
    """
    Dependency to verify admin access via X-Admin-Secret header.
    Raises 401 if missing, 403 if invalid.
    """
    if not x_admin_secret:
        logger.warning("Admin request without X-Admin-Secret header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "Admin authentication required",
                "code": "ADMIN_AUTH_REQUIRED",
                "message": "Missing X-Admin-Secret header",
            },
        )

    expected_secret = _get_admin_secret()

    if x_admin_secret != expected_secret:
        logger.warning("Admin request with invalid X-Admin-Secret")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Invalid admin credentials",
                "code": "INVALID_ADMIN_SECRET",
                "message": "The provided X-Admin-Secret is invalid",
            },
        )

    return True


@router.post(
    "/credits/add",
    response_model=AddCreditsResponse,
    summary="Add Credits to User",
    description="Add or subtract credits from a user. Admin only.",
    dependencies=[Depends(verify_admin_secret)],
)
async def add_credits(
    user_id: str,
    request: AddCreditsRequest,
) -> AddCreditsResponse:
    """
    Add credits to a user.
    Requires X-Admin-Secret header.
    """
    repo = get_user_repository()
    user = repo.get(user_id)

    if not user:
        user = repo.get_or_create(user_id)

    previous_credits = user.credits

    if user.has_unlimited_credits:
        return AddCreditsResponse(
            user_id=user_id,
            previous_credits=-1,
            delta=request.delta,
            new_credits=-1,
            message="User has unlimited credits (enterprise plan)",
        )

    user.add_credits(request.delta)
    repo.save(user)

    logger.info(
        f"Admin added {request.delta} credits to user {user_id}: "
        f"{previous_credits} -> {user.credits}"
    )

    return AddCreditsResponse(
        user_id=user_id,
        previous_credits=previous_credits,
        delta=request.delta,
        new_credits=user.credits,
        message=f"Successfully added {request.delta} credits",
    )


@router.post(
    "/users/{user_id}/credits",
    response_model=AddCreditsResponse,
    summary="Modify User Credits",
    description="Add or subtract credits from a user. Admin only.",
    dependencies=[Depends(verify_admin_secret)],
)
async def modify_user_credits(
    user_id: str,
    request: AddCreditsRequest,
) -> AddCreditsResponse:
    """
    Modify user credits.
    Alias endpoint for /admin/credits/add.
    """
    return await add_credits(user_id, request)


@router.get(
    "/users/{user_id}",
    summary="Get User Info",
    description="Get user information. Admin only.",
    dependencies=[Depends(verify_admin_secret)],
)
async def get_user(user_id: str) -> dict:
    """Get user information."""
    repo = get_user_repository()
    user = repo.get(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "User not found", "user_id": user_id},
        )

    return {
        "user_id": user.user_id,
        "email": user.email,
        "credits": user.credits_display,
        "credits_raw": user.credits,
        "plan": user.plan.value if isinstance(user.plan, Plan) else user.plan,
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }


@router.get(
    "/users",
    response_model=UserListResponse,
    summary="List All Users",
    description="List all users. Admin only.",
    dependencies=[Depends(verify_admin_secret)],
)
async def list_users() -> UserListResponse:
    """List all users."""
    repo = get_user_repository()
    users = repo.list_all()

    return UserListResponse(
        users=[
            {
                "user_id": u.user_id,
                "email": u.email,
                "credits": u.credits_display,
                "plan": u.plan.value if isinstance(u.plan, Plan) else u.plan,
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ],
        total=len(users),
    )


@router.post(
    "/users/{user_id}/plan",
    summary="Set User Plan",
    description="Change user plan. Admin only.",
    dependencies=[Depends(verify_admin_secret)],
)
async def set_user_plan(
    user_id: str,
    request: SetPlanRequest,
) -> dict:
    """Set user plan."""
    try:
        plan = Plan(request.plan)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Invalid plan",
                "valid_plans": ["free", "pro", "enterprise"],
            },
        )

    repo = get_user_repository()
    user = repo.get_or_create(user_id)

    old_plan = user.plan
    old_credits = user.credits

    user.plan = plan
    if plan == Plan.ENTERPRISE:
        pass
    elif plan == Plan.PRO:
        user.credits = max(user.credits, 30)
    else:
        user.credits = max(user.credits, 3)

    repo.save(user)

    logger.info(f"Admin changed plan for user {user_id}: {old_plan} -> {plan}")

    return {
        "user_id": user_id,
        "previous_plan": old_plan.value if isinstance(old_plan, Plan) else old_plan,
        "new_plan": plan.value,
        "previous_credits": old_credits,
        "new_credits": user.credits_display,
        "message": f"Plan changed to {plan.value}",
    }
