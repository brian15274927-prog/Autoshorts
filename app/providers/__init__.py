"""
Providers Layer.

Provides unified access to external and local providers for:
- Assets (videos, images)
- Voice/TTS
- Timestamps extraction

All providers support automatic fallback to local implementations.
"""
from .exceptions import ProviderError, ProviderUnavailable

from .assets import (
    BaseAssetsProvider,
    PexelsAssetsProvider,
    UnsplashAssetsProvider,
    LocalAssetsProvider,
    AssetsProviderFactory,
    get_assets_provider,
)

from .voice import (
    BaseVoiceProvider,
    OpenAITTSProvider,
    ElevenLabsProvider,
    LocalVoiceProvider,
    VoiceProviderFactory,
    get_voice_provider,
)

from .timestamps import (
    BaseTimestampsProvider,
    TimestampSegment,
    WhisperTimestampsProvider,
    HeuristicTimestampsProvider,
    TimestampsProviderFactory,
    get_timestamps_provider,
)

__all__ = [
    # Exceptions
    "ProviderError",
    "ProviderUnavailable",

    # Assets
    "BaseAssetsProvider",
    "PexelsAssetsProvider",
    "UnsplashAssetsProvider",
    "LocalAssetsProvider",
    "AssetsProviderFactory",
    "get_assets_provider",

    # Voice
    "BaseVoiceProvider",
    "OpenAITTSProvider",
    "ElevenLabsProvider",
    "LocalVoiceProvider",
    "VoiceProviderFactory",
    "get_voice_provider",

    # Timestamps
    "BaseTimestampsProvider",
    "TimestampSegment",
    "WhisperTimestampsProvider",
    "HeuristicTimestampsProvider",
    "TimestampsProviderFactory",
    "get_timestamps_provider",
]
