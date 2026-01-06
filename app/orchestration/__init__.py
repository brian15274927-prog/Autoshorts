"""
Orchestration Module.

Provides multi-mode video generation orchestration:
- TEXT: Text script -> TTS -> Video
- MUSIC: Music track -> Beat-synced video
- AUDIO: Audio file -> Transcription -> Video
- LONG: Long video -> Multiple short clips

Usage:
    from app.orchestration import orchestration_router
    app.include_router(orchestration_router)
"""
from .enums import OrchestrationMode
from .base import BaseOrchestrator, OrchestrationResult
from .text_mode import TextModeOrchestrator
from .music_mode import MusicModeOrchestrator
from .audio_mode import AudioModeOrchestrator
from .long_video_mode import LongVideoModeOrchestrator
from .router import router as orchestration_router

__all__ = [
    # Enums
    "OrchestrationMode",

    # Base classes
    "BaseOrchestrator",
    "OrchestrationResult",

    # Orchestrators
    "TextModeOrchestrator",
    "MusicModeOrchestrator",
    "AudioModeOrchestrator",
    "LongVideoModeOrchestrator",

    # Router
    "orchestration_router",
]
