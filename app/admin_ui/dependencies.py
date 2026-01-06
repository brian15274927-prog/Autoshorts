"""
Admin UI Authentication Dependencies.
"""
import os
import hashlib
import hmac
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse

ADMIN_SECRET_ENV = "ADMIN_SECRET"
ADMIN_COOKIE_NAME = "admin_session"
COOKIE_SECRET = "admin-ui-secret-key-change-in-prod"


def get_admin_secret() -> str:
    """Get admin secret from environment."""
    return os.environ.get(ADMIN_SECRET_ENV, "admin-secret-default")


def create_session_token(secret: str) -> str:
    """Create a signed session token."""
    signature = hmac.new(
        COOKIE_SECRET.encode(),
        secret.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    return f"valid:{signature}"


def verify_session_token(token: str) -> bool:
    """Verify the session token."""
    if not token or not token.startswith("valid:"):
        return False
    expected = create_session_token(get_admin_secret())
    return hmac.compare_digest(token, expected)


def require_admin_ui(request: Request):
    """
    Dependency to require admin UI authentication.
    Redirects to login page if not authenticated.
    """
    token = request.cookies.get(ADMIN_COOKIE_NAME)
    if not verify_session_token(token):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/admin-ui/login"}
        )
    return True


def check_admin_auth(request: Request) -> bool:
    """Check if user is authenticated (non-raising)."""
    token = request.cookies.get(ADMIN_COOKIE_NAME)
    return verify_session_token(token)
