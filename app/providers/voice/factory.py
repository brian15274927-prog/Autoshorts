"""
Voice provider factory.
"""
from pathlib import Path
from typing import Literal

from .base import BaseVoiceProvider
from .openai_tts import OpenAITTSProvider
from .elevenlabs import ElevenLabsProvider
from .local import LocalVoiceProvider
from ..exceptions import ProviderUnavailable


ProviderType = Literal["auto", "openai", "elevenlabs", "local"]


class VoiceProviderFactory:
    """Factory for creating voice providers with automatic fallback."""

    _providers = {
        "openai": OpenAITTSProvider,
        "elevenlabs": ElevenLabsProvider,
        "local": LocalVoiceProvider,
    }

    @classmethod
    def create(cls, provider: ProviderType = "auto") -> BaseVoiceProvider:
        if provider == "auto":
            return cls._create_auto()
        if provider not in cls._providers:
            return LocalVoiceProvider()
        return cls._providers[provider]()

    @classmethod
    def _create_auto(cls) -> BaseVoiceProvider:
        for name in ["openai", "elevenlabs"]:
            try:
                p = cls._providers[name]()
                if p.is_available:
                    return p
            except Exception:
                continue
        return LocalVoiceProvider()

    @classmethod
    def get_with_fallback(cls, provider: ProviderType = "auto") -> BaseVoiceProvider:
        return _FallbackVoiceProvider(cls.create(provider))


class _FallbackVoiceProvider(BaseVoiceProvider):
    """Wrapper that catches errors and falls back to local provider."""

    def __init__(self, primary: BaseVoiceProvider):
        self._primary = primary
        self._fallback = LocalVoiceProvider()

    @property
    def name(self) -> str:
        return f"{self._primary.name}+fallback"

    @property
    def is_available(self) -> bool:
        return True

    def synthesize(self, text: str, lang: str = "en") -> Path:
        try:
            if self._primary.is_available:
                return self._primary.synthesize(text, lang)
        except (ProviderUnavailable, Exception):
            pass
        return self._fallback.synthesize(text, lang)


def get_voice_provider(provider: ProviderType = "auto") -> BaseVoiceProvider:
    """Get a voice provider with automatic fallback to local."""
    return VoiceProviderFactory.get_with_fallback(provider)
