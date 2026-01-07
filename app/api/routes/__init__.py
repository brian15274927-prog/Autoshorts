"""
API Routes.
"""
from .health import router as health_router
from .render import router as render_router
from .admin import router as admin_router
from .clips import router as clips_router
from .youtube import router as youtube_router
from .video import router as video_router
from .broll import router as broll_router
from .god_mode import router as god_mode_router
from .faceless import router as faceless_router
from .portraits import router as portraits_router

__all__ = [
    "health_router",
    "render_router",
    "admin_router",
    "clips_router",
    "youtube_router",
    "video_router",
    "broll_router",
    "god_mode_router",
    "faceless_router",
    "portraits_router",
]
