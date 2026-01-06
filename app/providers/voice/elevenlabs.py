"""
ElevenLabs voice provider.
"""
import os
from pathlib import Path
from typing import Optional

from .base import BaseVoiceProvider
from ..exceptions import ProviderUnavailable


class ElevenLabsProvider(BaseVoiceProvider):
    """ElevenLabs TTS API provider."""

    ENV_KEY = "ELEVENLABS_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get(self.ENV_KEY)

    @property
    def name(self) -> str:
        return "elevenlabs"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def synthesize(self, text: str, lang: str = "en") -> Path:
        if not self.is_available:
            raise ProviderUnavailable(self.name, f"Missing {self.ENV_KEY}")
        raise ProviderUnavailable(self.name, "API integration not implemented")
