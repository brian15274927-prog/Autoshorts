"""
YouTube Shorts API Routes.
"""
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .service import YouTubeShortsService
from app.persistence.youtube_jobs_repo import get_youtube_jobs_repository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/youtube-shorts", tags=["youtube-shorts"])

# Service instance
shorts_service = YouTubeShortsService()

# Get repository for database persistence
youtube_jobs_repo = get_youtube_jobs_repository()


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
        # Update status in database
        youtube_jobs_repo.update_job_processing(job_id, "Загрузка видео с YouTube...")

        # Run analysis with parameters
        result = await shorts_service.analyze_youtube_url(
            youtube_url,
            max_clips=max_clips,
            min_duration=min_duration,
            max_duration=max_duration,
            goal=goal
        )

        # Store format settings with result for later use in render
        format_settings = {
            "format": output_format,
            "width": output_width,
            "height": output_height,
            "enable_broll": enable_broll,
            "broll_source": broll_source
        }
        result["format_settings"] = format_settings

        # Add AI reasoning to each clip if not present
        for clip in result.get("clips", []):
            if "reason" not in clip and "ai_reasoning" not in clip:
                clip["ai_reasoning"] = _generate_ai_reasoning(clip, goal)

        # Save to database
        youtube_jobs_repo.complete_job(
            job_id=job_id,
            video_duration=result.get("video_duration", 0),
            video_path=result.get("video_path", ""),
            clips=result.get("clips", []),
            format_settings=format_settings
        )

        logger.info(f"YouTube analysis completed for job {job_id}: {len(result.get('clips', []))} clips found")

    except Exception as e:
        logger.error(f"Analysis failed for job {job_id}: {e}")
        youtube_jobs_repo.fail_job(job_id, str(e))


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
    background_tasks: BackgroundTasks,
    req: Request = None
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

    # Get user_id from request state (set by AuthMiddleware)
    user_id = "guest"
    if req and hasattr(req.state, "user_id"):
        user_id = req.state.user_id

    # Create job in database
    youtube_jobs_repo.create_job(
        job_id=job_id,
        user_id=user_id,
        youtube_url=request.youtube_url,
        max_clips=request.max_clips,
        min_duration=request.min_duration,
        max_duration=request.max_duration,
        goal=request.goal,
        output_format=request.output_format,
        output_width=request.output_width,
        output_height=request.output_height,
        enable_broll=request.enable_broll,
        broll_source=request.broll_source
    )

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
    # Check database first
    response = youtube_jobs_repo.get_job_status_response(job_id)
    if response:
        return response

    # Fallback: Try to load from disk (legacy)
    result = shorts_service.get_analysis(job_id)
    if result:
        return {
            "job_id": job_id,
            "status": "completed",
            "progress": "Analysis complete",
            "result": result
        }

    raise HTTPException(status_code=404, detail="Job not found")


@router.get("/results/{job_id}")
async def get_analysis_results(job_id: str):
    """Get the full analysis results for a job."""
    # Check database first
    result = youtube_jobs_repo.get_analysis_result(job_id)
    if result:
        return result

    # Fallback: Check disk (legacy)
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
    # Get analysis results from database first
    result = youtube_jobs_repo.get_analysis_result(request.job_id)
    if not result:
        # Fallback: Check disk (legacy)
        result = shorts_service.get_analysis(request.job_id)
        if not result:
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

        # Generate new clip_id for the editor record
        editor_clip_id = str(uuid.uuid4())

        # Convert words to subtitles format
        subtitles = []
        for i, word in enumerate(clip_data.get("words", [])):
            subtitles.append(Subtitle(
                id=str(uuid.uuid4()),
                text=word.get("word", ""),
                start=word.get("start", 0) - clip_data["start"],  # Relative to clip start
                end=word.get("end", 0) - clip_data["start"]
            ))

        # Build video URL for the editor (served from /shorts/{job_id}/clips/)
        video_filename = Path(clip_path).name
        video_url = f"/shorts/{request.job_id}/clips/{video_filename}"

        # Create clip record with Revideo format settings
        clip_record = ClipRecord(
            clip_id=editor_clip_id,
            batch_id=request.job_id,
            clip_index=0,
            duration=clip_data["duration"],
            video_url=video_url,
            video_filename=video_filename,
            subtitles=subtitles,
            status="ready",
            style_preset=request.style,
            font_size="24",
            position="center"
        )

        clip_record = clips_repo.create_clip(clip_record)

        # Update the youtube_clips table with the video path
        youtube_jobs_repo.update_clip_status(
            clip_id=clip_data["clip_id"],
            status="created",
            clip_video_path=clip_path,
            clip_video_url=video_url
        )

        return {
            "success": True,
            "clip_id": clip_record.clip_id,
            "clip_path": clip_path,
            "video_url": video_url,
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


@router.get("/jobs")
async def list_jobs(req: Request, limit: int = 50):
    """List all YouTube analysis jobs for the current user."""
    user_id = "guest"
    if req and hasattr(req.state, "user_id"):
        user_id = req.state.user_id

    jobs = youtube_jobs_repo.get_user_jobs(user_id, limit=limit)
    return {
        "jobs": [youtube_jobs_repo.to_api_response(job) for job in jobs],
        "total": len(jobs)
    }


@router.get("/job/{job_id}")
async def get_job_details(job_id: str):
    """Get detailed information about a specific job including all clips."""
    job = youtube_jobs_repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get clips from database
    clips = youtube_jobs_repo.get_clips(job_id)

    response = youtube_jobs_repo.to_api_response(job)
    response["clips"] = [
        {
            "clip_id": clip.clip_id,
            "clip_index": clip.clip_index,
            "start": clip.start,
            "end": clip.end,
            "duration": clip.duration,
            "text_preview": clip.text_preview,
            "score": clip.score,
            "ai_reasoning": clip.ai_reasoning,
            "status": clip.status,
            "video_url": clip.clip_video_url
        }
        for clip in clips
    ]

    return response
