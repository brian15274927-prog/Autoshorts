"""
Application Configuration - Environment Variable Management.
Loads and validates configuration from .env file.
"""
import os
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env from project root
PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
    logger.info(f"Loaded environment from {ENV_FILE}")
else:
    logger.warning(f".env file not found at {ENV_FILE}")


@dataclass
class AIConfig:
    """AI/LLM Configuration."""
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None  # For Nano Banana / Gemini
    kie_api_key: Optional[str] = None  # For Kie image generation service
    openai_model: str = "gpt-4o-mini"

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key and not self.openai_api_key.startswith("PASTE_"))

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key and not self.anthropic_api_key.startswith("PASTE_"))

    @property
    def has_google(self) -> bool:
        return bool(self.google_api_key and not self.google_api_key.startswith("PASTE_"))

    @property
    def has_kie(self) -> bool:
        return bool(self.kie_api_key and not self.kie_api_key.startswith("PASTE_"))

    @property
    def has_any_llm(self) -> bool:
        return self.has_openai or self.has_anthropic


@dataclass
class PathsConfig:
    """File system paths configuration."""
    data_dir: Path
    temp_images_dir: Path
    ffmpeg_path: str
    ffprobe_path: str

    @classmethod
    def detect(cls) -> "PathsConfig":
        """Auto-detect paths based on environment and system."""
        # Data directory - use project root/data by default
        data_dir = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
        data_dir.mkdir(parents=True, exist_ok=True)

        # Temp images directory
        temp_images_dir = Path(os.getenv("TEMP_IMAGES_DIR", str(data_dir / "temp_images")))
        temp_images_dir.mkdir(parents=True, exist_ok=True)

        # FFmpeg paths - auto-detect
        ffmpeg_path = cls._find_ffmpeg()
        ffprobe_path = cls._find_ffprobe()

        return cls(
            data_dir=data_dir,
            temp_images_dir=temp_images_dir,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path
        )

    @staticmethod
    def _find_ffmpeg() -> str:
        """Find FFmpeg executable."""
        # Check environment variable first
        env_path = os.getenv("FFMPEG_PATH")
        if env_path and os.path.exists(env_path):
            return env_path

        # Check common locations
        common_paths = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
        ]

        for path in common_paths:
            if os.path.exists(path):
                return path

        # Try imageio-ffmpeg
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass

        # Fallback to system PATH
        return "ffmpeg"

    @staticmethod
    def _find_ffprobe() -> str:
        """Find FFprobe executable."""
        # Check environment variable first
        env_path = os.getenv("FFPROBE_PATH")
        if env_path and os.path.exists(env_path):
            return env_path

        # Check common locations
        common_paths = [
            r"C:\ffmpeg\bin\ffprobe.exe",
            r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
            "/usr/bin/ffprobe",
            "/usr/local/bin/ffprobe",
        ]

        for path in common_paths:
            if os.path.exists(path):
                return path

        # Try imageio-ffmpeg
        try:
            import imageio_ffmpeg
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")
            if os.path.exists(ffprobe_path):
                return ffprobe_path
        except ImportError:
            pass

        # Fallback to system PATH
        return "ffprobe"


@dataclass
class AppConfig:
    """Main Application Configuration."""
    ai: AIConfig
    paths: PathsConfig
    storage_backend: str = "sqlite"
    database_path: str = "data/app.db"
    admin_secret: Optional[str] = None  # MUST be set via ADMIN_SECRET env var
    debug: bool = False

    def __post_init__(self):
        """Validate critical configuration."""
        if not self.admin_secret:
            logger.warning("ADMIN_SECRET not set - God Mode endpoints will be disabled")
        elif len(self.admin_secret) < 32:
            logger.warning("ADMIN_SECRET should be at least 32 characters for security")

    def validate(self) -> dict:
        """Validate configuration and return status."""
        return {
            "ai": {
                "openai_configured": self.ai.has_openai,
                "anthropic_configured": self.ai.has_anthropic,
                "kie_configured": self.ai.has_kie,
                "any_llm_available": self.ai.has_any_llm,
            },
            "database": {
                "backend": self.storage_backend,
                "path": self.database_path,
            },
            "ready_for_faceless": self.ai.has_any_llm or True,  # Fallback script works
        }

    def log_status(self):
        """Log configuration status (without exposing keys)."""
        status = self.validate()

        logger.info("=" * 50)
        logger.info("Configuration Status:")
        logger.info(f"  OpenAI API: {'OK' if status['ai']['openai_configured'] else 'NOT CONFIGURED'}")
        logger.info(f"  Anthropic API: {'OK' if status['ai']['anthropic_configured'] else 'NOT CONFIGURED'}")
        logger.info(f"  Kie Image API: {'OK' if status['ai']['kie_configured'] else 'NOT CONFIGURED'}")
        logger.info(f"  Database: {status['database']['backend']}")
        logger.info(f"  Data Dir: {self.paths.data_dir}")
        logger.info(f"  FFmpeg: {self.paths.ffmpeg_path}")
        logger.info("=" * 50)

        if not status['ai']['any_llm_available']:
            logger.warning("No LLM configured - using fallback script generation")


def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    ai_config = AIConfig(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        kie_api_key=os.getenv("KIE_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    )

    paths_config = PathsConfig.detect()

    return AppConfig(
        ai=ai_config,
        paths=paths_config,
        storage_backend=os.getenv("STORAGE_BACKEND", "sqlite"),
        database_path=os.getenv("DATABASE_PATH", "data/app.db"),
        admin_secret=os.getenv("ADMIN_SECRET"),  # No default - must be explicitly set
        debug=os.getenv("DEBUG", "false").lower() == "true",
    )


# Global config instance
config = load_config()
