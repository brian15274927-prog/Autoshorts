"""
API Middleware.

Re-exports from app.auth for backwards compatibility.
"""
from app.auth.middleware import AuthMiddleware

__all__ = ["AuthMiddleware"]
