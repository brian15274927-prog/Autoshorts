"""
Video Engine Routes - Revideo Integration
Full video composition and rendering API using Revideo Node.js engine.
"""
import uuid
import logging
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, status, Depends, Query, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.auth.models import User
from app.auth.dependencies import get_current_user, get_current_user_optional
from app.persistence.clips_repo import get_clips_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/video", tags=["Video Engine"])


# =============================================================================
# Request/Response Models
# =============================================================================

class SubtitleInput(BaseModel):
    """Subtitle input for video composition."""
    id: Optional[str] = None
    text: str
    start: float
    end: float
    words: Optional[List[Dict[str, Any]]] = None


class ClipInput(BaseModel):
    """Clip input for video composition."""
    id: Optional[str] = None
    type: str = Field(default="video", pattern="^(video|image|color)$")
    src: Optional[str] = None
    color: Optional[str] = None
    start: float = 0.0
    end: float = 10.0
    position: Optional[Dict[str, int]] = None
    size: Optional[Dict[str, Any]] = None
    opacity: float = 1.0
    rotation: float = 0.0
    z_index: int = 0


class StyleInput(BaseModel):
    """Subtitle style input."""
    font_family: str = "Arial Black"
    font_size: int = 72
    font_weight: int = 900
    color: str = "#FFFFFF"
    background_color: Optional[str] = "#000000CC"
    background_padding: int = 16
    border_radius: int = 8
    text_align: str = "center"
    position: str = "center"
    offset_y: int = 0
    highlight_color: Optional[str] = "#FFFF00"
    animation_type: str = "pop"
    animation_duration: float = 0.3


class VideoComposeRequest(BaseModel):
    """Request to compose a video from spec."""
    id: Optional[str] = None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    duration: float = 10.0
    background: str = "#000000"
    clips: List[ClipInput] = Field(default_factory=list)
    subtitles: List[SubtitleInput] = Field(default_factory=list)
    style: Optional[StyleInput] = None
    template: Optional[str] = None


class QuickRenderRequest(BaseModel):
    """Quick render request for subtitles on video."""
    video_src: str
    subtitles: List[SubtitleInput]
    template: str = "shorts-vertical"
    output_path: Optional[str] = None


class RenderFromClipRequest(BaseModel):
    """Render request using clip data."""
    clip_id: str
    style: Optional[StyleInput] = None
    template: Optional[str] = None


class VideoJobResponse(BaseModel):
    """Response for video job creation."""
    job_id: str
    status: str
    message: str
    created_at: datetime


class VideoJobStatus(BaseModel):
    """Video job status response."""
    job_id: str
    status: str
    progress: int = 0
    output_path: Optional[str] = None
    duration: Optional[float] = None
    frames: Optional[int] = None
    render_time: Optional[float] = None
    error: Optional[str] = None


class TemplateInfo(BaseModel):
    """Template information."""
    type: str
    width: int
    height: int
    fps: int
    subtitle_style: Dict[str, Any]


# =============================================================================
# In-memory job storage (for simplicity; use Redis in production)
# =============================================================================

_video_jobs: Dict[str, Dict[str, Any]] = {}


def _create_job_record(job_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Create a new job record."""
    job = {
        "job_id": job_id,
        "user_id": user_id,
        "status": "pending",
        "progress": 0,
        "created_at": datetime.utcnow(),
        "started_at": None,
        "completed_at": None,
        "output_path": None,
        "duration": None,
        "frames": None,
        "render_time": None,
        "error": None,
    }
    _video_jobs[job_id] = job
    return job


def _update_job(job_id: str, **kwargs):
    """Update job record."""
    if job_id in _video_jobs:
        _video_jobs[job_id].update(kwargs)


def _get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get job record."""
    return _video_jobs.get(job_id)


# =============================================================================
# Background render task
# =============================================================================

async def _run_revideo_render(
    job_id: str,
    spec_dict: Dict[str, Any],
    options: Dict[str, Any],
    template: Optional[str] = None
):
    """Run Revideo render in background."""
    from app.video_engine.client import (
        RevideoClient, VideoSpec, ClipSpec, SubtitleSpec,
        SubtitleStyle, SubtitleAnimation, RenderOptions,
        TemplateType, QualityLevel, AnimationType
    )

    _update_job(job_id, status="processing", started_at=datetime.utcnow(), progress=10)

    try:
        # Build VideoSpec from dict
        clips = []
        for clip_data in spec_dict.get("clips", []):
            clips.append(ClipSpec(
                id=clip_data.get("id", f"clip_{uuid.uuid4().hex[:8]}"),
                type=clip_data.get("type", "video"),
                start=clip_data.get("start", 0.0),
                end=clip_data.get("end", 10.0),
                src=clip_data.get("src"),
                color=clip_data.get("color"),
                position=clip_data.get("position"),
                size=clip_data.get("size"),
                opacity=clip_data.get("opacity", 1.0),
                rotation=clip_data.get("rotation", 0.0),
                z_index=clip_data.get("z_index", 0),
            ))

        subtitles = []
        style_data = spec_dict.get("style", {})
        for sub_data in spec_dict.get("subtitles", []):
            style = SubtitleStyle(
                font_family=style_data.get("font_family", "Arial Black"),
                font_size=style_data.get("font_size", 72),
                font_weight=style_data.get("font_weight", 900),
                color=style_data.get("color", "#FFFFFF"),
                background_color=style_data.get("background_color", "#000000CC"),
                background_padding=style_data.get("background_padding", 16),
                border_radius=style_data.get("border_radius", 8),
                text_align=style_data.get("text_align", "center"),
                position=style_data.get("position", "center"),
                offset_y=style_data.get("offset_y", 0),
                highlight_color=style_data.get("highlight_color", "#FFFF00"),
            )
            animation = SubtitleAnimation(
                type=AnimationType(style_data.get("animation_type", "pop")),
                duration=style_data.get("animation_duration", 0.3),
            )
            subtitles.append(SubtitleSpec(
                id=sub_data.get("id", f"sub_{uuid.uuid4().hex[:8]}"),
                text=sub_data.get("text", ""),
                start=sub_data.get("start", 0.0),
                end=sub_data.get("end", 1.0),
                style=style,
                animation=animation,
            ))

        spec = VideoSpec(
            id=spec_dict.get("id", f"video_{uuid.uuid4().hex[:8]}"),
            width=spec_dict.get("width", 1080),
            height=spec_dict.get("height", 1920),
            fps=spec_dict.get("fps", 30),
            duration=spec_dict.get("duration", 10.0),
            background=spec_dict.get("background", "#000000"),
            clips=clips,
            subtitles=subtitles,
        )

        # Build render options
        render_options = RenderOptions(
            quality=QualityLevel(options.get("quality", "production")),
            format=options.get("format", "mp4"),
            output_path=options.get("output_path"),
        )

        # Parse template
        template_type = None
        if template:
            try:
                template_type = TemplateType(template)
            except ValueError:
                template_type = TemplateType.SHORTS_VERTICAL

        _update_job(job_id, progress=20)

        # Run render
        async with RevideoClient(auto_start_server=True) as client:
            _update_job(job_id, progress=30)

            result = await client.render_sync(spec, render_options, template_type)

            if result.success:
                _update_job(
                    job_id,
                    status="completed",
                    progress=100,
                    completed_at=datetime.utcnow(),
                    output_path=result.output_path,
                    duration=result.duration,
                    frames=result.frames,
                    render_time=result.render_time,
                )
                logger.info(f"Video render completed: job_id={job_id}, path={result.output_path}")
            else:
                _update_job(
                    job_id,
                    status="failed",
                    progress=0,
                    completed_at=datetime.utcnow(),
                    error=result.error,
                )
                logger.error(f"Video render failed: job_id={job_id}, error={result.error}")

    except Exception as e:
        logger.exception(f"Video render error: job_id={job_id}, error={e}")
        _update_job(
            job_id,
            status="failed",
            progress=0,
            completed_at=datetime.utcnow(),
            error=str(e),
        )


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/health")
async def video_engine_health():
    """Check Revideo engine health."""
    from app.video_engine.client import RevideoClient

    try:
        async with RevideoClient(auto_start_server=False) as client:
            if await client.is_server_running():
                health = await client.health()
                return {
                    "status": "ok",
                    "revideo_server": "running",
                    "details": health,
                }
            else:
                return {
                    "status": "offline",
                    "revideo_server": "not_running",
                    "message": "Revideo server is not running. It will auto-start on first render.",
                }
    except Exception as e:
        return {
            "status": "error",
            "revideo_server": "error",
            "error": str(e),
        }


@router.get("/templates", response_model=Dict[str, TemplateInfo])
async def get_templates():
    """Get available video templates."""
    from app.video_engine.client import RevideoClient

    try:
        async with RevideoClient(auto_start_server=True) as client:
            templates = await client.get_templates()
            return {
                name: TemplateInfo(
                    type=t.get("type", name),
                    width=t.get("width", 1080),
                    height=t.get("height", 1920),
                    fps=t.get("fps", 30),
                    subtitle_style=t.get("subtitleStyle", {}),
                )
                for name, t in templates.items()
            }
    except Exception as e:
        logger.error(f"Failed to get templates: {e}")
        # Return hardcoded templates as fallback
        return {
            "shorts-vertical": TemplateInfo(
                type="shorts-vertical",
                width=1080,
                height=1920,
                fps=30,
                subtitle_style={"fontFamily": "Arial Black", "fontSize": 72},
            ),
            "tiktok": TemplateInfo(
                type="tiktok",
                width=1080,
                height=1920,
                fps=30,
                subtitle_style={"fontFamily": "Montserrat", "fontSize": 64},
            ),
            "youtube-landscape": TemplateInfo(
                type="youtube-landscape",
                width=1920,
                height=1080,
                fps=30,
                subtitle_style={"fontFamily": "Roboto", "fontSize": 48},
            ),
            "instagram-square": TemplateInfo(
                type="instagram-square",
                width=1080,
                height=1080,
                fps=30,
                subtitle_style={"fontFamily": "Helvetica", "fontSize": 56},
            ),
        }


@router.post("/compose", response_model=VideoJobResponse)
async def compose_video(
    request: VideoComposeRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user_optional),
):
    """Compose and render video from spec."""
    job_id = f"video_{uuid.uuid4().hex[:12]}"
    user_id = user.user_id if user else None

    _create_job_record(job_id, user_id)

    # Build spec dict
    spec_dict = {
        "id": request.id or job_id,
        "width": request.width,
        "height": request.height,
        "fps": request.fps,
        "duration": request.duration,
        "background": request.background,
        "clips": [clip.model_dump() for clip in request.clips],
        "subtitles": [sub.model_dump() for sub in request.subtitles],
        "style": request.style.model_dump() if request.style else {},
    }

    options = {
        "quality": "production",
        "format": "mp4",
    }

    # Run render in background
    background_tasks.add_task(
        asyncio.create_task,
        _run_revideo_render(job_id, spec_dict, options, request.template)
    )

    return VideoJobResponse(
        job_id=job_id,
        status="pending",
        message="Video composition job created",
        created_at=datetime.utcnow(),
    )


@router.post("/quick-render", response_model=VideoJobResponse)
async def quick_render(
    request: QuickRenderRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user_optional),
):
    """Quick render subtitles on existing video."""
    from app.video_engine.client import RevideoClient, TemplateType

    job_id = f"quick_{uuid.uuid4().hex[:12]}"
    user_id = user.user_id if user else None

    _create_job_record(job_id, user_id)

    async def _quick_render_task():
        _update_job(job_id, status="processing", started_at=datetime.utcnow(), progress=10)

        try:
            template_type = TemplateType.SHORTS_VERTICAL
            try:
                template_type = TemplateType(request.template)
            except ValueError:
                pass

            subtitles = [
                {"text": s.text, "start": s.start, "end": s.end}
                for s in request.subtitles
            ]

            async with RevideoClient(auto_start_server=True) as client:
                _update_job(job_id, progress=30)

                result = await client.render_subtitles_video(
                    video_src=request.video_src,
                    subtitles=subtitles,
                    template=template_type,
                    output_path=request.output_path,
                )

                if result.success:
                    _update_job(
                        job_id,
                        status="completed",
                        progress=100,
                        completed_at=datetime.utcnow(),
                        output_path=result.output_path,
                        duration=result.duration,
                        frames=result.frames,
                        render_time=result.render_time,
                    )
                else:
                    _update_job(
                        job_id,
                        status="failed",
                        completed_at=datetime.utcnow(),
                        error=result.error,
                    )

        except Exception as e:
            logger.exception(f"Quick render error: {e}")
            _update_job(
                job_id,
                status="failed",
                completed_at=datetime.utcnow(),
                error=str(e),
            )

    background_tasks.add_task(asyncio.create_task, _quick_render_task())

    return VideoJobResponse(
        job_id=job_id,
        status="pending",
        message="Quick render job created",
        created_at=datetime.utcnow(),
    )


@router.post("/render-clip", response_model=VideoJobResponse)
async def render_from_clip(
    request: RenderFromClipRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    """Render video from existing clip data."""
    from app.credits.service import get_credit_service
    from app.credits.exceptions import InsufficientCreditsError

    # Get clip data
    repo = get_clips_repository()
    clip = repo.get_clip(request.clip_id)

    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Clip not found", "clip_id": request.clip_id}
        )

    # Check credits
    credit_service = get_credit_service()
    job_id = f"clip_render_{uuid.uuid4().hex[:12]}"

    try:
        credit_service.deduct_for_render(user, job_id=job_id)
    except InsufficientCreditsError as e:
        raise e.to_http_exception()

    # Update clip status
    repo.update_clip_status(request.clip_id, "rendering")

    _create_job_record(job_id, user.user_id)

    # Build spec from clip
    style = request.style or StyleInput()

    # Map clip style presets
    if clip.style_preset == "bold":
        style.highlight_color = "#FFD700"
    elif clip.style_preset == "highlight":
        style.highlight_color = "#FF6B6B"

    font_size_map = {"S": 50, "M": 70, "L": 90}
    style.font_size = font_size_map.get(clip.font_size, 70)

    position_map = {"center": "center", "lower": "bottom"}
    style.position = position_map.get(clip.position, "center")

    spec_dict = {
        "id": f"clip_{request.clip_id}",
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "duration": clip.duration,
        "background": "#000000",
        "clips": [
            {
                "id": "main_video",
                "type": "video",
                "src": clip.video_url,
                "start": 0.0,
                "end": clip.duration,
            }
        ] if clip.video_url else [],
        "subtitles": [
            {"id": s.id, "text": s.text, "start": s.start, "end": s.end}
            for s in clip.subtitles
        ],
        "style": style.model_dump(),
    }

    options = {
        "quality": "production",
        "format": "mp4",
    }

    async def _clip_render_complete_callback():
        await _run_revideo_render(job_id, spec_dict, options, request.template)
        # Update clip status after render
        job = _get_job(job_id)
        if job and job["status"] == "completed":
            repo.update_clip_status(request.clip_id, "ready")
            output_path = job.get("output_path")
            if output_path:
                # Update video_url with full path
                repo.update_clip_video_url(request.clip_id, output_path)
                # Extract filename and save video_filename for frontend
                video_filename = Path(output_path).name
                repo.update_clip_video_filename(request.clip_id, video_filename)
                logger.info(f"Clip video saved: clip_id={request.clip_id}, filename={video_filename}")
        elif job and job["status"] == "failed":
            repo.update_clip_status(request.clip_id, "error")

    background_tasks.add_task(asyncio.create_task, _clip_render_complete_callback())

    logger.info(f"Clip render started: clip_id={request.clip_id}, job_id={job_id}")

    return VideoJobResponse(
        job_id=job_id,
        status="pending",
        message="Clip render job created",
        created_at=datetime.utcnow(),
    )


@router.get("/jobs/{job_id}", response_model=VideoJobStatus)
async def get_job_status(
    job_id: str,
    user: User = Depends(get_current_user_optional),
):
    """Get video job status."""
    job = _get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Job not found", "job_id": job_id}
        )

    return VideoJobStatus(
        job_id=job["job_id"],
        status=job["status"],
        progress=job["progress"],
        output_path=job.get("output_path"),
        duration=job.get("duration"),
        frames=job.get("frames"),
        render_time=job.get("render_time"),
        error=job.get("error"),
    )


@router.get("/jobs")
async def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user_optional),
):
    """List video jobs."""
    user_id = user.user_id if user else None

    jobs = [
        VideoJobStatus(
            job_id=j["job_id"],
            status=j["status"],
            progress=j["progress"],
            output_path=j.get("output_path"),
            duration=j.get("duration"),
            frames=j.get("frames"),
            render_time=j.get("render_time"),
            error=j.get("error"),
        )
        for j in list(_video_jobs.values())[-limit:]
        if user_id is None or j.get("user_id") == user_id
    ]

    return {
        "jobs": jobs,
        "total": len(jobs),
    }


@router.post("/preview")
async def generate_preview(
    request: VideoComposeRequest,
    time: float = Query(default=0.0, description="Time in seconds for preview frame"),
):
    """Generate preview frame at specific time."""
    from app.video_engine.client import RevideoClient, VideoSpec, ClipSpec, SubtitleSpec

    try:
        # Build minimal spec
        clips = [
            ClipSpec(
                id=c.id or f"clip_{i}",
                type=c.type,
                start=c.start,
                end=c.end,
                src=c.src,
                color=c.color,
            )
            for i, c in enumerate(request.clips)
        ]

        subtitles = [
            SubtitleSpec(
                id=s.id or f"sub_{i}",
                text=s.text,
                start=s.start,
                end=s.end,
            )
            for i, s in enumerate(request.subtitles)
        ]

        spec = VideoSpec(
            id=request.id or "preview",
            width=request.width,
            height=request.height,
            fps=request.fps,
            duration=request.duration,
            background=request.background,
            clips=clips,
            subtitles=subtitles,
        )

        async with RevideoClient(auto_start_server=True) as client:
            result = await client.generate_preview(spec, time)
            return result

    except Exception as e:
        logger.exception(f"Preview generation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Preview generation failed", "message": str(e)}
        )


@router.post("/start-server")
async def start_revideo_server():
    """Manually start Revideo server."""
    from app.video_engine.client import RevideoClient

    try:
        async with RevideoClient(auto_start_server=True) as client:
            if await client.is_server_running():
                health = await client.health()
                return {
                    "status": "running",
                    "message": "Revideo server is now running",
                    "details": health,
                }
            else:
                return {
                    "status": "failed",
                    "message": "Failed to start Revideo server",
                }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Failed to start server", "message": str(e)}
        )


# =============================================================================
# Video File Serving
# =============================================================================

# Path to Revideo output directory - using BASE_DIR pattern
BASE_DIR = Path(__file__).resolve().parents[3]  # C:/dake
REVIDEO_OUTPUT_DIR = BASE_DIR / "app" / "video_engine" / "revideo" / "output"
SHORTS_CLIPS_DIR = BASE_DIR / "data" / "shorts"


def _serve_video(filename: str):
    """Internal function to serve video file."""
    # Security: only allow mp4, webm files, no path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Invalid filename"}
        )

    if not filename.endswith((".mp4", ".webm", ".mov")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Only video files allowed"}
        )

    video_path = REVIDEO_OUTPUT_DIR / filename

    # If not in Revideo output, search in YouTube Shorts clips directories
    if not video_path.exists():
        for clips_dir in SHORTS_CLIPS_DIR.glob("*/clips"):
            candidate = clips_dir / filename
            if candidate.exists():
                video_path = candidate
                break

    if not video_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Video file not found", "filename": filename, "path": str(video_path)}
        )

    # Determine media type
    media_type = "video/mp4"
    if filename.endswith(".webm"):
        media_type = "video/webm"
    elif filename.endswith(".mov"):
        media_type = "video/quicktime"

    return FileResponse(
        path=str(video_path),
        media_type=media_type,
        filename=filename,
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache, no-store, must-revalidate"
        }
    )


@router.get("/preview/{filename}")
async def serve_video_preview(filename: str):
    """Serve video preview - public endpoint for Editor UI."""
    return _serve_video(filename)


@router.get("/file/{filename}")
async def serve_video_file(filename: str):
    """Serve rendered video file from Revideo output directory."""
    return _serve_video(filename)


@router.get("/files")
async def list_video_files():
    """List all rendered video files."""
    if not REVIDEO_OUTPUT_DIR.exists():
        return {"files": [], "count": 0}

    files = []
    for f in REVIDEO_OUTPUT_DIR.glob("*.mp4"):
        stat = f.stat()
        files.append({
            "filename": f.name,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "url": f"/api/video/file/{f.name}"
        })

    files.sort(key=lambda x: x["created_at"], reverse=True)

    return {"files": files, "count": len(files)}
