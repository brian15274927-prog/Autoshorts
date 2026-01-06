"""
Timestamps provider factory.
"""
from pathlib import Path
from typing import List, Literal

from .base import BaseTimestampsProvider, TimestampSegment
from .whisper import WhisperTimestampsProvider
from .heuristic import HeuristicTimestampsProvider
from ..exceptions import ProviderUnavailable


ProviderType = Literal["auto", "whisper", "heuristic"]


class TimestampsProviderFactory:
    """Factory for creating timestamps providers with automatic fallback."""

    _providers = {
        "whisper": WhisperTimestampsProvider,
        "heuristic": HeuristicTimestampsProvider,
    }

    @classmethod
    def create(cls, provider: ProviderType = "auto") -> BaseTimestampsProvider:
        if provider == "auto":
            return cls._create_auto()
        if provider not in cls._providers:
            return HeuristicTimestampsProvider()
        return cls._providers[provider]()

    @classmethod
    def _create_auto(cls) -> BaseTimestampsProvider:
        try:
            p = WhisperTimestampsProvider()
            if p.is_available:
                return p
        except Exception:
            pass
        return HeuristicTimestampsProvider()

    @classmethod
    def get_with_fallback(cls, provider: ProviderType = "auto") -> BaseTimestampsProvider:
        return _FallbackTimestampsProvider(cls.create(provider))


class _FallbackTimestampsProvider(BaseTimestampsProvider):
    """Wrapper that catches errors and falls back to heuristic provider."""

    def __init__(self, primary: BaseTimestampsProvider):
        self._primary = primary
        self._fallback = HeuristicTimestampsProvider()

    @property
    def name(self) -> str:
        return f"{self._primary.name}+fallback"

    @property
    def is_available(self) -> bool:
        return True

    def extract(self, audio_path: Path, text: str) -> List[TimestampSegment]:
        try:
            if self._primary.is_available:
                result = self._primary.extract(audio_path, text)
                if result:
                    return result
        except (ProviderUnavailable, Exception):
            pass
        return self._fallback.extract(audio_path, text)


def get_timestamps_provider(provider: ProviderType = "auto") -> BaseTimestampsProvider:
    """Get a timestamps provider with automatic fallback to heuristic."""
    return TimestampsProviderFactory.get_with_fallback(provider)
