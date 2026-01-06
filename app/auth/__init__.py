"""
Authentication Module.
Stub auth via X-User-Id header for MVP.
"""
from .models import User, Plan, PLAN_CREDITS
from .repository import UserRepository, get_user_repository
from .middleware import AuthMiddleware
from .dependencies import get_current_user, require_auth

__all__ = [
    "User",
    "Plan",
    "PLAN_CREDITS",
    "UserRepository",
    "get_user_repository",
    "AuthMiddleware",
    "get_current_user",
    "require_auth",
]
