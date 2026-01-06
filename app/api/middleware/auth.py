"""
Authentication Middleware Re-export.

Thin wrapper - all auth logic lives in app.auth.middleware.
This module exists for backwards compatibility only.
"""
from app.auth.middleware import AuthMiddleware, USER_ID_HEADER

__all__ = ["AuthMiddleware", "USER_ID_HEADER"]
