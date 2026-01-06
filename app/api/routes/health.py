"""
Health check endpoints.
"""
from fastapi import APIRouter, status
from datetime import datetime

from ..schemas import HealthResponse
from ..dependencies import check_celery_connection, check_redis_connection

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health Check",
    description="Check API and dependent services health status.",
)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.
    Returns service status and connectivity info.
    """
    celery_ok = check_celery_connection()
    redis_ok = check_redis_connection()

    overall_status = "healthy" if (celery_ok and redis_ok) else "degraded"

    return HealthResponse(
        status=overall_status,
        service="video-rendering-api",
        version="1.0.0",
        celery_connected=celery_ok,
        redis_connected=redis_ok,
        timestamp=datetime.utcnow(),
    )


@router.get(
    "/health/live",
    status_code=status.HTTP_200_OK,
    summary="Liveness Probe",
    description="Kubernetes liveness probe endpoint.",
)
async def liveness() -> dict:
    """Liveness probe - always returns OK if app is running."""
    return {"status": "alive"}


@router.get(
    "/health/ready",
    status_code=status.HTTP_200_OK,
    summary="Readiness Probe",
    description="Kubernetes readiness probe endpoint.",
)
async def readiness() -> dict:
    """Readiness probe - checks if app can handle requests."""
    redis_ok = check_redis_connection()

    if not redis_ok:
        return {"status": "not_ready", "reason": "Redis unavailable"}

    return {"status": "ready"}


@router.get(
    "/health/config",
    status_code=status.HTTP_200_OK,
    summary="Configuration Status",
    description="Check API key configuration status (does not expose actual keys).",
)
async def config_status() -> dict:
    """
    Configuration status endpoint.
    Returns which APIs are configured without exposing sensitive keys.
    """
    from app.config import config

    status = config.validate()

    return {
        "status": "configured" if status["ai"]["any_llm_available"] and status["stock_footage"]["any_source_available"] else "partial",
        "apis": {
            "openai": "configured" if status["ai"]["openai_configured"] else "missing",
            "anthropic": "configured" if status["ai"]["anthropic_configured"] else "not_set",
            "pexels": "configured" if status["stock_footage"]["pexels_configured"] else "missing",
            "pixabay": "configured" if status["stock_footage"]["pixabay_configured"] else "not_set",
        },
        "capabilities": {
            "ai_script_generation": status["ai"]["any_llm_available"],
            "stock_footage_search": status["stock_footage"]["any_source_available"],
            "faceless_video": True,  # Fallback always works
            "youtube_analysis": True,  # Basic analysis always works
        },
        "notes": [] if status["ai"]["any_llm_available"] else ["Using fallback script generation (set OPENAI_API_KEY for AI scripts)"],
    }
