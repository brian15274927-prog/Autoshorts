"""
Authentication Middleware.
Single source of truth for auth.
Extracts user_id from cookie, header, or creates guest user.
"""
import os
import uuid
import logging
from typing import Callable, Set, Optional

from fastapi import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

logger = logging.getLogger(__name__)

USER_ID_HEADER = "X-User-Id"
USER_ID_COOKIE = "videogen_user_id"
GUEST_USER_PREFIX = "guest_"


def is_browser_request(request: Request) -> bool:
    """Check if request is from a browser."""
    user_agent = request.headers.get("user-agent", "").lower()
    return "mozilla" in user_agent or "chrome" in user_agent or "safari" in user_agent


def generate_guest_user_id() -> str:
    """Generate a new guest user ID."""
    return f"{GUEST_USER_PREFIX}{uuid.uuid4().hex[:12]}"


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware.

    Priority:
    1. Cookie (videogen_user_id)
    2. Header (X-User-Id)
    3. Auto-generate guest user for browser requests
    4. Return 401 only for API calls without auth (non-browser)
    """

    EXCLUDED_PATHS: Set[str] = {
        "/",
        "/health",
        "/health/live",
        "/health/ready",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/static",
        "/favicon.ico",
    }

    SOFT_AUTH_PREFIXES: tuple = (
        "/app",
        "/api/clips",
        "/api/youtube",
        "/api/video",
        "/admin",
        "/admin-ui",
        "/orchestrate",
    )

    def __init__(
        self,
        app,
        excluded_paths: Optional[Set[str]] = None,
        require_auth: bool = True,
    ):
        super().__init__(app)
        self.excluded_paths = excluded_paths or self.EXCLUDED_PATHS
        self.require_auth = require_auth

        logger.info(f"AuthMiddleware initialized: require_auth={require_auth}")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and extract/create user_id."""
        path = request.url.path

        # Skip auth for excluded paths
        if self._is_excluded_path(path):
            request.state.user_id = None
            return await call_next(request)

        # Try to get user_id from multiple sources
        user_id = self._extract_user_id(request)
        is_browser = is_browser_request(request)
        needs_cookie = False

        # If no user_id and it's a browser request, create guest user
        if not user_id and is_browser:
            user_id = generate_guest_user_id()
            needs_cookie = True
            logger.debug(f"Created guest user: {user_id}")

        request.state.user_id = user_id

        # For soft auth paths, allow request without user_id
        if self._is_soft_auth_path(path):
            response = await call_next(request)
            if needs_cookie and user_id:
                response.set_cookie(
                    key=USER_ID_COOKIE,
                    value=user_id,
                    max_age=60 * 60 * 24 * 365,  # 1 year
                    httponly=True,
                    samesite="lax",
                )
            return response

        # For other paths, require auth only for non-browser requests
        if not user_id and self.require_auth and not is_browser:
            logger.warning(f"Missing auth: {request.method} {path}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": "Authentication required",
                    "code": "AUTH_REQUIRED",
                    "message": f"Missing {USER_ID_HEADER} header",
                },
            )

        # For browser requests without user_id on non-soft-auth paths,
        # still create a guest user
        if not user_id and is_browser:
            user_id = generate_guest_user_id()
            request.state.user_id = user_id
            needs_cookie = True

        response = await call_next(request)

        # Set cookie if we created a new user
        if needs_cookie and user_id:
            response.set_cookie(
                key=USER_ID_COOKIE,
                value=user_id,
                max_age=60 * 60 * 24 * 365,  # 1 year
                httponly=True,
                samesite="lax",
            )

        return response

    def _extract_user_id(self, request: Request) -> Optional[str]:
        """Extract user_id from cookie or header."""
        # 1. Try cookie first
        user_id = request.cookies.get(USER_ID_COOKIE)
        if user_id:
            return user_id

        # 2. Try header
        user_id = request.headers.get(USER_ID_HEADER)
        if user_id:
            return user_id

        return None

    def _is_excluded_path(self, path: str) -> bool:
        """Check if path is excluded from auth."""
        if path in self.excluded_paths:
            return True
        # Check static files
        if path.startswith("/static"):
            return True
        return False

    def _is_soft_auth_path(self, path: str) -> bool:
        """Check if path uses soft auth (no 401 for missing auth)."""
        for prefix in self.SOFT_AUTH_PREFIXES:
            if path.startswith(prefix):
                return True
        return False


__all__ = ["AuthMiddleware", "USER_ID_HEADER", "USER_ID_COOKIE", "is_browser_request"]
