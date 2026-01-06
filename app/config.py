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
class StockFootageConfig:
    """Stock Footage API Configuration."""
    pexels_api_key: Optional[str] = None
    pixabay_api_key: Optional[str] = None

    @property
    def has_pexels(self) -> bool:
        return bool(self.pexels_api_key and not self.pexels_api_key.startswith("PASTE_"))

    @property
    def has_pixabay(self) -> bool:
        return bool(self.pixabay_api_key and not self.pixabay_api_key.startswith("PASTE_"))

    @property
    def has_any_source(self) -> bool:
        return self.has_pexels or self.has_pixabay


@dataclass
class AppConfig:
    """Main Application Configuration."""
    ai: AIConfig
    stock: StockFootageConfig
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
            "stock_footage": {
                "pexels_configured": self.stock.has_pexels,
                "pixabay_configured": self.stock.has_pixabay,
                "any_source_available": self.stock.has_any_source,
            },
            "database": {
                "backend": self.storage_backend,
                "path": self.database_path,
            },
            "ready_for_faceless": self.ai.has_any_llm or True,  # Fallback script works
            "ready_for_stock_footage": self.stock.has_any_source,
        }

    def log_status(self):
        """Log configuration status (without exposing keys)."""
        status = self.validate()

        logger.info("=" * 50)
        logger.info("Configuration Status:")
        logger.info(f"  OpenAI API: {'OK' if status['ai']['openai_configured'] else 'NOT CONFIGURED'}")
        logger.info(f"  Anthropic API: {'OK' if status['ai']['anthropic_configured'] else 'NOT CONFIGURED'}")
        logger.info(f"  Pexels API: {'OK' if status['stock_footage']['pexels_configured'] else 'NOT CONFIGURED'}")
        logger.info(f"  Pixabay API: {'OK' if status['stock_footage']['pixabay_configured'] else 'NOT CONFIGURED'}")
        logger.info(f"  Database: {status['database']['backend']}")
        logger.info("=" * 50)

        if not status['ai']['any_llm_available']:
            logger.warning("No LLM configured - using fallback script generation")
        if not status['stock_footage']['any_source_available']:
            logger.warning("No stock footage API configured - video generation will use placeholder")


def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    ai_config = AIConfig(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    )

    stock_config = StockFootageConfig(
        pexels_api_key=os.getenv("PEXELS_API_KEY"),
        pixabay_api_key=os.getenv("PIXABAY_API_KEY"),
    )

    return AppConfig(
        ai=ai_config,
        stock=stock_config,
        storage_backend=os.getenv("STORAGE_BACKEND", "sqlite"),
        database_path=os.getenv("DATABASE_PATH", "data/app.db"),
        admin_secret=os.getenv("ADMIN_SECRET", "change-this-to-a-secure-secret"),
        debug=os.getenv("DEBUG", "false").lower() == "true",
    )


# Global config instance
config = load_config()
