"""
Public UI Routes.
User-facing interface for the Video Rendering SaaS.
"""
import os
import uuid
import logging
import tempfile
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Request, Query, Header
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from celery.result import AsyncResult

from .dependencies import get_user_id, get_or_create_user_id, set_user_cookie, generate_idempotency_key

from app.persistence.users_repo import SQLiteUserRepository
from app.persistence.jobs_repo import SQLiteJobOwnershipTracker
from app.celery_app import celery_app

logger = logging.getLogger(__name__)

# Setup paths
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

router = APIRouter(tags=["Public UI"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_repos():
    """Get repository instances."""
    return {
        "users": SQLiteUserRepository(),
        "jobs": SQLiteJobOwnershipTracker(),
    }


def _map_celery_status(celery_status: str) -> str:
    """Map Celery status to simple status."""
    mapping = {
        "PENDING": "PENDING",
        "STARTED": "RUNNING",
        "PROGRESS": "RUNNING",
        "SUCCESS": "COMPLETED",
        "FAILURE": "FAILED",
        "REVOKED": "FAILED",
    }
    return mapping.get(celery_status, "PENDING")


def _get_progress(celery_status: str, info) -> int:
    """Get progress percentage from Celery task."""
    if celery_status == "SUCCESS":
        return 100
    if celery_status in ("FAILURE", "REVOKED"):
        return 0
    if celery_status == "PROGRESS" and isinstance(info, dict):
        return info.get("progress", 0)
    if celery_status == "STARTED":
        return 5
    return 0


def _get_message(celery_status: str, info) -> Optional[str]:
    """Get progress message from Celery task."""
    if celery_status == "PROGRESS" and isinstance(info, dict):
        return info.get("message", "")
    if celery_status == "STARTED":
        return "Запуск..."
    if celery_status == "PENDING":
        return "В очереди..."
    return None


def _format_datetime(dt) -> str:
    """Format datetime for display."""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    if isinstance(dt, datetime):
        return dt.strftime("%d.%m.%Y %H:%M")
    return str(dt)


# ============================================================================
# Static Files
# ============================================================================

@router.get("/static/{filename}", include_in_schema=False)
async def static_files(filename: str):
    """Serve static files."""
    file_path = STATIC_DIR / filename
    if file_path.exists():
        content = file_path.read_text()
        media_type = "text/css" if filename.endswith(".css") else "text/plain"
        return HTMLResponse(content=content, media_type=media_type)
    return HTMLResponse(content="Not Found", status_code=404)


# ============================================================================
# Landing Page
# ============================================================================

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing_page(request: Request):
    """Render landing page."""
    user_id = get_user_id(request)
    repos = get_repos()

    credits = 0
    if user_id:
        user = repos["users"].get(user_id)
        if user:
            credits = user.credits

    return templates.TemplateResponse("index.html", {
        "request": request,
        "user_id": user_id,
        "credits": credits,
        "show_navbar": True,
        "show_footer": True,
    })


# ============================================================================
# Dashboard
# ============================================================================

@router.get("/app", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request):
    """Render dashboard page."""
    repos = get_repos()

    # Always get or create user
    user_id = get_or_create_user_id(request)
    user = repos["users"].get_or_create(user_id)

    # Get jobs
    job_records = repos["jobs"].get_user_jobs(user_id)

    # Enrich with Celery status (with Redis error handling)
    recent_jobs = []
    completed_count = 0
    for record in job_records[-10:]:
        try:
            result = AsyncResult(record.task_id, app=celery_app)
            status = _map_celery_status(result.status)
            progress = _get_progress(result.status, result.info)
        except Exception:
            status = "PENDING"
            progress = 0

        if status == "COMPLETED":
            completed_count += 1
        recent_jobs.append({
            "job_id": record.job_id,
            "task_id": record.task_id,
            "status": status,
            "progress": progress,
            "created_at": _format_datetime(record.created_at),
        })

    recent_jobs.reverse()

    response = templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user_id": user_id,
        "credits": user.credits,
        "total_jobs": len(job_records),
        "completed_jobs": completed_count,
        "recent_jobs": recent_jobs[:5],
        "show_navbar": True,
        "show_footer": True,
        "active_page": "dashboard",
    })

    # Set cookie
    set_user_cookie(response, user_id)
    return response


# ============================================================================
# Create Video
# ============================================================================

@router.get("/app/create", response_class=HTMLResponse, include_in_schema=False)
async def create_page(request: Request):
    """Render create video page."""
    repos = get_repos()

    # Always get or create user
    user_id = get_or_create_user_id(request)
    user = repos["users"].get_or_create(user_id)

    response = templates.TemplateResponse("create.html", {
        "request": request,
        "user_id": user_id,
        "credits": user.credits,
        "idempotency_key": generate_idempotency_key(),
        "show_navbar": True,
        "show_footer": True,
        "active_page": "create",
    })

    set_user_cookie(response, user_id)
    return response


# ============================================================================
# Create Video API (simplified form -> RenderRequest)
# ============================================================================

class SimpleCreateRequest(BaseModel):
    """Simplified video creation request from UI form."""
    script_text: str
    voice: str = "alloy"
    background_music: Optional[str] = None
    resolution: dict = {"width": 1080, "height": 1920}
    fps: int = 30
    subtitle_font: str = "Arial"
    subtitle_size: str = "medium"
    highlight_words: bool = True


def _create_demo_files():
    """Create demo audio and background files for testing."""
    demo_dir = Path(tempfile.gettempdir()) / "videogen_demo"
    demo_dir.mkdir(exist_ok=True)

    audio_path = demo_dir / "demo_audio.mp3"
    bg_path = demo_dir / "demo_background.mp4"

    # Create minimal placeholder files if they don't exist
    if not audio_path.exists():
        audio_path.write_bytes(b"DEMO_AUDIO_FILE")
    if not bg_path.exists():
        bg_path.write_bytes(b"DEMO_VIDEO_FILE")

    return str(audio_path), str(bg_path)


def _build_render_request(form_data: SimpleCreateRequest, audio_path: str, bg_path: str) -> dict:
    """Convert simple form data to full RenderRequest payload."""
    # Parse script text into words for timestamps
    words = form_data.script_text.split()
    word_duration = 0.5  # seconds per word
    total_duration = len(words) * word_duration

    # Build word timestamps
    word_timestamps = []
    current_time = 0.0
    for word in words:
        word_timestamps.append({
            "word": word,
            "start": current_time,
            "end": current_time + word_duration,
        })
        current_time += word_duration

    # Build scenes (one scene with all text)
    scenes = [{
        "scene_id": f"scene-{uuid.uuid4().hex[:8]}",
        "scene_type": "video",
        "background_path": bg_path,
        "start_time": 0.0,
        "end_time": total_duration,
        "text": form_data.script_text,
    }]

    # Map subtitle size to font size
    font_sizes = {"small": 50, "medium": 70, "large": 90}
    subtitle_font_size = font_sizes.get(form_data.subtitle_size, 70)

    return {
        "script": {
            "script_id": f"script-{uuid.uuid4().hex[:8]}",
            "title": form_data.script_text[:50] + "..." if len(form_data.script_text) > 50 else form_data.script_text,
            "scenes": scenes,
            "total_duration": total_duration,
        },
        "audio_path": audio_path,
        "timestamps": {
            "words": word_timestamps,
            "total_duration": total_duration,
        },
        "bgm_path": None,  # Would map from background_music
        "output_dir": str(Path(tempfile.gettempdir()) / "video_output"),
        "output_filename": f"video_{uuid.uuid4().hex[:8]}.mp4",
        "settings": {
            "video_width": form_data.resolution.get("width", 1080),
            "video_height": form_data.resolution.get("height", 1920),
            "fps": form_data.fps,
            "subtitle_font_size": subtitle_font_size,
            "subtitle_active_color": "#FFD700" if form_data.highlight_words else "white",
        },
    }


@router.post("/app/create", include_in_schema=False)
async def create_video_api(
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Handle video creation from UI form.
    Accepts simplified form data and proxies to /render API.
    """
    repos = get_repos()

    # Always get or create user
    user_id = get_or_create_user_id(request)
    user = repos["users"].get_or_create(user_id)

    # Parse JSON body
    try:
        body = await request.json()
        form_data = SimpleCreateRequest(**body)
    except Exception as e:
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "INVALID_REQUEST", "message": str(e)}}
        )

    # Validate script text
    if len(form_data.script_text.strip()) < 10:
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "SCRIPT_TOO_SHORT", "message": "Текст должен быть не менее 10 символов"}}
        )

    # Generate idempotency key if not provided
    if not idempotency_key:
        idempotency_key = generate_idempotency_key()

    # Create demo files and build request
    audio_path, bg_path = _create_demo_files()
    render_payload = _build_render_request(form_data, audio_path, bg_path)

    # Import and call the render API directly
    try:
        from app.api.routes.render import create_render, RenderRequest
        from app.api.schemas import RenderRequest as RenderRequestSchema

        # Create RenderRequest from payload
        render_request = RenderRequestSchema(**render_payload)

        # Call the render endpoint directly
        response = await create_render(
            request=render_request,
            user=user,
            idempotency_key=idempotency_key,
        )

        return JSONResponse(
            status_code=202,
            content={
                "task_id": response.task_id,
                "job_id": response.job_id,
                "status": response.status.value,
                "message": response.message,
            }
        )

    except Exception as e:
        logger.exception(f"Failed to create video: {e}")

        # Extract error details
        error_detail = str(e) if str(e) else "Неизвестная ошибка"
        error_code = "RENDER_FAILED"
        status_code = 500

        # Handle HTTPException (from FastAPI)
        if hasattr(e, 'status_code'):
            status_code = e.status_code

        # Handle different detail formats
        if hasattr(e, 'detail'):
            detail = e.detail
            if isinstance(detail, dict):
                error_detail = detail.get('message') or detail.get('error') or str(detail)
                error_code = detail.get('code', 'ERROR')
            elif detail:
                error_detail = str(detail)

        # Handle APIError subclasses (ServiceUnavailableError, etc.)
        if hasattr(e, 'message') and e.message:
            error_detail = e.message
        if hasattr(e, 'code') and e.code:
            error_code = e.code

        return JSONResponse(
            status_code=status_code,
            content={"detail": {"code": error_code, "message": error_detail}}
        )


# ============================================================================
# Jobs List
# ============================================================================

@router.get("/app/jobs", response_class=HTMLResponse, include_in_schema=False)
async def jobs_list(
    request: Request,
    page: int = Query(default=1, ge=1),
):
    """Render jobs list page."""
    repos = get_repos()

    # Always get or create user
    user_id = get_or_create_user_id(request)
    user = repos["users"].get_or_create(user_id)

    # Get jobs
    job_records = repos["jobs"].get_user_jobs(user_id)

    # Pagination
    per_page = 20
    total_jobs = len(job_records)
    total_pages = max(1, (total_jobs + per_page - 1) // per_page)
    page = min(page, total_pages)

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_records = list(reversed(job_records))[start_idx:end_idx]

    # Stats
    stats = {"total": total_jobs, "completed": 0, "running": 0, "failed": 0, "pending": 0}

    # Enrich with Celery status (with Redis error handling)
    jobs = []
    for record in page_records:
        try:
            result = AsyncResult(record.task_id, app=celery_app)
            status = _map_celery_status(result.status)
            progress = _get_progress(result.status, result.info)
        except Exception:
            status = "PENDING"
            progress = 0

        jobs.append({
            "job_id": record.job_id,
            "task_id": record.task_id,
            "status": status,
            "progress": progress,
            "created_at": _format_datetime(record.created_at),
        })

    # Count stats from all jobs (with Redis error handling)
    for record in job_records:
        try:
            result = AsyncResult(record.task_id, app=celery_app)
            status = _map_celery_status(result.status)
        except Exception:
            status = "PENDING"

        if status == "COMPLETED":
            stats["completed"] += 1
        elif status == "RUNNING":
            stats["running"] += 1
        elif status == "FAILED":
            stats["failed"] += 1
        else:
            stats["pending"] += 1

    response = templates.TemplateResponse("jobs.html", {
        "request": request,
        "user_id": user_id,
        "credits": user.credits,
        "jobs": jobs,
        "stats": stats,
        "page": page,
        "total_pages": total_pages,
        "show_navbar": True,
        "show_footer": True,
        "active_page": "jobs",
    })

    set_user_cookie(response, user_id)
    return response


# ============================================================================
# Job Detail
# ============================================================================

@router.get("/app/jobs/{job_id}", response_class=HTMLResponse, include_in_schema=False)
async def job_detail(request: Request, job_id: str):
    """Render job detail page."""
    repos = get_repos()

    # Always get or create user
    user_id = get_or_create_user_id(request)
    user = repos["users"].get_or_create(user_id)

    # Find job by job_id
    job_records = repos["jobs"].get_user_jobs(user_id)
    job_record = None
    for record in job_records:
        if record.job_id == job_id:
            job_record = record
            break

    if not job_record:
        return HTMLResponse(content="Задача не найдена", status_code=404)

    # Get Celery status (with Redis error handling)
    output_url = None
    srt_url = None
    error = None

    try:
        result = AsyncResult(job_record.task_id, app=celery_app)
        status = _map_celery_status(result.status)
        progress = _get_progress(result.status, result.info)
        message = _get_message(result.status, result.info)

        if result.status == "SUCCESS" and result.result:
            output_url = result.result.get("output_path")
            srt_url = result.result.get("srt_path")
        elif result.status == "FAILURE":
            error = str(result.result) if result.result else "Неизвестная ошибка"
    except Exception:
        status = "PENDING"
        progress = 0
        message = "В очереди..."

    job = {
        "job_id": job_record.job_id,
        "task_id": job_record.task_id,
        "status": status,
        "progress": progress,
        "message": message,
        "output_url": output_url,
        "srt_url": srt_url,
        "error": error,
        "created_at": _format_datetime(job_record.created_at),
        "updated_at": None,
    }

    response = templates.TemplateResponse("job_detail.html", {
        "request": request,
        "user_id": user_id,
        "credits": user.credits,
        "job": job,
        "show_navbar": True,
        "show_footer": True,
        "active_page": "jobs",
    })

    set_user_cookie(response, user_id)
    return response


# ============================================================================
# API for Job Status (JSON)
# ============================================================================

@router.get("/api/v1/jobs/{job_id}", include_in_schema=False)
async def job_status_api(request: Request, job_id: str):
    """Get job status as JSON (for polling)."""
    repos = get_repos()

    user_id = get_user_id(request)
    if not user_id:
        return {"error": "Не авторизован"}

    # Find job by job_id
    job_records = repos["jobs"].get_user_jobs(user_id)
    job_record = None
    for record in job_records:
        if record.job_id == job_id:
            job_record = record
            break

    if not job_record:
        return {"error": "Задача не найдена"}

    # Get Celery status (with Redis error handling)
    try:
        result = AsyncResult(job_record.task_id, app=celery_app)
        status = _map_celery_status(result.status)
        progress = _get_progress(result.status, result.info)
        message = _get_message(result.status, result.info)
    except Exception:
        status = "PENDING"
        progress = 0
        message = "В очереди..."

    return {
        "job_id": job_id,
        "status": status,
        "progress": progress,
        "message": message,
    }


# ============================================================================
# YouTube Processing
# ============================================================================

@router.get("/app/youtube", response_class=HTMLResponse, include_in_schema=False)
async def youtube_page(request: Request):
    """Render YouTube processing page."""
    repos = get_repos()

    # Always get or create user
    user_id = get_or_create_user_id(request)
    user = repos["users"].get_or_create(user_id)

    response = templates.TemplateResponse("youtube.html", {
        "request": request,
        "user_id": user_id,
        "credits": user.credits,
        "show_navbar": True,
        "show_footer": True,
        "active_page": "youtube",
    })

    set_user_cookie(response, user_id)
    return response


# ============================================================================
# Interactive Editor
# ============================================================================

@router.get("/app/editor/{batch_id}", response_class=HTMLResponse, include_in_schema=False)
async def editor_batch(request: Request, batch_id: str):
    """Render editor page for a batch of clips."""
    repos = get_repos()

    # Always get or create user
    user_id = get_or_create_user_id(request)
    user = repos["users"].get_or_create(user_id)

    response = templates.TemplateResponse("editor.html", {
        "request": request,
        "user_id": user_id,
        "credits": user.credits,
        "batch_id": batch_id,
        "clip_id": None,
        "mode": "batch",
        "show_navbar": False,
        "show_footer": False,
    })

    set_user_cookie(response, user_id)
    return response


@router.get("/app/editor/single/{clip_id}", response_class=HTMLResponse, include_in_schema=False)
async def editor_single(request: Request, clip_id: str):
    """Render editor page for a single clip."""
    repos = get_repos()

    # Always get or create user
    user_id = get_or_create_user_id(request)
    user = repos["users"].get_or_create(user_id)

    response = templates.TemplateResponse("editor.html", {
        "request": request,
        "user_id": user_id,
        "credits": user.credits,
        "batch_id": None,
        "clip_id": clip_id,
        "mode": "single",
        "show_navbar": False,
        "show_footer": False,
    })

    set_user_cookie(response, user_id)
    return response
