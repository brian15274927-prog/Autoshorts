"""
Timestamps providers.
"""
from .base import BaseTimestampsProvider, TimestampSegment
from .whisper import WhisperTimestampsProvider
from .heuristic import HeuristicTimestampsProvider
from .factory import TimestampsProviderFactory, get_timestamps_provider

__all__ = [
    "BaseTimestampsProvider",
    "TimestampSegment",
    "WhisperTimestampsProvider",
    "HeuristicTimestampsProvider",
    "TimestampsProviderFactory",
    "get_timestamps_provider",
]
