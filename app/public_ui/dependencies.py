"""
Public UI Dependencies.
User identification from request state, cookie, or header.
"""
import uuid
from fastapi import Request, Response
from typing import Optional

USER_COOKIE_NAME = "videogen_user_id"
USER_HEADER_NAME = "X-User-Id"
GUEST_USER_PREFIX = "guest_"


def get_user_id(request: Request) -> Optional[str]:
    """
    Get user_id from request state (set by middleware), cookie, or header.
    """
    # 1. Try request.state (set by AuthMiddleware)
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return user_id

    # 2. Try cookie
    user_id = request.cookies.get(USER_COOKIE_NAME)
    if user_id:
        return user_id

    # 3. Try header
    user_id = request.headers.get(USER_HEADER_NAME)
    if user_id:
        return user_id

    return None


def get_or_create_user_id(request: Request) -> str:
    """
    Get existing user_id or create a new guest user.
    Always returns a valid user_id.
    """
    user_id = get_user_id(request)
    if user_id:
        return user_id

    # Create guest user
    return f"{GUEST_USER_PREFIX}{uuid.uuid4().hex[:12]}"


def set_user_cookie(response: Response, user_id: str) -> None:
    """Set user_id cookie."""
    response.set_cookie(
        key=USER_COOKIE_NAME,
        value=user_id,
        httponly=True,
        max_age=60 * 60 * 24 * 365,  # 1 year
        samesite="lax",
    )


def generate_idempotency_key() -> str:
    """Generate a unique idempotency key."""
    return f"idem_{uuid.uuid4().hex}"
