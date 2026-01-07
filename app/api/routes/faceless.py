"""
Faceless Video Generation API Routes.
Provides endpoints for AutoShorts.ai-style faceless video creation.

Now uses DALL-E 3 for AI-generated visuals instead of stock footage.
Pipeline: Script (GPT-4o) → TTS (edge-tts) → Visuals (DALL-E 3) → Animation (Ken Burns) → Render
"""
import logging
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.services.faceless_engine import (
    get_faceless_engine,
    FacelessJob,
    JobStatus,
    SUBTITLE_STYLES,
    FACELESS_DIR
)
from app.services.llm_service import ScriptStyle
from app.services.tts_service import VoicePreset, TTSService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/faceless", tags=["Faceless Video"])


# =============================================================================
# Request/Response Models
# =============================================================================

class GenerateFacelessRequest(BaseModel):
    """Request to generate a faceless video."""
    topic: str = Field(..., description="Video topic or keyword", min_length=2)
    style: str = Field("viral", description="Script style: viral, educational, storytelling, motivational, documentary")
    language: str = Field("ru", description="Output language: ru, en")
    voice: str = Field("ru-RU-DmitryNeural", description="TTS voice preset")
    duration: int = Field(60, ge=15, le=180, description="Target duration in seconds")
    format: str = Field("9:16", description="Video format: 9:16, 1:1, 16:9")
    subtitle_style: str = Field("hormozi", description="Subtitle style: hormozi, clean, neon, bold")
    background_music: bool = Field(True, description="Include background music")
    music_volume: float = Field(0.2, ge=0, le=1, description="Background music volume")


class GenerateFacelessResponse(BaseModel):
    """Response from faceless generation start."""
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    """Job status response."""
    job_id: str
    topic: str
    status: str
    progress: float
    progress_message: str
    created_at: str
    completed_at: Optional[str]
    output_path: Optional[str]
    error: Optional[str]
    script: Optional[dict]
    audio_duration: Optional[float]
    image_urls: Optional[List[str]] = None


class ScriptPreviewRequest(BaseModel):
    """Request to preview generated script."""
    topic: str = Field(..., min_length=2)
    style: str = Field("viral")
    language: str = Field("ru")
    duration: int = Field(60, ge=15, le=180)


class StockSearchRequest(BaseModel):
    """Request to search stock footage."""
    query: str = Field(..., min_length=2)
    source: str = Field("pexels", description="pexels or pixabay")
    orientation: str = Field("portrait", description="portrait, landscape, square")
    per_page: int = Field(10, ge=1, le=50)


class VoicePreviewRequest(BaseModel):
    """Request to preview TTS voice."""
    text: str = Field(..., min_length=1, max_length=500)
    voice: str = Field("ru-RU-DmitryNeural")


# =============================================================================
# Main Generation Endpoints
# =============================================================================

@router.post("/generate", response_model=GenerateFacelessResponse)
async def generate_faceless_video(request: GenerateFacelessRequest):
    """
    Generate a complete faceless video from a topic using AI.

    This starts a background job that:
    1. Generates a viral script using GPT-4o
    2. Creates narration using edge-tts
    3. Generates visual prompts with GPT-4o
    4. Creates AI images with DALL-E 3 (1024x1792 for 9:16)
    5. Animates images with Ken Burns effect
    6. Renders final video with Hormozi-style subtitles

    Poll /status/{job_id} for progress updates.

    NOTE: Runs directly without Redis/Celery - no workers needed!
    """
    logger.info("=" * 60)
    logger.info(f"🎬 FACELESS VIDEO GENERATION STARTED")
    logger.info(f"   Topic: {request.topic}")
    logger.info(f"   Style: {request.style}")
    logger.info(f"   Duration: {request.duration}s")
    logger.info(f"   Format: {request.format}")
    logger.info("=" * 60)
    logger.info("🔄 Processing... (running directly, no Redis needed)")

    engine = get_faceless_engine()

    try:
        style = ScriptStyle(request.style) if request.style in [s.value for s in ScriptStyle] else ScriptStyle.VIRAL
    except ValueError:
        style = ScriptStyle.VIRAL

    job_id = await engine.create_faceless_video(
        topic=request.topic,
        style=style,
        language=request.language,
        voice=request.voice,
        duration=request.duration,
        format=request.format,
        subtitle_style=request.subtitle_style,
        background_music=request.background_music,
        music_volume=request.music_volume
    )

    logger.info(f"✅ Job created: {job_id}")
    logger.info(f"   Pipeline stages: Script → Audio → DALL-E 3 → Ken Burns → Render")

    return GenerateFacelessResponse(
        job_id=job_id,
        status="pending",
        message=f"🎬 AI видео о '{request.topic}' запущено! Job ID: {job_id}"
    )


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """Get the status of a faceless video generation job."""
    engine = get_faceless_engine()
    status = engine.get_job_status(job_id)

    if not status:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(**status)


@router.get("/jobs")
async def list_jobs(limit: int = 50):
    """
    List recent faceless video generation jobs.
    Jobs are persisted to SQLite and survive server restarts.
    """
    engine = get_faceless_engine()
    return {"jobs": engine.list_jobs(limit=limit)}


@router.get("/history")
async def get_job_history(limit: int = 50, status: str = None):
    """
    Get job history from database.
    Supports filtering by status: pending, processing, completed, failed
    """
    from app.persistence.faceless_jobs_repo import get_faceless_jobs_repository

    repo = get_faceless_jobs_repository()

    if status:
        jobs = repo.get_all_jobs(limit=limit)
        jobs = [j for j in jobs if j.status == status]
    else:
        jobs = repo.get_all_jobs(limit=limit)

    return {
        "jobs": [repo.to_api_response(j) for j in jobs],
        "total": len(jobs)
    }


@router.get("/job/{job_id}/full")
async def get_full_job_details(job_id: str):
    """
    Get complete job details for editor.
    Includes script, images, video URL, and all metadata.
    """
    from app.persistence.faceless_jobs_repo import get_faceless_jobs_repository

    repo = get_faceless_jobs_repository()
    job_record = repo.get_job(job_id)

    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")

    return repo.to_api_response(job_record)


# ═══════════════════════════════════════════════════════════════════════════
# EDITOR INTEGRATION ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/edit/{job_id}")
async def get_job_for_editor(job_id: str):
    """
    Get complete job data formatted for the video editor.
    Returns all segments with their image URLs for editing.

    Response format:
    {
        "job_id": "...",
        "topic": "...",
        "video_url": "/data/faceless/{job_id}/final.mp4",
        "segments": [
            {
                "index": 0,
                "text": "...",
                "duration": 5.0,
                "image_url": "/temp_images/{job_id}/segment_000.png",
                ...
            }
        ]
    }
    """
    from app.persistence.faceless_jobs_repo import get_faceless_jobs_repository

    repo = get_faceless_jobs_repository()
    editor_data = repo.get_job_for_editor(job_id)

    if not editor_data:
        raise HTTPException(status_code=404, detail="Job not found")

    return editor_data


@router.get("/edit/{job_id}/segments")
async def get_job_segments(job_id: str):
    """Get all segments for a job (for timeline display)."""
    from app.persistence.faceless_jobs_repo import get_faceless_jobs_repository

    repo = get_faceless_jobs_repository()
    segments = repo.get_segments(job_id)

    if not segments:
        # Check if job exists
        job = repo.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"segments": [], "message": "No segments found for this job"}

    return {
        "job_id": job_id,
        "segments": [
            {
                "index": seg.segment_index,
                "text": seg.text,
                "duration": seg.duration,
                "image_url": seg.image_url,
                "image_path": seg.image_path,
                "visual_prompt": seg.visual_prompt,
                "emotion": seg.emotion,
                "segment_type": seg.segment_type,
            }
            for seg in segments
        ],
        "count": len(segments)
    }


@router.put("/edit/{job_id}/segment/{segment_index}")
async def update_segment(job_id: str, segment_index: int, text: str = None, duration: float = None):
    """
    Update a specific segment (for editor changes).
    Allows modifying text and duration of individual segments.
    """
    from app.persistence.faceless_jobs_repo import get_faceless_jobs_repository

    repo = get_faceless_jobs_repository()

    # Verify job exists
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Update segment
    success = repo.update_segment(job_id, segment_index, text=text, duration=duration)

    if not success:
        raise HTTPException(status_code=404, detail=f"Segment {segment_index} not found")

    return {"success": True, "message": f"Segment {segment_index} updated"}


@router.get("/recent")
async def get_recent_jobs(limit: int = 20):
    """
    Get recent jobs for the 'Recent Jobs' page.
    Returns jobs from database so they persist across server restarts.
    """
    from app.persistence.faceless_jobs_repo import get_faceless_jobs_repository

    repo = get_faceless_jobs_repository()
    jobs = repo.get_all_jobs(limit=limit)

    return {
        "jobs": [
            {
                "job_id": job.job_id,
                "topic": job.topic,
                "status": job.status,
                "progress": job.progress,
                "created_at": job.created_at,
                "completed_at": job.completed_at,
                "video_url": f"/data/faceless/{job.job_id}/final.mp4" if job.status == "completed" else None,
                "can_edit": job.status == "completed",
            }
            for job in jobs
        ],
        "total": len(jobs)
    }


@router.get("/download/{job_id}")
async def download_video(job_id: str):
    """Download the generated video."""
    engine = get_faceless_engine()
    job = engine.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail=f"Job not completed. Status: {job.status.value}")

    if not job.output_path or not Path(job.output_path).exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    return FileResponse(
        job.output_path,
        media_type="video/mp4",
        filename=f"faceless_{job_id[:8]}.mp4"
    )


@router.get("/images/{job_id}")
async def get_job_images(job_id: str):
    """
    Get the list of generated images for a job.
    Returns URLs to access the images via /data/ static route.
    """
    engine = get_faceless_engine()
    job = engine.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check for images in the job directory
    images_dir = FACELESS_DIR / job_id / "images"
    if not images_dir.exists():
        return {"job_id": job_id, "images": [], "message": "Images folder not found"}

    # Get all PNG images
    image_files = sorted(images_dir.glob("*.png"))

    # Build URLs using the /data/ static mount
    images = []
    for img_path in image_files:
        # URL format: /data/faceless/{job_id}/images/{filename}
        url = f"/data/faceless/{job_id}/images/{img_path.name}"
        images.append({
            "filename": img_path.name,
            "url": url,
            "segment_index": int(img_path.stem.split("_")[-1]) if "_" in img_path.stem else 0
        })

    return {
        "job_id": job_id,
        "images": images,
        "count": len(images)
    }


# =============================================================================
# Preview & Utility Endpoints
# =============================================================================

@router.post("/preview-script")
async def preview_script(request: ScriptPreviewRequest):
    """
    Preview the AI-generated script before full video generation.
    Useful for reviewing content before committing to render.
    """
    from app.services.llm_service import LLMService

    llm = LLMService()

    try:
        style = ScriptStyle(request.style)
    except ValueError:
        style = ScriptStyle.VIRAL

    script = await llm.generate_script(
        topic=request.topic,
        style=style,
        duration_seconds=request.duration,
        language=request.language
    )

    # Analyze viral potential
    analysis = await llm.analyze_viral_potential(script)

    return {
        "script": {
            "title": script.title,
            "hook": script.hook,
            "segments": [
                {
                    "text": s.text,
                    "duration": s.duration,
                    "visual_keywords": s.visual_keywords,
                    "emotion": s.emotion,
                    "segment_type": s.segment_type
                }
                for s in script.segments
            ],
            "cta": script.cta,
            "total_duration": script.total_duration,
            "visual_keywords": script.visual_keywords,
            "background_music_mood": script.background_music_mood
        },
        "analysis": analysis
    }


@router.post("/preview-voice")
async def preview_voice(request: VoicePreviewRequest):
    """
    Preview TTS voice with sample text.
    Returns audio file for playback.
    """
    from app.services.tts_service import TTSService
    import uuid

    tts = TTSService(voice=request.voice)
    output_path = str(FACELESS_DIR / f"preview_{uuid.uuid4()}.mp3")

    result = await tts.generate_audio(request.text, output_path)

    return FileResponse(
        result.audio_path,
        media_type="audio/mpeg",
        filename="voice_preview.mp3"
    )


@router.get("/voices")
async def get_available_voices(language: str = "ru"):
    """Get available TTS voices for a language."""
    return TTSService.get_available_voices(language)


@router.get("/subtitle-styles")
async def get_subtitle_styles():
    """Get available subtitle style presets."""
    return {
        name: {
            "name": style.name,
            "font_family": style.font_family,
            "font_size": style.font_size,
            "primary_color": style.primary_color,
            "secondary_color": style.secondary_color,
            "animation": style.animation,
            "position": style.position
        }
        for name, style in SUBTITLE_STYLES.items()
    }


@router.get("/script-styles")
async def get_script_styles():
    """Get available script style presets."""
    return [
        {"id": "viral", "name": "Вирусный", "description": "Провокационный контент для максимального охвата"},
        {"id": "educational", "name": "Образовательный", "description": "Обучающий контент с примерами"},
        {"id": "storytelling", "name": "Сторителлинг", "description": "Нарративная структура с эмоциями"},
        {"id": "motivational", "name": "Мотивационный", "description": "Вдохновляющий контент"},
        {"id": "documentary", "name": "Документальный", "description": "Факты и статистика"},
    ]


# =============================================================================
# Stock Footage Endpoints
# =============================================================================

@router.post("/stock/search")
async def search_stock_footage(request: StockSearchRequest):
    """
    Search stock footage from Pexels/Pixabay.
    Returns list of available videos matching the query.
    """
    from app.services.stock_footage_service import (
        StockFootageService,
        VideoSource,
        VideoOrientation
    )

    service = StockFootageService()

    try:
        source = VideoSource(request.source)
    except ValueError:
        source = VideoSource.PEXELS

    orientation_map = {
        "portrait": VideoOrientation.PORTRAIT,
        "landscape": VideoOrientation.LANDSCAPE,
        "square": VideoOrientation.SQUARE
    }
    orientation = orientation_map.get(request.orientation, VideoOrientation.PORTRAIT)

    videos = await service.search(
        query=request.query,
        source=source,
        orientation=orientation,
        per_page=request.per_page
    )

    return {
        "query": request.query,
        "source": request.source,
        "results": [
            {
                "id": v.id,
                "source": v.source.value,
                "preview_url": v.preview_url,
                "duration": v.duration,
                "width": v.width,
                "height": v.height,
                "author": v.author,
                "tags": v.tags
            }
            for v in videos
        ]
    }


@router.get("/stock/sources")
async def get_stock_sources():
    """Get available stock footage sources."""
    return [
        {"id": "pexels", "name": "Pexels", "requires_api_key": True},
        {"id": "pixabay", "name": "Pixabay", "requires_api_key": True},
    ]


# =============================================================================
# Advanced Clipping Endpoints
# =============================================================================

@router.post("/analyze-viral-segments")
async def analyze_viral_segments(youtube_url: str, max_segments: int = 5):
    """
    Analyze YouTube video for viral segments using Director AI.
    Identifies Hook -> Value -> CTA structure in content.
    """
    # This integrates with the existing youtube_shorts service
    from app.youtube_shorts.service import YouTubeShortsService

    service = YouTubeShortsService()

    try:
        result = await service.analyze_youtube_url(
            youtube_url,
            max_clips=max_segments,
            goal="viral"
        )

        # Enhance with viral structure analysis
        enhanced_clips = []
        for clip in result.get("clips", []):
            enhanced_clip = {
                **clip,
                "viral_structure": {
                    "has_hook": _detect_hook(clip.get("text_preview", "")),
                    "has_value": True,  # Assumed if clip was selected
                    "has_cta": _detect_cta(clip.get("text_preview", "")),
                    "hook_strength": _calculate_hook_strength(clip.get("text_preview", "")),
                    "engagement_prediction": clip.get("score", 0.7) * 100
                }
            }
            enhanced_clips.append(enhanced_clip)

        return {
            "youtube_url": youtube_url,
            "video_duration": result.get("video_duration", 0),
            "segments": enhanced_clips,
            "best_segment": enhanced_clips[0] if enhanced_clips else None
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _detect_hook(text: str) -> bool:
    """Detect if text contains a hook pattern."""
    hook_patterns = ["?", "!", "вы знали", "секрет", "никто не", "всегда", "никогда"]
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in hook_patterns)


def _detect_cta(text: str) -> bool:
    """Detect if text contains a call-to-action."""
    cta_patterns = ["подпис", "лайк", "коммент", "поделит", "сохран", "follow", "subscribe"]
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in cta_patterns)


def _calculate_hook_strength(text: str) -> float:
    """Calculate hook strength score (0-100)."""
    score = 50.0

    power_words = ["секрет", "шок", "невероятно", "топ", "лучший", "худший", "всегда", "никогда"]
    for word in power_words:
        if word in text.lower():
            score += 10

    if "?" in text[:50]:  # Question in first 50 chars
        score += 15

    if len(text.split()) <= 10:  # Short and punchy
        score += 10

    return min(100.0, score)
