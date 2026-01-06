"""
Director Module - AI Decision Engine for Video Clip Selection.

Based on video-db/Director architecture.
Director = AI brain that analyzes text and decides WHAT to clip.
Revideo = renderer that executes HOW to render.
"""
from .engine import DirectorEngine
from .models import ClipDecision, DirectorResult

__all__ = ["DirectorEngine", "ClipDecision", "DirectorResult"]
