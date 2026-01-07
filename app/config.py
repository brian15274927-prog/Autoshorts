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
    openai_model: str = "gpt-4o-mini"

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key and not self.openai_api_key.startswith("PASTE_"))

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key and not self.anthropic_api_key.startswith("PASTE_"))

    @property
    def has_any_llm(self) -> bool:
        return self.has_openai or self.has_anthropic


@dataclass
class AppConfig:
    """Main Application Configuration."""
    ai: AIConfig
    storage_backend: str = "sqlite"
    database_path: str = "data/app.db"
    admin_secret: str = "change-this-to-a-secure-secret"
    debug: bool = False

    def validate(self) -> dict:
        """Validate configuration and return status."""
        return {
            "ai": {
                "openai_configured": self.ai.has_openai,
                "anthropic_configured": self.ai.has_anthropic,
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
        logger.info(f"  Database: {status['database']['backend']}")
        logger.info("=" * 50)

        if not status['ai']['any_llm_available']:
            logger.warning("No LLM configured - using fallback script generation")


def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    ai_config = AIConfig(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    )

    return AppConfig(
        ai=ai_config,
        storage_backend=os.getenv("STORAGE_BACKEND", "sqlite"),
        database_path=os.getenv("DATABASE_PATH", "data/app.db"),
        admin_secret=os.getenv("ADMIN_SECRET", "change-this-to-a-secure-secret"),
        debug=os.getenv("DEBUG", "false").lower() == "true",
    )


# Global config instance
config = load_config()
