"""
Whisper timestamps provider.
"""
import os
from pathlib import Path
from typing import List, Optional

from .base import BaseTimestampsProvider, TimestampSegment
from ..exceptions import ProviderUnavailable


class WhisperTimestampsProvider(BaseTimestampsProvider):
    """OpenAI Whisper-based timestamps provider."""

    ENV_KEY = "OPENAI_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get(self.ENV_KEY)

    @property
    def name(self) -> str:
        return "whisper"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def extract(self, audio_path: Path, text: str) -> List[TimestampSegment]:
        if not self.is_available:
            raise ProviderUnavailable(self.name, f"Missing {self.ENV_KEY}")
        raise ProviderUnavailable(self.name, "API integration not implemented")
