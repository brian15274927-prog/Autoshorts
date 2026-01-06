"""
Authentication dependencies for FastAPI.
"""
import logging
from typing import Optional

from fastapi import Request, HTTPException, status

from .models import User
from .repository import get_user_repository

logger = logging.getLogger(__name__)


async def get_current_user_id(request: Request) -> Optional[str]:
    """Get current user_id from request state."""
    return getattr(request.state, "user_id", None)


async def get_current_user(request: Request) -> User:
    """
    Get current user from request.
    Creates user if doesn't exist (auto-registration).
    Raises 401 if no user_id in request.
    """
    user_id = getattr(request.state, "user_id", None)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "Authentication required",
                "code": "AUTH_REQUIRED",
                "message": "Missing X-User-Id header",
            },
        )

    repo = get_user_repository()
    user = repo.get_or_create(user_id)
    return user


async def require_auth(request: Request) -> User:
    """
    Dependency that requires authenticated user.
    Alias for get_current_user.
    """
    return await get_current_user(request)


async def get_current_user_optional(request: Request) -> Optional[User]:
    """
    Get current user from request if authenticated.
    Returns None if no user_id in request (no error raised).
    Creates user if doesn't exist (auto-registration).
    """
    user_id = getattr(request.state, "user_id", None)

    if not user_id:
        return None

    repo = get_user_repository()
    user = repo.get_or_create(user_id)
    return user
