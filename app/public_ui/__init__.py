"""
Public User UI Module.
User-facing interface for Video Rendering SaaS.
"""
from .routes import router

public_ui_router = router

__all__ = ["public_ui_router"]
