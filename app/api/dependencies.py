"""
Shared dependencies for API routes.
"""
import logging
from typing import Generator
from functools import lru_cache

from app.celery_app import celery_app
from app.rendering.cost import CostCalculator

logger = logging.getLogger(__name__)


@lru_cache()
def get_cost_calculator() -> CostCalculator:
    """Get cached CostCalculator instance."""
    return CostCalculator()


def get_celery_app():
    """Get Celery app instance."""
    return celery_app


def check_celery_connection() -> bool:
    """Check if Celery/Redis is accessible."""
    try:
        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        return stats is not None
    except Exception as e:
        logger.warning(f"Celery connection check failed: {e}")
        return False


def check_redis_connection() -> bool:
    """Check if Redis is accessible."""
    try:
        celery_app.backend.client.ping()
        return True
    except Exception as e:
        logger.warning(f"Redis connection check failed: {e}")
        return False
