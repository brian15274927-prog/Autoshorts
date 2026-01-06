"""
Base class for timestamps providers.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, TypedDict


class TimestampSegment(TypedDict):
    start: float
    end: float
    text: str


class BaseTimestampsProvider(ABC):
    """Abstract base class for timestamps providers."""

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
    def extract(self, audio_path: Path, text: str) -> List[TimestampSegment]:
        """
        Extract word/sentence timestamps from audio.

        Args:
            audio_path: Path to audio file
            text: Original text for alignment

        Returns:
            List of timestamp segments with start, end, and text
        """
        pass
