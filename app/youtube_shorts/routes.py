"""
YouTube Shorts API Routes.
"""
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .service import YouTubeShortsService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/youtube-shorts", tags=["youtube-shorts"])

# Service instance
shorts_service = YouTubeShortsService()

# In-memory job status storage
_job_status = {}


class AnalyzeRequest(BaseModel):
    """Request to analyze a YouTube URL with format settings."""
    youtube_url: str
    max_clips: int = 5
    min_duration: float = 15.0
    max_duration: float = 45.0
    goal: str = "viral"  # viral, educational, podcast, dramatic, funny
    output_format: str = "9:16"  # 9:16, 1:1, 16:9
    output_width: int = 1080
    output_height: int = 1920
    enable_broll: bool = False
    broll_source: str = "pexels"  # pexels, pixabay, both


class CreateClipRequest(BaseModel):
    """Request to create a clip with Revideo render settings."""
    job_id: str
    clip_id: str
    format: str = "9:16"  # Connected to Revideo render core
    width: int = 1080
    height: int = 1920
    style: str = "clean"  # clean, bold, neon


class AnalyzeResponse(BaseModel):
    """Response from analyze endpoint."""
    job_id: str
    status: str
    message: str


class ClipInfo(BaseModel):
    """Clip information."""
    clip_id: str
    start: float
    end: float
    duration: float
    text_preview: str
    score: float


class AnalysisResult(BaseModel):
    """Analysis result with clips."""
    job_id: str
    youtube_url: str
    video_duration: float
    clips: list[ClipInfo]
    status: str


async def _run_analysis(
    job_id: str,
    youtube_url: str,
    max_clips: int = 5,
    min_duration: float = 15.0,
    max_duration: float = 45.0,
    goal: str = "viral",
    output_format: str = "9:16",
    output_width: int = 1080,
    output_height: int = 1920,
    enable_broll: bool = False,
    broll_source: str = "pexels"
):
    """Background task to run analysis with Director AI."""
    try:
        _job_status[job_id] = {"status": "processing", "progress": "Загрузка видео с YouTube..."}

        # Run analysis with parameters
        result = await shorts_service.analyze_youtube_url(
            youtube_url,
            max_clips=max_clips,
            min_duration=min_duration,
            max_duration=max_duration,
            goal=goal
        )

        # Store format settings with result for later use in render
        result["format_settings"] = {
            "format": output_format,
            "width": output_width,
            "height": output_height,
            "enable_broll": enable_broll,
            "broll_source": broll_source
        }

        # Add AI reasoning to each clip if not present
        for clip in result.get("clips", []):
            if "reason" not in clip and "ai_reasoning" not in clip:
                clip["ai_reasoning"] = _generate_ai_reasoning(clip, goal)

        _job_status[job_id] = {
            "status": "completed",
            "progress": "Анализ завершён",
            "result": result
        }

    except Exception as e:
        logger.error(f"Analysis failed for job {job_id}: {e}")
        _job_status[job_id] = {
            "status": "failed",
            "progress": str(e),
            "error": str(e)
        }


def _generate_ai_reasoning(clip: dict, goal: str) -> str:
    """Generate AI reasoning explanation for clip selection."""
    score = clip.get("score", 0.7)
    text = clip.get("text_preview", "")[:100]

    reasons = {
        "viral": [
            f"Высокий вирусный потенциал ({int(score*100)}% совпадение). Момент содержит эмоциональный пик.",
            f"Отличный hook для удержания внимания. Score: {int(score*100)}%.",
            f"Director AI определил этот фрагмент как наиболее захватывающий."
        ],
        "educational": [
            f"Ключевая обучающая информация. Ясность изложения: {int(score*100)}%.",
            f"Концентрированное объяснение концепции. Релевантность: {int(score*100)}%."
        ],
        "podcast": [
            f"Яркий момент дискуссии. Вовлечённость: {int(score*100)}%.",
            f"Запоминающаяся цитата или инсайт. Score: {int(score*100)}%."
        ],
        "dramatic": [
            f"Эмоциональный пик повествования. Драматизм: {int(score*100)}%.",
            f"Момент высокого напряжения. Score: {int(score*100)}%."
        ],
        "funny": [
            f"Комедийный момент с высоким потенциалом. Юмор: {int(score*100)}%.",
            f"Забавный фрагмент для мемов. Score: {int(score*100)}%."
        ]
    }

    import random
    goal_reasons = reasons.get(goal, reasons["viral"])
    return random.choice(goal_reasons)


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_youtube_url(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks
):
    """
    Analyze a YouTube URL and find potential short clips using Director AI.

    Accepts format settings that will be used for Revideo render:
    - output_format: 9:16, 1:1, or 16:9
    - output_width/height: Resolution for render
    - goal: viral, educational, podcast, dramatic, funny
    - enable_broll: Auto-add B-Roll footage
    - broll_source: pexels, pixabay, or both

    This starts a background job and returns immediately.
    Poll /status/{job_id} to check progress.
    """
    job_id = str(uuid.uuid4())

    _job_status[job_id] = {
        "status": "pending",
        "progress": "Запуск анализа..."
    }

    # Start background task with all parameters
    background_tasks.add_task(
        _run_analysis,
        job_id,
        request.youtube_url,
        request.max_clips,
        request.min_duration,
        request.max_duration,
        request.goal,
        request.output_format,
        request.output_width,
        request.output_height,
        request.enable_broll,
        request.broll_source
    )

    return AnalyzeResponse(
        job_id=job_id,
        status="pending",
        message="Анализ запущен. Отслеживайте прогресс через /status/{job_id}."
    )


@router.get("/status/{job_id}")
async def get_job_status(job_id: str):
    """Get the status of an analysis job."""
    if job_id not in _job_status:
        # Try to load from disk
        result = shorts_service.get_analysis(job_id)
        if result:
            return {
                "job_id": job_id,
                "status": "completed",
                "progress": "Analysis complete",
                "result": result
            }
        raise HTTPException(status_code=404, detail="Job not found")

    status = _job_status[job_id]
    return {
        "job_id": job_id,
        **status
    }


@router.get("/results/{job_id}")
async def get_analysis_results(job_id: str):
    """Get the full analysis results for a job."""
    # Check in-memory first
    if job_id in _job_status and _job_status[job_id].get("status") == "completed":
        return _job_status[job_id].get("result")

    # Check disk
    result = shorts_service.get_analysis(job_id)
    if result:
        return result

    raise HTTPException(status_code=404, detail="Analysis results not found")


@router.post("/create-clip")
async def create_clip(request: CreateClipRequest):
    """
    Create a video clip from analysis results.

    Uses format settings connected to Revideo render core:
    - format: 9:16, 1:1, or 16:9
    - width/height: Output resolution
    - style: clean, bold, or neon subtitle style

    Returns the clip information that can be opened in the Editor.
    """
    # Get analysis results
    result = shorts_service.get_analysis(request.job_id)
    if not result:
        # Check in-memory status
        if request.job_id in _job_status and _job_status[request.job_id].get("status") == "completed":
            result = _job_status[request.job_id].get("result")
        else:
            raise HTTPException(status_code=404, detail="Analysis not found")

    # Find the clip
    clip_data = None
    for clip in result.get("clips", []):
        if clip["clip_id"] == request.clip_id:
            clip_data = clip
            break

    if not clip_data:
        raise HTTPException(status_code=404, detail="Clip not found")

    try:
        # Extract the clip video
        from .service import ShortClip

        clip = ShortClip(
            clip_id=clip_data["clip_id"],
            start=clip_data["start"],
            end=clip_data["end"],
            duration=clip_data["duration"],
            text_preview=clip_data["text_preview"],
            words=clip_data.get("words", []),
            score=clip_data.get("score", 0)
        )

        clip_path = await shorts_service.create_clip_video(
            request.job_id,
            clip,
            result["video_path"]
        )

        # Create a clip record in the database for the Editor
        from app.persistence.clips_repo import get_clips_repository, ClipRecord, Subtitle
        clips_repo = get_clips_repository()

        # Convert words to subtitles format
        subtitles = []
        for i, word in enumerate(clip_data.get("words", [])):
            subtitles.append(Subtitle(
                id=str(uuid.uuid4()),
                text=word.get("word", ""),
                start=word.get("start", 0) - clip_data["start"],  # Relative to clip start
                end=word.get("end", 0) - clip_data["start"]
            ))

        # Create clip record with Revideo format settings
        clip_record = ClipRecord(
            clip_id=str(uuid.uuid4()),
            batch_id=request.job_id,
            clip_index=0,
            duration=clip_data["duration"],
            video_filename=Path(clip_path).name,
            subtitles=subtitles,
            status="ready",
            style_preset=request.style,
            font_size="24",
            position="center"
        )

        clip_record = clips_repo.create_clip(clip_record)

        return {
            "success": True,
            "clip_id": clip_record.clip_id,
            "clip_path": clip_path,
            "duration": clip_data["duration"],
            "format": request.format,
            "width": request.width,
            "height": request.height,
            "style": request.style,
            "ai_reasoning": clip_data.get("ai_reasoning", ""),
            "score": clip_data.get("score", 0),
            "editor_url": f"/app/editor/{clip_record.clip_id}"
        }

    except Exception as e:
        logger.error(f"Failed to create clip: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/clip-video/{job_id}/{clip_id}")
async def get_clip_video(job_id: str, clip_id: str):
    """Get the video file for a clip."""
    from .service import SHORTS_DIR

    clip_path = SHORTS_DIR / job_id / "clips" / f"{clip_id}.mp4"

    if not clip_path.exists():
        raise HTTPException(status_code=404, detail="Clip video not found")

    return FileResponse(
        clip_path,
        media_type="video/mp4",
        filename=f"short-{clip_id}.mp4"
    )


@router.get("/source-video/{job_id}")
async def get_source_video(job_id: str):
    """Get the original downloaded video."""
    from .service import SHORTS_DIR

    video_path = SHORTS_DIR / job_id / "video.mp4"

    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Source video not found")

    return FileResponse(
        video_path,
        media_type="video/mp4",
        filename=f"source-{job_id}.mp4"
    )
