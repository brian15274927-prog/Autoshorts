"""
Base class for voice/TTS providers.
"""
from abc import ABC, abstractmethod
from pathlib import Path


class BaseVoiceProvider(ABC):
    """Abstract base class for voice/TTS providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available."""
        pass

    @abstractmethod
    def synthesize(self, text: str, lang: str = "en") -> Path:
        """
        Synthesize speech from text.

        Args:
            text: Text to synthesize
            lang: Language code (e.g., 'en', 'ru')

        Returns:
            Path to generated audio file (WAV)
        """
        pass
