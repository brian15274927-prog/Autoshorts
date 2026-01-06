"""
Provider exceptions.
"""


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(self, provider: str, message: str):
        self.provider = provider
        self.message = message
        super().__init__(f"[{provider}] {message}")


class ProviderUnavailable(ProviderError):
    """Provider is not available (missing API key, network error, etc.)."""

    def __init__(self, provider: str, reason: str = "unavailable"):
        super().__init__(provider, f"Provider unavailable: {reason}")
        self.reason = reason
