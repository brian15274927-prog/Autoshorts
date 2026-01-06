"""
Admin Web UI Module.
Provides a web-based admin interface for managing users, credits, and jobs.
"""
from .routes import router as admin_ui_router

__all__ = ["admin_ui_router"]
