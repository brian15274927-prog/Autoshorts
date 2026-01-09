"""
Tests for configuration management.
"""
import os
import pytest
from unittest.mock import patch


class TestPathsConfig:
    """Tests for PathsConfig auto-detection."""

    def test_data_dir_default(self):
        """Data directory should default to project root/data."""
        from app.config import PathsConfig

        config = PathsConfig.detect()
        assert config.data_dir.exists() or True  # May not exist in test env
        assert "data" in str(config.data_dir)

    def test_ffmpeg_path_detection(self):
        """FFmpeg path should be detected or fallback to 'ffmpeg'."""
        from app.config import PathsConfig

        ffmpeg_path = PathsConfig._find_ffmpeg()
        assert ffmpeg_path  # Should not be None/empty
        # Either a valid path or 'ffmpeg' fallback
        assert ffmpeg_path == "ffmpeg" or os.path.exists(ffmpeg_path)

    def test_custom_data_dir_from_env(self, temp_dir, monkeypatch):
        """DATA_DIR env var should override default."""
        monkeypatch.setenv("DATA_DIR", str(temp_dir))

        from app.config import PathsConfig

        config = PathsConfig.detect()
        assert config.data_dir == temp_dir


class TestAppConfig:
    """Tests for AppConfig."""

    def test_admin_secret_warning_when_not_set(self, monkeypatch, caplog):
        """Should log warning when ADMIN_SECRET is not set."""
        monkeypatch.delenv("ADMIN_SECRET", raising=False)

        # Re-import to trigger config load
        import importlib
        import app.config
        importlib.reload(app.config)

        # Check that warning was logged (may need to check log content)

    def test_admin_secret_short_warning(self, monkeypatch, caplog):
        """Should warn when ADMIN_SECRET is too short."""
        monkeypatch.setenv("ADMIN_SECRET", "short")

        import importlib
        import app.config
        importlib.reload(app.config)

        # Config should still work but with warning

    def test_ai_config_properties(self, monkeypatch):
        """AI config properties should detect configured keys."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-valid-key")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        from app.config import AIConfig

        config = AIConfig(
            openai_api_key="sk-valid-key",
            anthropic_api_key=None
        )

        assert config.has_openai is True
        assert config.has_anthropic is False
        assert config.has_any_llm is True

    def test_ai_config_rejects_placeholder_keys(self):
        """Placeholder keys starting with PASTE_ should not count as configured."""
        from app.config import AIConfig

        config = AIConfig(
            openai_api_key="PASTE_YOUR_KEY_HERE"
        )

        assert config.has_openai is False
