"""
Base class for asset providers.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List


class BaseAssetsProvider(ABC):
    """Abstract base class for asset providers."""

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
    def search_videos(self, query: str, limit: int = 5) -> List[Path]:
        """
        Search for videos matching query.

        Args:
            query: Search query
            limit: Maximum number of results

        Returns:
            List of paths to video files
        """
        pass

    @abstractmethod
    def search_images(self, query: str, limit: int = 5) -> List[Path]:
        """
        Search for images matching query.

        Args:
            query: Search query
            limit: Maximum number of results

        Returns:
            List of paths to image files
        """
        pass
