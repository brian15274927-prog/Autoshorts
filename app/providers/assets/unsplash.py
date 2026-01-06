"""
Unsplash asset provider.
"""
import os
from pathlib import Path
from typing import List, Optional

from .base import BaseAssetsProvider
from ..exceptions import ProviderUnavailable


class UnsplashAssetsProvider(BaseAssetsProvider):
    """Unsplash API asset provider."""

    ENV_KEY = "UNSPLASH_ACCESS_KEY"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get(self.ENV_KEY)

    @property
    def name(self) -> str:
        return "unsplash"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def search_videos(self, query: str, limit: int = 5) -> List[Path]:
        if not self.is_available:
            raise ProviderUnavailable(self.name, f"Missing {self.ENV_KEY}")
        raise ProviderUnavailable(self.name, "API integration not implemented")

    def search_images(self, query: str, limit: int = 5) -> List[Path]:
        if not self.is_available:
            raise ProviderUnavailable(self.name, f"Missing {self.ENV_KEY}")
        raise ProviderUnavailable(self.name, "API integration not implemented")
