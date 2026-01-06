"""
Clips API Routes.
Provides CRUD operations for clips and subtitles in the editor.
"""
import uuid
import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field

from app.auth.models import User
from app.auth.dependencies import get_current_user, get_current_user_optional
from app.persistence.clips_repo import (
    get_clips_repository,
    ClipRecord,
    Subtitle,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/clips", tags=["Clips"])


# =============================================================================
# Request/Response Models
# =============================================================================

class SubtitleItem(BaseModel):
    """Subtitle item for API."""
    id: str
    start: float
    end: float
    text: str


class ClipListItem(BaseModel):
    """Clip item for list view."""
    clip_id: str
    batch_id: str
    clip_index: int
    duration: float
    status: str
    subtitle_count: int
    thumbnail_url: Optional[str] = None
    video_filename: Optional[str] = None


class ClipDetail(BaseModel):
    """Full clip detail for editor."""
    clip_id: str
    batch_id: str
    clip_index: int
    duration: float
    video_url: Optional[str] = None
    srt_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    video_filename: Optional[str] = None
    subtitles: List[SubtitleItem]
    status: str
    style_preset: str
    font_size: str
    position: str


class UpdateSubtitlesRequest(BaseModel):
    """Request to update subtitles."""
    subtitles: List[SubtitleItem]


class UpdateStyleRequest(BaseModel):
    """Request to update clip style."""
    style_preset: str = Field(default="clean", pattern="^(clean|bold|highlight)$")
    font_size: str = Field(default="M", pattern="^(S|M|L)$")
    position: str = Field(default="center", pattern="^(center|lower)$")


class RenderResponse(BaseModel):
    """Response for render request."""
    task_id: str
    status: str


class TaskStatusResponse(BaseModel):
    """Response for task status check."""
    task_id: str
    status: str
    progress: int = 0
    video_url: Optional[str] = None
    error: Optional[str] = None


# =============================================================================
# Endpoints
# =============================================================================

@router.get("", response_model=List[ClipListItem])
async def list_clips(
    batch_id: str = Query(..., description="Batch ID to filter clips"),
    user: User = Depends(get_current_user_optional),
):
    """List all clips for a batch."""
    repo = get_clips_repository()
    clips = repo.get_clips_by_batch(batch_id)

    return [
        ClipListItem(
            clip_id=clip.clip_id,
            batch_id=clip.batch_id,
            clip_index=clip.clip_index,
            duration=clip.duration,
            status=clip.status,
            subtitle_count=len(clip.subtitles),
            thumbnail_url=clip.thumbnail_url,
            video_filename=clip.video_filename,
        )
        for clip in clips
    ]


@router.get("/{clip_id}", response_model=ClipDetail)
async def get_clip(
    clip_id: str,
    user: User = Depends(get_current_user_optional),
):
    """Get full clip details including subtitles."""
    repo = get_clips_repository()
    clip = repo.get_clip(clip_id)

    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Клип не найден", "clip_id": clip_id}
        )

    return ClipDetail(
        clip_id=clip.clip_id,
        batch_id=clip.batch_id,
        clip_index=clip.clip_index,
        duration=clip.duration,
        video_url=clip.video_url,
        srt_url=clip.srt_url,
        thumbnail_url=clip.thumbnail_url,
        video_filename=clip.video_filename,
        subtitles=[
            SubtitleItem(id=s.id, start=s.start, end=s.end, text=s.text)
            for s in clip.subtitles
        ],
        status=clip.status,
        style_preset=clip.style_preset,
        font_size=clip.font_size,
        position=clip.position,
    )


@router.post("/{clip_id}/subtitles")
async def update_subtitles(
    clip_id: str,
    request: UpdateSubtitlesRequest,
    user: User = Depends(get_current_user_optional),
):
    """Update subtitles for a clip."""
    repo = get_clips_repository()

    # Verify clip exists
    clip = repo.get_clip(clip_id)
    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Клип не найден", "clip_id": clip_id}
        )

    # Convert to internal format
    subtitles = [
        Subtitle(id=s.id, start=s.start, end=s.end, text=s.text)
        for s in request.subtitles
    ]

    repo.update_subtitles(clip_id, subtitles)

    return {"ok": True, "updated_at": datetime.utcnow().isoformat()}


@router.post("/{clip_id}/style")
async def update_style(
    clip_id: str,
    request: UpdateStyleRequest,
    user: User = Depends(get_current_user_optional),
):
    """Update style settings for a clip."""
    repo = get_clips_repository()

    # Verify clip exists
    clip = repo.get_clip(clip_id)
    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Клип не найден", "clip_id": clip_id}
        )

    repo.update_clip_style(
        clip_id,
        request.style_preset,
        request.font_size,
        request.position,
    )

    return {"ok": True}


@router.post("/{clip_id}/render", response_model=RenderResponse)
async def render_clip(
    clip_id: str,
    user: User = Depends(get_current_user),
):
    """Re-render a clip with current subtitles."""
    from app.credits.service import get_credit_service
    from app.credits.exceptions import InsufficientCreditsError
    from app.rendering.tasks import render_video_task
    from app.credits.job_tracker import get_job_tracker

    repo = get_clips_repository()

    # Verify clip exists
    clip = repo.get_clip(clip_id)
    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Клип не найден", "clip_id": clip_id}
        )

    # Check credits
    credit_service = get_credit_service()
    job_id = f"rerender_{clip_id}_{uuid.uuid4().hex[:8]}"

    try:
        credit_service.deduct_for_render(user, job_id=job_id)
    except InsufficientCreditsError as e:
        raise e.to_http_exception()

    # Update clip status
    repo.update_clip_status(clip_id, "rendering")

    # Build render kwargs from clip data
    # Map font size
    font_sizes = {"S": 50, "M": 70, "L": 90}
    subtitle_font_size = font_sizes.get(clip.font_size, 70)

    # Map style preset to colors
    style_colors = {
        "clean": {"color": "white", "active": "white"},
        "bold": {"color": "#FFFFFF", "active": "#FFD700"},
        "highlight": {"color": "#FFFFFF", "active": "#FF6B6B"},
    }
    colors = style_colors.get(clip.style_preset, style_colors["clean"])

    # Build timestamps JSON from subtitles
    words = []
    for sub in clip.subtitles:
        sub_words = sub.text.split()
        if not sub_words:
            continue
        word_duration = (sub.end - sub.start) / len(sub_words)
        current_time = sub.start
        for word in sub_words:
            words.append({
                "word": word,
                "start": round(current_time, 3),
                "end": round(current_time + word_duration, 3),
            })
            current_time += word_duration

    timestamps_json = {
        "words": words,
        "total_duration": clip.duration,
    }

    # Build script JSON
    script_json = {
        "script_id": f"script_{clip_id}",
        "title": f"Клип {clip.clip_index}",
        "scenes": [{
            "scene_id": "scene_1",
            "scene_type": "video",
            "background_path": clip.video_url or "",
            "start_time": 0.0,
            "end_time": clip.duration,
            "text": " ".join(s.text for s in clip.subtitles),
        }],
        "total_duration": clip.duration,
    }

    render_kwargs = {
        "job_id": job_id,
        "script_json": script_json,
        "audio_path": None,
        "timestamps_json": timestamps_json,
        "bgm_path": None,
        "output_dir": None,
        "output_filename": f"clip_{clip.clip_index:02d}_rerender.mp4",
        "generate_srt": True,
        "video_width": 1080,
        "video_height": 1920,
        "fps": 30,
        "video_bitrate": "8M",
        "preset": "medium",
        "bgm_volume_db": 0.0,
        "subtitle_font_size": subtitle_font_size,
        "subtitle_color": colors["color"],
        "subtitle_active_color": colors["active"],
    }

    # Submit task
    task = render_video_task.delay(**render_kwargs)

    # Track job
    job_tracker = get_job_tracker()
    job_tracker.track_job(
        task_id=task.id,
        job_id=job_id,
        user_id=user.user_id,
    )

    logger.info(f"Re-render started: clip_id={clip_id}, task_id={task.id}")

    return RenderResponse(
        task_id=task.id,
        status="queued",
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    user: User = Depends(get_current_user_optional),
):
    """Get status of a render task."""
    from celery.result import AsyncResult
    from app.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)

    status_map = {
        "PENDING": "pending",
        "STARTED": "running",
        "PROGRESS": "running",
        "SUCCESS": "completed",
        "FAILURE": "failed",
        "REVOKED": "failed",
    }

    task_status = status_map.get(result.status, "pending")
    progress = 0
    video_url = None
    error = None

    if result.status == "PROGRESS" and isinstance(result.info, dict):
        progress = result.info.get("progress", 0)
    elif result.status == "SUCCESS":
        progress = 100
        if result.result:
            video_url = result.result.get("output_path")
    elif result.status == "FAILURE":
        error = str(result.result) if result.result else "Неизвестная ошибка"

    return TaskStatusResponse(
        task_id=task_id,
        status=task_status,
        progress=progress,
        video_url=video_url,
        error=error,
    )


# =============================================================================
# Demo Batch Creation
# =============================================================================

@router.post("/demo/create-batch")
async def create_demo_batch(
    user: User = Depends(get_current_user_optional),
):
    """Create a demo batch with sample clips for testing the editor."""
    repo = get_clips_repository()

    batch_id = f"batch_{uuid.uuid4().hex[:8]}"

    # Russian demo content - realistic video subtitles
    demo_content = [
        {
            "title": "Как увеличить продуктивность",
            "subtitles": [
                "Привет! Сегодня поговорим о продуктивности.",
                "Первый совет — начинайте день с самой сложной задачи.",
                "Это называется техника «съешь лягушку».",
                "Когда трудное сделано, остальное кажется легким.",
                "Второй совет — делайте перерывы каждые 25 минут.",
            ]
        },
        {
            "title": "Секреты успешных людей",
            "subtitles": [
                "Все успешные люди имеют одну общую черту.",
                "Они не боятся неудач и учатся на ошибках.",
                "Каждое падение — это шаг к победе.",
                "Важно не сдаваться и идти вперёд.",
                "Помните: ваш успех зависит только от вас.",
            ]
        },
        {
            "title": "Утренние привычки миллионеров",
            "subtitles": [
                "Хотите узнать, как начинают день богатые?",
                "Большинство встаёт в пять утра.",
                "Первый час посвящён медитации и спорту.",
                "Затем идёт планирование ключевых задач.",
                "Эти привычки формируют успех на годы вперёд.",
            ]
        },
    ]

    demo_clips = []
    for i, content in enumerate(demo_content):
        clip_id = f"{batch_id}_clip_{i:02d}"

        # Generate subtitles with proper timing
        subtitles = []
        current_time = 0.0
        for j, text in enumerate(content["subtitles"]):
            duration = 2.8  # Each subtitle ~3 seconds
            subtitles.append(
                Subtitle(
                    id=f"{clip_id}_sub_{j}",
                    start=round(current_time, 2),
                    end=round(current_time + duration, 2),
                    text=text
                )
            )
            current_time += duration + 0.2  # Small gap between subtitles

        clip = ClipRecord(
            clip_id=clip_id,
            batch_id=batch_id,
            clip_index=i,
            duration=round(current_time, 2),
            video_url=None,
            srt_url=None,
            thumbnail_url=None,
            subtitles=subtitles,
            status="ready",
        )

        repo.create_clip(clip)
        demo_clips.append(clip_id)

    return {
        "batch_id": batch_id,
        "clips": demo_clips,
        "editor_url": f"/app/editor/{batch_id}",
    }
