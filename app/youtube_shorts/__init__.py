"""
YouTube Shorts Module - Analyze YouTube videos and create short clips.
"""
from .routes import router as youtube_shorts_router
from .service import YouTubeShortsService

__all__ = ["youtube_shorts_router", "YouTubeShortsService"]
