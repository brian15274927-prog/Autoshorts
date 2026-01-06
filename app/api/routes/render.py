"""
Render endpoints.
With authentication, credit checking, and idempotency.
"""
import os
import uuid
import logging
from datetime import datetime
from typing import Optional
import sqlite3

from fastapi import APIRouter, Depends, status, Query, HTTPException, Header
from celery.result import AsyncResult

from ..schemas import (
    RenderRequest,
    RenderResponse,
    RenderStatusResponse,
    RenderResultResponse,
    CancelResponse,
    TaskStatus,
    ProgressInfo,
    CostBreakdown,
    UsageMetricsResponse,
    EstimateCostRequest,
    EstimateCostResponse,
)
from ..exceptions import (
    InternalError,
    ServiceUnavailableError,
    ValidationError,
)
from ..dependencies import get_cost_calculator, check_redis_connection

from app.auth.models import User
from app.auth.dependencies import get_current_user
from app.credits.service import get_credit_service
from app.credits.job_tracker import get_job_tracker
from app.credits.exceptions import InsufficientCreditsError, JobNotOwnedError

from app.persistence.idempotency_repo import (
    get_idempotency_repository,
    IdempotencyRepository,
    IdempotencyStatus,
)

from app.rendering.tasks import render_video_task
from app.celery_app import celery_app

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/render", tags=["Render"])


def _validate_render_request(request: RenderRequest) -> None:
    """
    Fail-fast validation for render request.
    Raises HTTPException 422 for empty lists, 400 for missing files.
    """
    if not request.script.scenes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Validation failed",
                "code": "EMPTY_SCENES",
                "message": "scenes list cannot be empty",
            },
        )

    if not request.timestamps.words:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Validation failed",
                "code": "EMPTY_WORDS",
                "message": "timestamps.words list cannot be empty",
            },
        )

    if not os.path.exists(request.audio_path):
        raise ValidationError(
            message="Audio file not found",
            detail=f"File does not exist: {request.audio_path}",
        )


def _map_celery_status(celery_status: str) -> TaskStatus:
    """Map Celery status to API TaskStatus."""
    mapping = {
        "PENDING": TaskStatus.PENDING,
        "STARTED": TaskStatus.STARTED,
        "PROGRESS": TaskStatus.PROGRESS,
        "SUCCESS": TaskStatus.SUCCESS,
        "FAILURE": TaskStatus.FAILURE,
        "REVOKED": TaskStatus.REVOKED,
    }
    return mapping.get(celery_status, TaskStatus.PENDING)


def _parse_progress(info: dict) -> Optional[ProgressInfo]:
    """Parse Celery task info to ProgressInfo."""
    if not info or not isinstance(info, dict):
        return None

    return ProgressInfo(
        stage=info.get("stage", "unknown"),
        progress=info.get("progress", 0),
        current_scene=info.get("current_scene"),
        total_scenes=info.get("total_scenes"),
        message=info.get("message", ""),
    )


def _compute_request_hash(request: RenderRequest) -> str:
    """Compute hash of render request for idempotency conflict detection."""
    repo = get_idempotency_repository()
    request_data = {
        "script_id": request.script.script_id,
        "audio_path": request.audio_path,
        "bgm_path": request.bgm_path,
        "scenes_count": len(request.script.scenes),
        "words_count": len(request.timestamps.words),
        "settings": {
            "video_width": request.settings.video_width,
            "video_height": request.settings.video_height,
            "fps": request.settings.fps,
        },
    }
    return repo.compute_request_hash(request_data)


def _parse_result(result: dict) -> Optional[RenderResultResponse]:
    """Parse Celery result to RenderResultResponse."""
    if not result or not isinstance(result, dict):
        return None

    cost_breakdown = None
    if result.get("cost_breakdown"):
        cost_breakdown = CostBreakdown(**result["cost_breakdown"])

    usage_metrics = None
    if result.get("usage_metrics"):
        usage_metrics = UsageMetricsResponse(**result["usage_metrics"])

    return RenderResultResponse(
        job_id=result.get("job_id", ""),
        success=result.get("success", False),
        output_path=result.get("output_path"),
        srt_path=result.get("srt_path"),
        duration_seconds=result.get("duration_seconds", 0),
        file_size_mb=result.get("file_size_mb"),
        error=result.get("error"),
        video_duration_seconds=result.get("video_duration_seconds"),
        scenes_count=result.get("scenes_count"),
        resolution=result.get("resolution"),
        fps=result.get("fps"),
        cost_usd=result.get("cost_usd"),
        cost_breakdown=cost_breakdown,
        usage_metrics=usage_metrics,
    )


@router.post(
    "",
    response_model=RenderResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create Render Job",
    description="Submit a new video render job to the queue. Requires Idempotency-Key header.",
)
async def create_render(
    request: RenderRequest,
    user: User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias=IDEMPOTENCY_KEY_HEADER),
) -> RenderResponse:
    """
    Create a new render job with idempotency protection.

    - Requires Idempotency-Key header (400 if missing)
    - Returns cached response for duplicate keys
    - Validates request (scenes, words, audio_path)
    - Checks and deducts 1 credit
    - Submits task to Celery queue
    - Tracks job ownership
    - Rolls back credit if task submission fails
    """
    # Step 1: Require Idempotency-Key header
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Missing required header",
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": f"{IDEMPOTENCY_KEY_HEADER} header is required for render requests",
            },
        )

    idempotency_repo = get_idempotency_repository()
    request_hash = _compute_request_hash(request)

    # Step 2: Check for existing idempotency record
    existing = idempotency_repo.find_by_key(user.user_id, idempotency_key)

    if existing:
        # Step 3: Check hash mismatch for ALL statuses (security: prevent key reuse with different body)
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "Request hash mismatch",
                    "code": "IDEMPOTENCY_HASH_MISMATCH",
                    "message": f"Request body differs from original request with this {IDEMPOTENCY_KEY_HEADER}",
                },
            )

        # Step 4: Handle existing record based on status
        if existing.status == IdempotencyStatus.COMPLETED:
            # Return cached response - no double charge
            logger.info(
                f"Idempotency hit: returning cached response for key={idempotency_key}, "
                f"user={user.user_id}, task_id={existing.task_id}"
            )
            return RenderResponse(
                task_id=existing.task_id,
                job_id=existing.job_id,
                status=TaskStatus.QUEUED,
                message="Render job already queued (idempotent response)",
                created_at=existing.created_at,
            )

        if existing.status == IdempotencyStatus.PENDING:
            # Request in progress - conflict
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "Request in progress",
                    "code": "IDEMPOTENCY_PENDING",
                    "message": f"A request with this {IDEMPOTENCY_KEY_HEADER} is already being processed",
                },
            )

        # Status is FAILED - delete to allow retry (hash already verified above)
        idempotency_repo.delete_failed(user.user_id, idempotency_key)

    # Step 4: Create pending idempotency record
    try:
        idempotency_repo.create_pending(
            user_id=user.user_id,
            key=idempotency_key,
            request_hash=request_hash,
        )
    except sqlite3.IntegrityError:
        # Race condition - another request just created the record
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Concurrent request",
                "code": "IDEMPOTENCY_RACE",
                "message": "Another request with this key is being processed concurrently",
            },
        )

    # Step 5: Validate request - mark FAILED if validation fails to avoid PENDING forever
    try:
        _validate_render_request(request)
    except HTTPException as e:
        idempotency_repo.update_failed(
            user.user_id, idempotency_key,
            f"Validation failed: {e.detail.get('code', 'UNKNOWN') if isinstance(e.detail, dict) else str(e.detail)}"
        )
        raise

    if not check_redis_connection():
        idempotency_repo.update_failed(user.user_id, idempotency_key, "Service unavailable")
        raise ServiceUnavailableError("Render queue")

    credit_service = get_credit_service()
    job_tracker = get_job_tracker()

    credit_deducted = False
    job_id = request.job_id or f"job_{uuid.uuid4().hex[:12]}"

    # Step 6: Deduct credit
    try:
        credit_service.deduct_for_render(user, job_id=job_id)
        credit_deducted = True
    except InsufficientCreditsError as e:
        idempotency_repo.update_failed(user.user_id, idempotency_key, "Insufficient credits")
        raise e.to_http_exception()

    script_json = {
        "script_id": request.script.script_id,
        "title": request.script.title,
        "total_duration": request.script.total_duration,
        "scenes": [
            {
                "scene_id": scene.scene_id,
                "scene_type": scene.scene_type,
                "background_path": scene.background_path,
                "start_time": scene.start_time,
                "end_time": scene.end_time,
                "text": scene.text,
                "transition_in": scene.transition_in,
                "transition_duration": scene.transition_duration,
            }
            for scene in request.script.scenes
        ],
    }

    timestamps_json = {
        "total_duration": request.timestamps.total_duration,
        "words": [
            {
                "word": word.word,
                "start": word.start,
                "end": word.end,
            }
            for word in request.timestamps.words
        ],
    }

    # Step 7: Submit task to Celery
    try:
        task = render_video_task.delay(
            job_id=job_id,
            script_json=script_json,
            audio_path=request.audio_path,
            timestamps_json=timestamps_json,
            bgm_path=request.bgm_path,
            output_dir=request.output_dir,
            output_filename=request.output_filename,
            generate_srt=request.settings.generate_srt,
            video_width=request.settings.video_width,
            video_height=request.settings.video_height,
            fps=request.settings.fps,
            video_bitrate=request.settings.video_bitrate,
            preset=request.settings.preset,
            bgm_volume_db=request.settings.bgm_volume_db,
            subtitle_font_size=request.settings.subtitle_font_size,
            subtitle_color=request.settings.subtitle_color,
            subtitle_active_color=request.settings.subtitle_active_color,
        )

        job_tracker.track_job(
            task_id=task.id,
            job_id=job_id,
            user_id=user.user_id,
        )

        # Step 8: Mark idempotency as completed
        idempotency_repo.update_completed(
            user_id=user.user_id,
            key=idempotency_key,
            task_id=task.id,
            job_id=job_id,
        )

        logger.info(
            f"Render job created: job_id={job_id}, task_id={task.id}, "
            f"user={user.user_id}, idempotency_key={idempotency_key}, "
            f"credits_remaining={user.credits_display}"
        )

        return RenderResponse(
            task_id=task.id,
            job_id=job_id,
            status=TaskStatus.QUEUED,
            message="Render job queued successfully",
            created_at=datetime.utcnow(),
        )

    except Exception as e:
        # Rollback credit if deducted
        if credit_deducted:
            try:
                credit_service.rollback_render_credit(user.user_id, job_id=job_id)
                logger.info(
                    f"Credit rollback: restored 1 credit to user {user.user_id} "
                    f"after task submission failure, job_id={job_id}"
                )
            except Exception as rollback_error:
                logger.error(
                    f"CRITICAL: Failed to rollback credit for user {user.user_id}: "
                    f"{rollback_error}"
                )

        # Mark idempotency as failed
        idempotency_repo.update_failed(user.user_id, idempotency_key, str(e))

        logger.exception(f"Failed to create render job: {e}")
        raise InternalError("Failed to queue render job", detail=str(e))


@router.get(
    "/{task_id}",
    response_model=RenderStatusResponse,
    summary="Get Render Status",
    description="Get current status and result of a render job. Only accessible by owner.",
)
async def get_render_status(
    task_id: str,
    user: User = Depends(get_current_user),
) -> RenderStatusResponse:
    """
    Get render job status.

    - Only the job owner can access
    - Returns current status, progress, or result
    """
    job_tracker = get_job_tracker()

    if not job_tracker.is_owner(task_id, user.user_id):
        raise JobNotOwnedError(user.user_id, task_id).to_http_exception()

    result = AsyncResult(task_id, app=celery_app)

    celery_status = result.status
    api_status = _map_celery_status(celery_status)

    response = RenderStatusResponse(
        task_id=task_id,
        status=api_status,
    )

    if celery_status == "PROGRESS":
        response.progress = _parse_progress(result.info)
        if result.info:
            response.job_id = result.info.get("job_id")

    elif celery_status == "SUCCESS":
        response.result = _parse_result(result.result)
        if response.result:
            response.job_id = response.result.job_id

    elif celery_status == "FAILURE":
        response.error = str(result.result) if result.result else "Unknown error"

    return response


@router.post(
    "/{task_id}/cancel",
    response_model=CancelResponse,
    summary="Cancel Render Job",
    description="Cancel a pending or running render job. Only accessible by owner.",
)
async def cancel_render(
    task_id: str,
    user: User = Depends(get_current_user),
) -> CancelResponse:
    """
    Cancel a render job.

    - Only the job owner can cancel
    - Sends revoke signal to Celery
    """
    job_tracker = get_job_tracker()

    if not job_tracker.is_owner(task_id, user.user_id):
        raise JobNotOwnedError(user.user_id, task_id).to_http_exception()

    result = AsyncResult(task_id, app=celery_app)

    if result.ready():
        return CancelResponse(
            task_id=task_id,
            cancelled=False,
            message="Task already completed, cannot cancel",
        )

    try:
        celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")

        logger.info(f"Render job cancelled: task_id={task_id}, user={user.user_id}")

        return CancelResponse(
            task_id=task_id,
            cancelled=True,
            message="Cancellation signal sent",
        )

    except Exception as e:
        logger.exception(f"Failed to cancel task {task_id}: {e}")
        raise InternalError("Failed to cancel task", detail=str(e))


@router.post(
    "/estimate-cost",
    response_model=EstimateCostResponse,
    summary="Estimate Render Cost",
    description="Estimate cost before rendering.",
)
async def estimate_cost(
    request: EstimateCostRequest,
    user: User = Depends(get_current_user),
) -> EstimateCostResponse:
    """
    Estimate render cost based on video parameters.
    """
    cost_calc = get_cost_calculator()

    estimate = cost_calc.estimate(
        video_duration_seconds=request.video_duration_seconds,
        width=request.width,
        height=request.height,
        fps=request.fps,
        complexity_factor=request.complexity_factor,
    )

    return EstimateCostResponse(
        estimated_cost_usd=estimate.total_cost_usd,
        breakdown=CostBreakdown(
            cpu_cost_usd=estimate.cpu_cost_usd,
            storage_cost_usd=estimate.storage_cost_usd,
            gpu_cost_usd=estimate.gpu_cost_usd,
            bandwidth_cost_usd=estimate.bandwidth_cost_usd,
            total_cost_usd=estimate.total_cost_usd,
            cost_per_second_video=estimate.cost_per_second_video,
            cost_per_frame=estimate.cost_per_frame,
        ),
        video_duration_seconds=request.video_duration_seconds,
        resolution=f"{request.width}x{request.height}",
    )


@router.get(
    "",
    summary="List User's Render Jobs",
    description="List render jobs for the authenticated user.",
)
async def list_renders(
    limit: int = Query(default=10, ge=1, le=100),
    user: User = Depends(get_current_user),
) -> dict:
    """
    List render jobs for current user.
    """
    job_tracker = get_job_tracker()
    jobs = job_tracker.get_user_jobs(user.user_id)

    job_list = []
    for job_record in jobs[-limit:]:
        result = AsyncResult(job_record.task_id, app=celery_app)
        job_list.append({
            "task_id": job_record.task_id,
            "job_id": job_record.job_id,
            "status": _map_celery_status(result.status).value,
            "created_at": job_record.created_at.isoformat(),
        })

    return {
        "jobs": job_list,
        "total": len(jobs),
        "limit": limit,
        "user_id": user.user_id,
        "credits_remaining": user.credits_display,
    }


@router.get(
    "/me/credits",
    summary="Get User Credits",
    description="Get current user's credit balance.",
)
async def get_my_credits(
    user: User = Depends(get_current_user),
) -> dict:
    """
    Get current user's credits and plan info.
    """
    return {
        "user_id": user.user_id,
        "credits": user.credits_display,
        "credits_raw": user.credits if not user.has_unlimited_credits else -1,
        "plan": user.plan.value,
        "can_render": user.can_render,
    }
