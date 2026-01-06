"""
Assets provider factory.
"""
from typing import Literal

from .base import BaseAssetsProvider
from .pexels import PexelsAssetsProvider
from .unsplash import UnsplashAssetsProvider
from .local import LocalAssetsProvider
from ..exceptions import ProviderUnavailable


ProviderType = Literal["auto", "pexels", "unsplash", "local"]


class AssetsProviderFactory:
    """Factory for creating asset providers with automatic fallback."""

    _providers = {
        "pexels": PexelsAssetsProvider,
        "unsplash": UnsplashAssetsProvider,
        "local": LocalAssetsProvider,
    }

    @classmethod
    def create(cls, provider: ProviderType = "auto") -> BaseAssetsProvider:
        if provider == "auto":
            return cls._create_auto()
        if provider not in cls._providers:
            return LocalAssetsProvider()
        return cls._providers[provider]()

    @classmethod
    def _create_auto(cls) -> BaseAssetsProvider:
        for name in ["pexels", "unsplash"]:
            try:
                p = cls._providers[name]()
                if p.is_available:
                    return p
            except Exception:
                continue
        return LocalAssetsProvider()

    @classmethod
    def get_with_fallback(cls, provider: ProviderType = "auto") -> BaseAssetsProvider:
        return _FallbackAssetsProvider(cls.create(provider))


class _FallbackAssetsProvider(BaseAssetsProvider):
    """Wrapper that catches errors and falls back to local provider."""

    def __init__(self, primary: BaseAssetsProvider):
        self._primary = primary
        self._fallback = LocalAssetsProvider()

    @property
    def name(self) -> str:
        return f"{self._primary.name}+fallback"

    @property
    def is_available(self) -> bool:
        return True

    def search_videos(self, query: str, limit: int = 5):
        try:
            if self._primary.is_available:
                result = self._primary.search_videos(query, limit)
                if result:
                    return result
        except (ProviderUnavailable, Exception):
            pass
        return self._fallback.search_videos(query, limit)

    def search_images(self, query: str, limit: int = 5):
        try:
            if self._primary.is_available:
                result = self._primary.search_images(query, limit)
                if result:
                    return result
        except (ProviderUnavailable, Exception):
            pass
        return self._fallback.search_images(query, limit)


def get_assets_provider(provider: ProviderType = "auto") -> BaseAssetsProvider:
    """Get an assets provider with automatic fallback to local."""
    return AssetsProviderFactory.get_with_fallback(provider)
