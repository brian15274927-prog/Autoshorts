"""
Orchestration API Router.

Provides endpoints for different video generation modes.
Each endpoint accepts mode-specific input and returns orchestration result.
"""
import logging
import uuid
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, status, Depends, Header
from pydantic import BaseModel, Field

from .enums import OrchestrationMode
from .text_mode import TextModeOrchestrator
from .music_mode import MusicModeOrchestrator
from .audio_mode import AudioModeOrchestrator
from .long_video_mode import LongVideoModeOrchestrator

from app.auth.models import User
from app.auth.dependencies import get_current_user
from app.credits.service import get_credit_service
from app.credits.job_tracker import get_job_tracker
from app.credits.exceptions import InsufficientCreditsError
from app.persistence.idempotency_repo import (
    get_idempotency_repository,
    IdempotencyStatus,
)
from app.rendering.tasks import render_video_task
from app.celery_app import celery_app

logger = logging.getLogger(__name__)


def _check_redis_connection() -> bool:
    """Check if Redis is accessible."""
    try:
        celery_app.backend.client.ping()
        return True
    except Exception as e:
        logger.warning(f"Redis connection check failed: {e}")
        return False

router = APIRouter(prefix="/orchestrate", tags=["Orchestration"])

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"


# =============================================================================
# Request Models
# =============================================================================

class ResolutionSettings(BaseModel):
    """Video resolution settings."""
    width: int = Field(default=1080, ge=480, le=3840)
    height: int = Field(default=1920, ge=480, le=3840)


class VoiceSettings(BaseModel):
    """TTS voice configuration for text mode."""
    voice_id: str = Field(default="alloy", description="Voice identifier")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float = Field(default=1.0, ge=0.5, le=2.0)


class SubtitleSettings(BaseModel):
    """Subtitle styling options."""
    enabled: bool = Field(default=True)
    font: str = Field(default="Arial")
    size: str = Field(default="medium", description="small, medium, large")
    highlight_active: bool = Field(default=True)


class TextModeRequest(BaseModel):
    """Request body for text-to-video orchestration."""
    script_text: str = Field(
        ...,
        min_length=10,
        max_length=10000,
        description="Text script for voiceover"
    )
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    visual_style: str = Field(
        default="cinematic",
        description="Visual style: cinematic, minimal, vibrant, dark"
    )
    background_type: str = Field(
        default="video",
        description="Background type: video, image, solid"
    )
    subtitles: SubtitleSettings = Field(default_factory=SubtitleSettings)
    resolution: ResolutionSettings = Field(default_factory=ResolutionSettings)
    fps: int = Field(default=30, ge=15, le=60)
    lang: str = Field(default="ru", description="Language code for TTS")
    background_music: Optional[str] = Field(
        default=None,
        description="Background music style or URL"
    )


class MusicModeRequest(BaseModel):
    """Request body for music-to-clip orchestration."""
    audio_path: Optional[str] = Field(default=None, description="Path to music file")
    audio_url: Optional[str] = Field(default=None, description="URL to download music")
    visual_style: str = Field(default="cinematic", description="Style: motivation, cinematic, dark, abstract, random")
    clip_length: float = Field(default=10.0, ge=3.0, le=60.0, description="Clip duration in seconds")
    clip_start: float = Field(default=0.0, ge=0.0, description="Start time in audio")
    color_palette: List[str] = Field(default=["#8B5CF6", "#06B6D4", "#EC4899"])
    sync_intensity: str = Field(default="medium")
    lyrics_text: Optional[str] = Field(default=None)
    resolution: ResolutionSettings = Field(default_factory=ResolutionSettings)
    fps: int = Field(default=30, ge=15, le=60)


class AudioModeRequest(BaseModel):
    """Request body for audio-to-video orchestration."""
    audio_path: Optional[str] = Field(default=None, description="Path to audio file")
    audio_url: Optional[str] = Field(default=None, description="URL to download audio")
    transcript_text: Optional[str] = Field(default=None, description="Optional transcript for better subtitles")
    visual_style: str = Field(default="podcast", description="Style: podcast, motivation, news, education, story, random")
    language: str = Field(default="auto")
    subtitles: SubtitleSettings = Field(default_factory=SubtitleSettings)
    resolution: ResolutionSettings = Field(default_factory=ResolutionSettings)
    fps: int = Field(default=30, ge=15, le=60)


class LongModeRequest(BaseModel):
    """Request body for long video → shorts orchestration."""
    video_path: Optional[str] = Field(default=None, description="Path to source video file")
    video_url: Optional[str] = Field(default=None, description="URL to download video")
    clip_length: float = Field(default=15.0, ge=5.0, le=60.0, description="Target clip duration")
    max_clips: int = Field(default=5, ge=1, le=20, description="Maximum clips to generate")
    min_clip_length: float = Field(default=8.0, ge=3.0, le=30.0, description="Minimum clip duration")
    max_clip_length: float = Field(default=60.0, ge=10.0, le=120.0, description="Maximum clip duration")
    visual_style: str = Field(default="education", description="Style: education, podcast, motivation, news, story")
    subtitles: SubtitleSettings = Field(default_factory=SubtitleSettings)
    resolution: ResolutionSettings = Field(default_factory=ResolutionSettings)
    fps: int = Field(default=30, ge=15, le=60)


# =============================================================================
# Response Models
# =============================================================================

class OrchestrationResponse(BaseModel):
    """Response for successful orchestration."""
    status: str = "queued"
    mode: str
    task_id: str
    job_id: str
    message: str
    estimated_duration_seconds: float
    created_at: datetime


class OrchestrationStubResponse(BaseModel):
    """Stub response for unimplemented orchestration."""
    status: str = "stub"
    mode: str
    message: str
    request_received: Dict[str, Any]


class ModeInfoResponse(BaseModel):
    """Information about orchestration modes."""
    modes: List[Dict[str, str]]


class BatchClipInfo(BaseModel):
    """Information about a single clip in batch."""
    clip_id: str
    clip_index: int
    start: float
    end: float
    duration: float


class LongModeResponse(BaseModel):
    """Response for long video → shorts batch orchestration."""
    status: str = "queued"
    mode: str
    batch_id: str
    clips_count: int
    clips: List[BatchClipInfo]
    task_ids: List[str]
    message: str
    source_duration: float
    created_at: datetime


# =============================================================================
# Helper Functions
# =============================================================================

def _compute_request_hash(request_data: Dict[str, Any]) -> str:
    """Compute hash of request for idempotency."""
    repo = get_idempotency_repository()
    return repo.compute_request_hash(request_data)


# =============================================================================
# Endpoints
# =============================================================================

@router.get(
    "",
    response_model=ModeInfoResponse,
    summary="List Orchestration Modes",
    description="Get list of available video generation modes",
)
async def list_modes() -> ModeInfoResponse:
    """List all available orchestration modes."""
    modes = []
    for mode in OrchestrationMode:
        modes.append({
            "mode": mode.value,
            "display_name": mode.display_name,
            "description": mode.description,
            "endpoint": f"/orchestrate/{mode.value}",
        })
    return ModeInfoResponse(modes=modes)


@router.post(
    "/text",
    response_model=OrchestrationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Text to Video",
    description="Generate video with AI voiceover from text script",
)
async def orchestrate_text(
    request: TextModeRequest,
    user: User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias=IDEMPOTENCY_KEY_HEADER),
) -> OrchestrationResponse:
    """
    Orchestrate text-to-video generation.

    Pipeline:
    1. Generate TTS audio from script
    2. Extract word timestamps
    3. Fetch background visuals
    4. Build and submit render job
    """
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Missing required header",
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": f"{IDEMPOTENCY_KEY_HEADER} header is required",
            },
        )

    idempotency_repo = get_idempotency_repository()
    request_data = {
        "mode": "text",
        "script_text_hash": hash(request.script_text),
        "visual_style": request.visual_style,
        "resolution": f"{request.resolution.width}x{request.resolution.height}",
    }
    request_hash = _compute_request_hash(request_data)

    existing = idempotency_repo.find_by_key(user.user_id, idempotency_key)
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "Request hash mismatch",
                    "code": "IDEMPOTENCY_HASH_MISMATCH",
                    "message": "Request body differs from original request",
                },
            )

        if existing.status == IdempotencyStatus.COMPLETED:
            return OrchestrationResponse(
                status="queued",
                mode=OrchestrationMode.TEXT.value,
                task_id=existing.task_id,
                job_id=existing.job_id,
                message="Render job already queued (idempotent response)",
                estimated_duration_seconds=0,
                created_at=existing.created_at,
            )

        if existing.status == IdempotencyStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "Request in progress",
                    "code": "IDEMPOTENCY_PENDING",
                    "message": "A request with this key is already being processed",
                },
            )

        idempotency_repo.delete_failed(user.user_id, idempotency_key)

    try:
        idempotency_repo.create_pending(
            user_id=user.user_id,
            key=idempotency_key,
            request_hash=request_hash,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Concurrent request",
                "code": "IDEMPOTENCY_RACE",
                "message": "Another request with this key is being processed",
            },
        )

    if not _check_redis_connection():
        idempotency_repo.update_failed(user.user_id, idempotency_key, "Service unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "Render queue unavailable", "code": "SERVICE_UNAVAILABLE"},
        )

    credit_service = get_credit_service()
    job_tracker = get_job_tracker()
    credit_deducted = False
    job_id = f"text_{uuid.uuid4().hex[:12]}"

    try:
        credit_service.deduct_for_render(user, job_id=job_id)
        credit_deducted = True
    except InsufficientCreditsError as e:
        idempotency_repo.update_failed(user.user_id, idempotency_key, "Insufficient credits")
        raise e.to_http_exception()

    try:
        orchestrator = TextModeOrchestrator()

        orchestration_request = {
            "script_text": request.script_text,
            "visual_style": request.visual_style,
            "lang": request.lang,
            "resolution": {
                "width": request.resolution.width,
                "height": request.resolution.height,
            },
            "fps": request.fps,
            "subtitles": {
                "enabled": request.subtitles.enabled,
                "size": request.subtitles.size,
            },
            "job_id": job_id,
        }

        result = orchestrator.build_render_job(orchestration_request)

        render_kwargs = result.render_job

        task = render_video_task.delay(**render_kwargs)

        job_tracker.track_job(
            task_id=task.id,
            job_id=job_id,
            user_id=user.user_id,
        )

        idempotency_repo.update_completed(
            user_id=user.user_id,
            key=idempotency_key,
            task_id=task.id,
            job_id=job_id,
        )

        logger.info(
            f"Text orchestration complete: job_id={job_id}, task_id={task.id}, "
            f"user={user.user_id}, duration={result.estimated_duration_seconds:.1f}s"
        )

        return OrchestrationResponse(
            status="queued",
            mode=OrchestrationMode.TEXT.value,
            task_id=task.id,
            job_id=job_id,
            message="Video generation queued successfully",
            estimated_duration_seconds=result.estimated_duration_seconds,
            created_at=datetime.utcnow(),
        )

    except ValueError as e:
        if credit_deducted:
            try:
                credit_service.rollback_render_credit(user.user_id, job_id=job_id)
                logger.info(f"Credit rollback for validation error: user={user.user_id}")
            except Exception as rollback_error:
                logger.error(f"Failed to rollback credit: {rollback_error}")

        idempotency_repo.update_failed(user.user_id, idempotency_key, str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "Validation failed", "message": str(e)},
        )

    except Exception as e:
        if credit_deducted:
            try:
                credit_service.rollback_render_credit(user.user_id, job_id=job_id)
                logger.info(f"Credit rollback after failure: user={user.user_id}")
            except Exception as rollback_error:
                logger.error(f"CRITICAL: Failed to rollback credit: {rollback_error}")

        idempotency_repo.update_failed(user.user_id, idempotency_key, str(e))
        logger.exception(f"Text orchestration failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Orchestration failed", "message": str(e)},
        )


@router.post(
    "/music",
    response_model=OrchestrationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Music to Clip",
    description="Generate beat-synced music video clip",
)
async def orchestrate_music(
    request: MusicModeRequest,
    user: User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias=IDEMPOTENCY_KEY_HEADER),
) -> OrchestrationResponse:
    """
    Orchestrate music-to-clip generation.

    Pipeline:
    1. Analyze audio for beats
    2. Select video assets
    3. Build beat-synced scenes
    4. Submit render job
    """
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Missing required header",
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": f"{IDEMPOTENCY_KEY_HEADER} header is required",
            },
        )

    if not request.audio_path and not request.audio_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "AUDIO_REQUIRED",
                "message": "Требуется audio_path или audio_url",
            },
        )

    audio_path = request.audio_path
    if not audio_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "AUDIO_PATH_REQUIRED",
                "message": "audio_url не поддерживается. Используйте audio_path.",
            },
        )

    idempotency_repo = get_idempotency_repository()
    request_data = {
        "mode": "music",
        "audio_path": audio_path,
        "visual_style": request.visual_style,
        "clip_length": request.clip_length,
        "resolution": f"{request.resolution.width}x{request.resolution.height}",
    }
    request_hash = _compute_request_hash(request_data)

    existing = idempotency_repo.find_by_key(user.user_id, idempotency_key)
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "Request hash mismatch",
                    "code": "IDEMPOTENCY_HASH_MISMATCH",
                    "message": "Request body differs from original request",
                },
            )

        if existing.status == IdempotencyStatus.COMPLETED:
            return OrchestrationResponse(
                status="queued",
                mode=OrchestrationMode.MUSIC.value,
                task_id=existing.task_id,
                job_id=existing.job_id,
                message="Render job already queued (idempotent response)",
                estimated_duration_seconds=0,
                created_at=existing.created_at,
            )

        if existing.status == IdempotencyStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "Request in progress",
                    "code": "IDEMPOTENCY_PENDING",
                    "message": "A request with this key is already being processed",
                },
            )

        idempotency_repo.delete_failed(user.user_id, idempotency_key)

    try:
        idempotency_repo.create_pending(
            user_id=user.user_id,
            key=idempotency_key,
            request_hash=request_hash,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Concurrent request",
                "code": "IDEMPOTENCY_RACE",
                "message": "Another request with this key is being processed",
            },
        )

    if not _check_redis_connection():
        idempotency_repo.update_failed(user.user_id, idempotency_key, "Service unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "Render queue unavailable", "code": "SERVICE_UNAVAILABLE"},
        )

    credit_service = get_credit_service()
    job_tracker = get_job_tracker()
    credit_deducted = False
    job_id = f"music_{uuid.uuid4().hex[:12]}"

    try:
        credit_service.deduct_for_render(user, job_id=job_id)
        credit_deducted = True
    except InsufficientCreditsError as e:
        idempotency_repo.update_failed(user.user_id, idempotency_key, "Insufficient credits")
        raise e.to_http_exception()

    try:
        orchestrator = MusicModeOrchestrator()

        orchestration_request = {
            "audio_path": audio_path,
            "style": request.visual_style,
            "clip_length": request.clip_length,
            "clip_start": request.clip_start,
            "resolution": {
                "width": request.resolution.width,
                "height": request.resolution.height,
            },
            "fps": request.fps,
            "job_id": job_id,
        }

        result = orchestrator.build_render_job(orchestration_request)

        render_kwargs = result.render_job

        task = render_video_task.delay(**render_kwargs)

        job_tracker.track_job(
            task_id=task.id,
            job_id=job_id,
            user_id=user.user_id,
        )

        idempotency_repo.update_completed(
            user_id=user.user_id,
            key=idempotency_key,
            task_id=task.id,
            job_id=job_id,
        )

        logger.info(
            f"Music orchestration complete: job_id={job_id}, task_id={task.id}, "
            f"user={user.user_id}, duration={result.estimated_duration_seconds:.1f}s, "
            f"beats={result.metadata.get('beats_detected', 0)}, tempo={result.metadata.get('tempo_bpm', 0)}bpm"
        )

        return OrchestrationResponse(
            status="queued",
            mode=OrchestrationMode.MUSIC.value,
            task_id=task.id,
            job_id=job_id,
            message="Music clip generation queued successfully",
            estimated_duration_seconds=result.estimated_duration_seconds,
            created_at=datetime.utcnow(),
        )

    except ValueError as e:
        if credit_deducted:
            try:
                credit_service.rollback_render_credit(user.user_id, job_id=job_id)
                logger.info(f"Credit rollback for validation error: user={user.user_id}")
            except Exception as rollback_error:
                logger.error(f"Failed to rollback credit: {rollback_error}")

        idempotency_repo.update_failed(user.user_id, idempotency_key, str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "Validation failed", "message": str(e)},
        )

    except FileNotFoundError as e:
        if credit_deducted:
            try:
                credit_service.rollback_render_credit(user.user_id, job_id=job_id)
                logger.info(f"Credit rollback for file not found: user={user.user_id}")
            except Exception as rollback_error:
                logger.error(f"Failed to rollback credit: {rollback_error}")

        idempotency_repo.update_failed(user.user_id, idempotency_key, str(e))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "File not found", "message": str(e)},
        )

    except Exception as e:
        if credit_deducted:
            try:
                credit_service.rollback_render_credit(user.user_id, job_id=job_id)
                logger.info(f"Credit rollback after failure: user={user.user_id}")
            except Exception as rollback_error:
                logger.error(f"CRITICAL: Failed to rollback credit: {rollback_error}")

        idempotency_repo.update_failed(user.user_id, idempotency_key, str(e))
        logger.exception(f"Music orchestration failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Orchestration failed", "message": str(e)},
        )


@router.post(
    "/audio",
    response_model=OrchestrationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Audio to Video",
    description="Generate video from existing audio with subtitles",
)
async def orchestrate_audio(
    request: AudioModeRequest,
    user: User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias=IDEMPOTENCY_KEY_HEADER),
) -> OrchestrationResponse:
    """
    Orchestrate audio-to-video generation.

    Pipeline:
    1. Load audio file
    2. Extract timestamps
    3. Select background visuals
    4. Submit render job with subtitles
    """
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Missing required header",
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": f"{IDEMPOTENCY_KEY_HEADER} header is required",
            },
        )

    if not request.audio_path and not request.audio_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "AUDIO_REQUIRED",
                "message": "Требуется audio_path или audio_url",
            },
        )

    audio_path = request.audio_path
    if not audio_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "AUDIO_PATH_REQUIRED",
                "message": "audio_url не поддерживается. Используйте audio_path.",
            },
        )

    idempotency_repo = get_idempotency_repository()
    request_data = {
        "mode": "audio",
        "audio_path": audio_path,
        "visual_style": request.visual_style,
        "has_transcript": request.transcript_text is not None,
        "resolution": f"{request.resolution.width}x{request.resolution.height}",
    }
    request_hash = _compute_request_hash(request_data)

    existing = idempotency_repo.find_by_key(user.user_id, idempotency_key)
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "Request hash mismatch",
                    "code": "IDEMPOTENCY_HASH_MISMATCH",
                    "message": "Request body differs from original request",
                },
            )

        if existing.status == IdempotencyStatus.COMPLETED:
            return OrchestrationResponse(
                status="queued",
                mode=OrchestrationMode.AUDIO.value,
                task_id=existing.task_id,
                job_id=existing.job_id,
                message="Render job already queued (idempotent response)",
                estimated_duration_seconds=0,
                created_at=existing.created_at,
            )

        if existing.status == IdempotencyStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "Request in progress",
                    "code": "IDEMPOTENCY_PENDING",
                    "message": "A request with this key is already being processed",
                },
            )

        idempotency_repo.delete_failed(user.user_id, idempotency_key)

    try:
        idempotency_repo.create_pending(
            user_id=user.user_id,
            key=idempotency_key,
            request_hash=request_hash,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Concurrent request",
                "code": "IDEMPOTENCY_RACE",
                "message": "Another request with this key is being processed",
            },
        )

    if not _check_redis_connection():
        idempotency_repo.update_failed(user.user_id, idempotency_key, "Service unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "Render queue unavailable", "code": "SERVICE_UNAVAILABLE"},
        )

    credit_service = get_credit_service()
    job_tracker = get_job_tracker()
    credit_deducted = False
    job_id = f"audio_{uuid.uuid4().hex[:12]}"

    try:
        credit_service.deduct_for_render(user, job_id=job_id)
        credit_deducted = True
    except InsufficientCreditsError as e:
        idempotency_repo.update_failed(user.user_id, idempotency_key, "Insufficient credits")
        raise e.to_http_exception()

    try:
        orchestrator = AudioModeOrchestrator()

        orchestration_request = {
            "audio_path": audio_path,
            "style": request.visual_style,
            "transcript_text": request.transcript_text,
            "resolution": {
                "width": request.resolution.width,
                "height": request.resolution.height,
            },
            "fps": request.fps,
            "subtitles": {
                "enabled": request.subtitles.enabled,
                "size": request.subtitles.size,
            },
            "job_id": job_id,
        }

        result = orchestrator.build_render_job(orchestration_request)

        render_kwargs = result.render_job

        task = render_video_task.delay(**render_kwargs)

        job_tracker.track_job(
            task_id=task.id,
            job_id=job_id,
            user_id=user.user_id,
        )

        idempotency_repo.update_completed(
            user_id=user.user_id,
            key=idempotency_key,
            task_id=task.id,
            job_id=job_id,
        )

        logger.info(
            f"Audio orchestration complete: job_id={job_id}, task_id={task.id}, "
            f"user={user.user_id}, duration={result.estimated_duration_seconds:.1f}s, "
            f"scenes={result.metadata.get('scenes_count', 0)}, words={result.metadata.get('words_count', 0)}"
        )

        return OrchestrationResponse(
            status="queued",
            mode=OrchestrationMode.AUDIO.value,
            task_id=task.id,
            job_id=job_id,
            message="Audio video generation queued successfully",
            estimated_duration_seconds=result.estimated_duration_seconds,
            created_at=datetime.utcnow(),
        )

    except ValueError as e:
        if credit_deducted:
            try:
                credit_service.rollback_render_credit(user.user_id, job_id=job_id)
                logger.info(f"Credit rollback for validation error: user={user.user_id}")
            except Exception as rollback_error:
                logger.error(f"Failed to rollback credit: {rollback_error}")

        idempotency_repo.update_failed(user.user_id, idempotency_key, str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "Validation failed", "message": str(e)},
        )

    except FileNotFoundError as e:
        if credit_deducted:
            try:
                credit_service.rollback_render_credit(user.user_id, job_id=job_id)
                logger.info(f"Credit rollback for file not found: user={user.user_id}")
            except Exception as rollback_error:
                logger.error(f"Failed to rollback credit: {rollback_error}")

        idempotency_repo.update_failed(user.user_id, idempotency_key, str(e))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "File not found", "message": str(e)},
        )

    except Exception as e:
        if credit_deducted:
            try:
                credit_service.rollback_render_credit(user.user_id, job_id=job_id)
                logger.info(f"Credit rollback after failure: user={user.user_id}")
            except Exception as rollback_error:
                logger.error(f"CRITICAL: Failed to rollback credit: {rollback_error}")

        idempotency_repo.update_failed(user.user_id, idempotency_key, str(e))
        logger.exception(f"Audio orchestration failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Orchestration failed", "message": str(e)},
        )


@router.post(
    "/long",
    response_model=LongModeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Long Video to Shorts",
    description="Convert long video to multiple short vertical clips",
)
async def orchestrate_long(
    request: LongModeRequest,
    user: User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias=IDEMPOTENCY_KEY_HEADER),
) -> LongModeResponse:
    """
    Orchestrate long video → shorts batch generation.

    Pipeline:
    1. Extract audio from video
    2. Segment video based on silence/content
    3. Crop each segment to vertical 9:16
    4. Generate subtitles for each clip
    5. Submit batch of render jobs
    """
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Missing required header",
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": f"{IDEMPOTENCY_KEY_HEADER} header is required",
            },
        )

    if not request.video_path and not request.video_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "VIDEO_REQUIRED",
                "message": "video_path or video_url is required",
            },
        )

    video_path = request.video_path
    if not video_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "VIDEO_PATH_REQUIRED",
                "message": "video_url not supported. Use video_path.",
            },
        )

    idempotency_repo = get_idempotency_repository()
    request_data = {
        "mode": "long",
        "video_path": video_path,
        "clip_length": request.clip_length,
        "max_clips": request.max_clips,
        "resolution": f"{request.resolution.width}x{request.resolution.height}",
    }
    request_hash = _compute_request_hash(request_data)

    existing = idempotency_repo.find_by_key(user.user_id, idempotency_key)
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "Request hash mismatch",
                    "code": "IDEMPOTENCY_HASH_MISMATCH",
                    "message": "Request body differs from original request",
                },
            )

        if existing.status == IdempotencyStatus.COMPLETED:
            return LongModeResponse(
                status="queued",
                mode=OrchestrationMode.LONG.value,
                batch_id=existing.job_id,
                clips_count=0,
                clips=[],
                task_ids=[existing.task_id] if existing.task_id else [],
                message="Batch already queued (idempotent response)",
                source_duration=0,
                created_at=existing.created_at,
            )

        if existing.status == IdempotencyStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "Request in progress",
                    "code": "IDEMPOTENCY_PENDING",
                    "message": "A request with this key is already being processed",
                },
            )

        idempotency_repo.delete_failed(user.user_id, idempotency_key)

    try:
        idempotency_repo.create_pending(
            user_id=user.user_id,
            key=idempotency_key,
            request_hash=request_hash,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Concurrent request",
                "code": "IDEMPOTENCY_RACE",
                "message": "Another request with this key is being processed",
            },
        )

    if not _check_redis_connection():
        idempotency_repo.update_failed(user.user_id, idempotency_key, "Service unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "Render queue unavailable", "code": "SERVICE_UNAVAILABLE"},
        )

    credit_service = get_credit_service()
    job_tracker = get_job_tracker()
    batch_id = f"batch_{uuid.uuid4().hex[:12]}"

    try:
        orchestrator = LongVideoModeOrchestrator()

        orchestration_request = {
            "video_path": video_path,
            "style": request.visual_style,
            "clip_length": request.clip_length,
            "max_clips": request.max_clips,
            "min_clip_length": request.min_clip_length,
            "max_clip_length": request.max_clip_length,
            "resolution": {
                "width": request.resolution.width,
                "height": request.resolution.height,
            },
            "fps": request.fps,
            "subtitles": {
                "enabled": request.subtitles.enabled,
                "size": request.subtitles.size,
            },
            "batch_id": batch_id,
        }

        result = orchestrator.build_render_job(orchestration_request)

        batch_data = result.render_job
        clips_data = batch_data.get("clips", [])
        clips_count = len(clips_data)

        try:
            credit_service.deduct_for_render(user, job_id=batch_id, amount=clips_count)
        except InsufficientCreditsError as e:
            idempotency_repo.update_failed(user.user_id, idempotency_key, "Insufficient credits")
            raise e.to_http_exception()

        task_ids = []
        for clip_kwargs in clips_data:
            task = render_video_task.delay(**clip_kwargs)
            task_ids.append(task.id)

            job_tracker.track_job(
                task_id=task.id,
                job_id=clip_kwargs["job_id"],
                user_id=user.user_id,
            )

        idempotency_repo.update_completed(
            user_id=user.user_id,
            key=idempotency_key,
            task_id=task_ids[0] if task_ids else "",
            job_id=batch_id,
        )

        clips_info = [
            BatchClipInfo(
                clip_id=clip["clip_id"],
                clip_index=clip["clip_index"],
                start=clip["start"],
                end=clip["end"],
                duration=round(clip["end"] - clip["start"], 3),
            )
            for clip in result.metadata.get("clips", [])
        ]

        logger.info(
            f"Long video orchestration complete: batch_id={batch_id}, "
            f"user={user.user_id}, clips={clips_count}, "
            f"source_duration={result.metadata.get('source_duration', 0):.1f}s"
        )

        return LongModeResponse(
            status="queued",
            mode=OrchestrationMode.LONG.value,
            batch_id=batch_id,
            clips_count=clips_count,
            clips=clips_info,
            task_ids=task_ids,
            message=f"Batch of {clips_count} clips queued successfully",
            source_duration=result.metadata.get("source_duration", 0),
            created_at=datetime.utcnow(),
        )

    except ValueError as e:
        idempotency_repo.update_failed(user.user_id, idempotency_key, str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "Validation failed", "message": str(e)},
        )

    except FileNotFoundError as e:
        idempotency_repo.update_failed(user.user_id, idempotency_key, str(e))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "File not found", "message": str(e)},
        )

    except Exception as e:
        idempotency_repo.update_failed(user.user_id, idempotency_key, str(e))
        logger.exception(f"Long video orchestration failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Orchestration failed", "message": str(e)},
        )
