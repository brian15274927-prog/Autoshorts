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
    art_style: str = Field("photorealism", description="Visual art style: photorealism, anime, ghibli, disney, comic, minecraft, lego, gtav, watercolor, expressionism, charcoal, pixel, creepy, childrens")
    background_music: bool = Field(True, description="Include background music")
    music_volume: float = Field(0.2, ge=0, le=1, description="Background music volume")

    # Custom idea - user's own script/idea to be processed by Storyteller
    custom_idea: Optional[str] = Field(
        None,
        description="Your own idea or draft script. Storyteller will structure it properly while keeping your key points.",
        max_length=5000
    )
    idea_mode: str = Field(
        "expand",
        description="How to process custom_idea: 'expand' (develop into full script), 'polish' (improve structure only), 'strict' (keep as close as possible)"
    )

    # Image generation provider
    image_provider: str = Field(
        "dalle",
        description="Image generation provider: 'dalle' (DALL-E 3, ~$0.04/img) or 'nanobanana' (Google Gemini, ~$0.039/img)"
    )


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
    """Request to preview generated script before full generation."""
    topic: str = Field(..., min_length=2)
    style: str = Field("viral")
    language: str = Field("ru")
    duration: int = Field(60, ge=15, le=180)
    art_style: str = Field("photorealism", description="Visual art style for prompts")


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
async def generate_faceless_video(
    request: GenerateFacelessRequest,
    x_user_id: str = "default"  # Get from header in production
):
    """
    Generate a complete faceless video from a topic using AI.

    This starts a background job that:
    1. Generates a viral script using GPT-4o-mini
    2. Creates narration using edge-tts
    3. Generates visual prompts with GPT-4o-mini
    4. Creates AI images with DALL-E 3 (1024x1792 for 9:16)
    5. Animates images with Ken Burns effect
    6. Renders final video with Hormozi-style subtitles

    Poll /status/{job_id} for progress updates.

    Limits are enforced based on user tier (free/pro/business).
    """
    from app.persistence.user_limits_repo import get_user_limits_repository

    # Check user limits
    limits_repo = get_user_limits_repository()
    check = limits_repo.check_can_generate(x_user_id, request.duration)

    if not check["allowed"]:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "reason": check["reason"],
                "tier": check["usage"].tier,
                "videos_today": check["usage"].videos_today,
                "videos_remaining": check["usage"].videos_remaining_today,
                "upgrade_hint": "Upgrade to Pro for 50 videos/day"
            }
        )

    logger.info("=" * 60)
    logger.info(f"🎬 FACELESS VIDEO GENERATION STARTED")
    logger.info(f"   Topic: {request.topic}")
    logger.info(f"   Style: {request.style}")
    logger.info(f"   Art Style: {request.art_style}")
    logger.info(f"   Image Provider: {request.image_provider}")
    logger.info(f"   Duration: {request.duration}s")
    logger.info(f"   Format: {request.format}")
    logger.info(f"   User: {x_user_id} ({check['usage'].tier})")
    logger.info(f"   Videos remaining today: {check['usage'].videos_remaining_today}")
    logger.info("=" * 60)

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
        art_style=request.art_style,
        background_music=request.background_music,
        music_volume=request.music_volume,
        custom_idea=request.custom_idea,
        idea_mode=request.idea_mode,
        image_provider=request.image_provider
    )

    # Record the generation for usage tracking
    limits_repo.record_video_generation(x_user_id)

    logger.info(f"✅ Job created: {job_id}")
    logger.info(f"   Pipeline stages: Script → Audio → DALL-E 3 → Ken Burns → Render")

    return GenerateFacelessResponse(
        job_id=job_id,
        status="pending",
        message=f"🎬 AI видео о '{request.topic}' запущено! Job ID: {job_id}"
    )


# =============================================================================
# User Limits & Tier Endpoints
# =============================================================================

@router.get("/limits")
async def get_user_limits(x_user_id: str = "default"):
    """
    Get current user's usage and limits.

    Returns:
        - Current tier (free/pro/business)
        - Videos generated today
        - Videos remaining today
        - Maximum duration allowed
        - Other tier-specific limits
    """
    from app.persistence.user_limits_repo import get_user_limits_repository, TIER_LIMITS, UserTier

    limits_repo = get_user_limits_repository()
    usage = limits_repo.get_or_create_user(x_user_id)
    tier_limits = TIER_LIMITS[UserTier(usage.tier)]

    return {
        "user_id": x_user_id,
        "tier": usage.tier,
        "usage": {
            "videos_today": usage.videos_today,
            "videos_total": usage.videos_total,
            "videos_remaining_today": usage.videos_remaining_today,
            "last_video_at": usage.last_video_at
        },
        "limits": {
            "videos_per_day": tier_limits.videos_per_day,
            "max_duration_seconds": tier_limits.max_duration_seconds,
            "max_segments": tier_limits.max_segments,
            "watermark": tier_limits.watermark,
            "dalle_quality": tier_limits.dalle_quality
        },
        "can_generate": usage.can_generate,
        "reason": usage.reason
    }


@router.get("/tiers")
async def get_available_tiers():
    """
    Get information about all available subscription tiers.

    Useful for displaying upgrade options to users.
    """
    from app.persistence.user_limits_repo import get_user_limits_repository

    limits_repo = get_user_limits_repository()
    return {
        "tiers": limits_repo.get_tier_info(),
        "comparison": {
            "free": {
                "price": "$0/month",
                "best_for": "Trying out the service",
                "highlights": ["3 videos/day", "30s max", "Watermark"]
            },
            "pro": {
                "price": "$19/month",
                "best_for": "Content creators",
                "highlights": ["50 videos/day", "90s max", "No watermark", "Priority queue"]
            },
            "business": {
                "price": "$99/month",
                "best_for": "Agencies & teams",
                "highlights": ["Unlimited videos", "180s max", "HD images", "API access"]
            }
        }
    }


@router.post("/upgrade")
async def upgrade_user_tier(tier: str, x_user_id: str = "default"):
    """
    Upgrade user to a new tier.

    In production, this would integrate with Stripe or another payment processor.
    For now, it directly upgrades the tier (for testing).
    """
    from app.persistence.user_limits_repo import get_user_limits_repository, UserTier

    # Validate tier
    try:
        UserTier(tier)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier: {tier}. Available: free, pro, business"
        )

    limits_repo = get_user_limits_repository()
    success = limits_repo.upgrade_tier(x_user_id, tier)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to upgrade tier")

    # Get updated limits
    usage = limits_repo.get_or_create_user(x_user_id)

    return {
        "success": True,
        "message": f"🎉 Upgraded to {tier.upper()} tier!",
        "new_tier": tier,
        "videos_remaining_today": usage.videos_remaining_today,
        "max_duration": usage.max_duration
    }


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
# RESUME FUNCTIONALITY - Continue failed jobs from checkpoint
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/resume/{job_id}")
async def resume_failed_job(job_id: str):
    """
    Resume a failed job from its last checkpoint.

    This saves money by not re-generating content that already exists:
    - If script exists, skip script generation (saves GPT-4 tokens)
    - If audio exists, skip audio generation
    - If images exist, skip DALL-E calls (saves $0.04-0.08 per image!)
    - If clips exist, skip Ken Burns animation

    Returns:
        200: Job resumed successfully
        400: Job cannot be resumed (already completed or no checkpoint)
        404: Job not found
    """
    from app.persistence.faceless_jobs_repo import get_faceless_jobs_repository, PipelineCheckpoint

    repo = get_faceless_jobs_repository()
    job_record = repo.get_job(job_id)

    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if job can be resumed
    if job_record.status == "completed":
        raise HTTPException(status_code=400, detail="Job already completed - nothing to resume")

    if job_record.checkpoint == PipelineCheckpoint.NONE.value:
        raise HTTPException(
            status_code=400,
            detail="Job has no checkpoint - use /generate to start fresh"
        )

    # Resume the job
    engine = get_faceless_engine()
    success = await engine.resume_job(job_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to resume job")

    return {
        "success": True,
        "job_id": job_id,
        "message": f"🔄 Job resumed from checkpoint: {job_record.checkpoint}",
        "checkpoint": job_record.checkpoint,
        "saved_stages": _get_saved_stages(job_record.checkpoint)
    }


@router.get("/resumable")
async def list_resumable_jobs():
    """
    List all jobs that can be resumed.
    These are failed jobs that have some progress saved.

    Returns jobs that failed after at least one checkpoint was saved,
    along with info about what was saved and estimated cost savings on resume.
    """
    from app.persistence.faceless_jobs_repo import get_faceless_jobs_repository

    repo = get_faceless_jobs_repository()
    jobs = repo.get_resumable_jobs()

    result = []
    for job in jobs:
        saved_stages = _get_saved_stages(job.checkpoint)
        result.append({
            "job_id": job.job_id,
            "topic": job.topic,
            "status": job.status,
            "checkpoint": job.checkpoint,
            "created_at": job.created_at,
            "error": job.error,
            "saved_stages": saved_stages,
            "estimated_savings": _estimate_savings(job.checkpoint)
        })

    return {
        "resumable_jobs": result,
        "total": len(result)
    }


def _get_saved_stages(checkpoint: str) -> list:
    """Get list of stages that are already complete based on checkpoint."""
    from app.persistence.faceless_jobs_repo import PipelineCheckpoint

    saved = []
    if checkpoint in [PipelineCheckpoint.SCRIPT_DONE.value,
                      PipelineCheckpoint.AUDIO_DONE.value,
                      PipelineCheckpoint.IMAGES_DONE.value,
                      PipelineCheckpoint.CLIPS_DONE.value,
                      PipelineCheckpoint.RENDERED.value]:
        saved.append("script")

    if checkpoint in [PipelineCheckpoint.AUDIO_DONE.value,
                      PipelineCheckpoint.IMAGES_DONE.value,
                      PipelineCheckpoint.CLIPS_DONE.value,
                      PipelineCheckpoint.RENDERED.value]:
        saved.append("audio")

    if checkpoint in [PipelineCheckpoint.IMAGES_DONE.value,
                      PipelineCheckpoint.CLIPS_DONE.value,
                      PipelineCheckpoint.RENDERED.value]:
        saved.append("images")

    if checkpoint in [PipelineCheckpoint.CLIPS_DONE.value,
                      PipelineCheckpoint.RENDERED.value]:
        saved.append("clips")

    return saved


def _estimate_savings(checkpoint: str) -> str:
    """Estimate cost savings from resuming at this checkpoint."""
    from app.persistence.faceless_jobs_repo import PipelineCheckpoint

    savings = 0.0

    if checkpoint in [PipelineCheckpoint.SCRIPT_DONE.value,
                      PipelineCheckpoint.AUDIO_DONE.value,
                      PipelineCheckpoint.IMAGES_DONE.value,
                      PipelineCheckpoint.CLIPS_DONE.value]:
        savings += 0.01  # GPT-4o-mini for script

    if checkpoint in [PipelineCheckpoint.IMAGES_DONE.value,
                      PipelineCheckpoint.CLIPS_DONE.value]:
        savings += 0.24  # ~6 DALL-E images * $0.04 each

    return f"~${savings:.2f}"


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


class UpdateSegmentRequest(BaseModel):
    """Request to update a segment."""
    segment_index: int  # Required: which segment to update
    text: Optional[str] = None
    duration: Optional[float] = None
    visual_prompt: Optional[str] = None
    emotion: Optional[str] = None


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


@router.post("/edit/{job_id}/update_segment")
async def update_segment_post(job_id: str, request: UpdateSegmentRequest):
    """
    Update a specific segment via POST (full update support).
    Allows modifying text, duration, visual_prompt, and emotion.
    """
    from app.persistence.faceless_jobs_repo import get_faceless_jobs_repository

    repo = get_faceless_jobs_repository()
    segment_index = request.segment_index

    # Verify job exists
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Update segment
    success = repo.update_segment(
        job_id,
        segment_index,
        text=request.text,
        duration=request.duration,
        visual_prompt=request.visual_prompt,
        emotion=request.emotion
    )

    if not success:
        raise HTTPException(status_code=404, detail=f"Segment {segment_index} not found")

    # Return updated segment
    updated = repo.get_segment(job_id, segment_index)
    return {
        "success": True,
        "message": f"Segment {segment_index} updated",
        "segment": {
            "index": updated.segment_index,
            "text": updated.text,
            "duration": updated.duration,
            "image_url": updated.image_url,
            "visual_prompt": updated.visual_prompt,
            "emotion": updated.emotion
        }
    }


class RegenerateImageRequest(BaseModel):
    """Request to regenerate segment image with DALL-E."""
    prompt: Optional[str] = None  # Custom prompt, or use existing visual_prompt


@router.post("/edit/{job_id}/regenerate_image/{segment_index}")
async def regenerate_segment_image(
    job_id: str,
    segment_index: int,
    request: RegenerateImageRequest,
    background_tasks: BackgroundTasks
):
    """
    Regenerate image for a segment using DALL-E 3.
    Optionally provide a custom prompt, or use the existing visual_prompt.
    """
    from app.persistence.faceless_jobs_repo import get_faceless_jobs_repository
    from app.services.dalle_service import DalleService

    repo = get_faceless_jobs_repository()

    # Verify job and segment exist
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    segment = repo.get_segment(job_id, segment_index)
    if not segment:
        raise HTTPException(status_code=404, detail=f"Segment {segment_index} not found")

    # Get prompt and ensure art style is applied
    prompt = request.prompt or segment.visual_prompt
    if not prompt:
        raise HTTPException(status_code=400, detail="No prompt provided")

    # Get art_style from job settings and inject modifier if custom prompt provided
    art_style = job.art_style or "photorealism"
    if request.prompt:  # Custom prompt - need to inject art style
        from app.services.agents.visual_director import ART_STYLE_PROMPTS, DEFAULT_ART_STYLE
        art_style_modifier = ART_STYLE_PROMPTS.get(art_style, ART_STYLE_PROMPTS.get(DEFAULT_ART_STYLE))
        if art_style_modifier and art_style_modifier not in prompt:
            prompt = f"{art_style_modifier}, {prompt}"
            logger.info(f"[REGENERATE] Injected art_style '{art_style}' into custom prompt")

    # Generate new image
    dalle = DalleService()
    images_dir = FACELESS_DIR / job_id / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    output_path = str(images_dir / f"segment_{segment_index:03d}.png")

    try:
        # generate_image returns GeneratedImage on success, None on failure
        result = await dalle.generate_image(
            prompt=prompt,
            output_path=output_path,
            size="1024x1792"  # 9:16 aspect ratio
        )

        if result is not None:
            # Success - update database
            repo.update_segment(job_id, segment_index, image_path=result.image_path, visual_prompt=prompt)

            # Also copy to temp_images for editor access
            temp_dir = Path("C:/dake/data/temp_images") / job_id
            temp_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            temp_path = temp_dir / f"segment_{segment_index:03d}.png"
            shutil.copy2(result.image_path, str(temp_path))

            return {
                "success": True,
                "message": f"Image regenerated for segment {segment_index}",
                "image_url": f"/temp_images/{job_id}/segment_{segment_index:03d}.png",
                "prompt_used": prompt
            }
        else:
            raise HTTPException(status_code=500, detail="DALL-E generation failed - check API key and quota")

    except Exception as e:
        logger.error(f"Failed to regenerate image: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/edit/{job_id}/upload_image/{segment_index}")
async def upload_segment_image(job_id: str, segment_index: int):
    """
    Upload a custom image for a segment.
    Expects multipart form data with 'file' field.
    """
    from fastapi import UploadFile, File
    from app.persistence.faceless_jobs_repo import get_faceless_jobs_repository

    # This endpoint is a stub - actual implementation would need UploadFile
    # For now, return info about how to use it
    return {
        "message": "Use multipart/form-data with 'file' field to upload image",
        "job_id": job_id,
        "segment_index": segment_index
    }


class RenderSegmentRequest(BaseModel):
    """Request to re-render specific segments."""
    segment_indices: List[int] = Field(..., description="Indices of segments to re-render")
    regenerate_audio: bool = Field(False, description="Re-generate TTS audio for text changes")


@router.post("/edit/{job_id}/render")
async def render_edited_video(job_id: str, background_tasks: BackgroundTasks):
    """
    Re-render the video with all current edits applied.
    This performs a partial re-render where possible.
    """
    from app.persistence.faceless_jobs_repo import get_faceless_jobs_repository

    repo = get_faceless_jobs_repository()

    # Verify job exists
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Can only re-render completed jobs")

    # Get all segments
    segments = repo.get_segments(job_id)
    if not segments:
        raise HTTPException(status_code=400, detail="No segments found")

    # Start background re-render task
    background_tasks.add_task(_rerender_video, job_id, job, segments)

    return {
        "success": True,
        "message": "Re-render started",
        "job_id": job_id,
        "segment_count": len(segments)
    }


async def _rerender_video(job_id: str, job, segments):
    """Background task to re-render video with edits."""
    import json
    from app.persistence.faceless_jobs_repo import get_faceless_jobs_repository
    from app.services.ken_burns_service import KenBurnsService
    from app.services.video_renderer import VideoRenderer

    logger.info(f"[RE-RENDER] Starting re-render for job {job_id}")
    repo = get_faceless_jobs_repository()

    try:
        job_dir = FACELESS_DIR / job_id

        # Get image paths from segments
        image_paths = [seg.image_path for seg in segments if seg.image_path]

        if not image_paths:
            logger.error(f"[RE-RENDER] No images found for job {job_id}")
            return

        # Re-create Ken Burns animated clips
        ken_burns = KenBurnsService()
        durations = [seg.duration for seg in segments]

        clip_paths = await ken_burns.animate_images(
            image_paths=image_paths,
            durations=durations,
            output_dir=str(job_dir / "clips"),
            fps=30
        )

        # Concatenate clips
        concat_video = str(job_dir / "concat_video_edited.mp4")
        await ken_burns.concatenate_clips(clip_paths, concat_video)

        # Re-render with existing audio and new subtitles
        audio_path = job.audio_path
        if not audio_path or not Path(audio_path).exists():
            logger.warning(f"[RE-RENDER] Audio not found: {audio_path}")
            audio_path = None

        # Build subtitle data from segments
        subtitle_data = [
            {"text": seg.text, "duration": seg.duration}
            for seg in segments
        ]

        # Render final video
        renderer = VideoRenderer()
        output_path = str(job_dir / "final_edited.mp4")

        await renderer.render_with_subtitles(
            video_path=concat_video,
            audio_path=audio_path,
            subtitles=subtitle_data,
            output_path=output_path,
            style=job.subtitle_style or "hormozi"
        )

        # Update job output path
        repo.complete_job(job_id, output_path, "Re-rendered with edits")
        logger.info(f"[RE-RENDER] Complete: {output_path}")

    except Exception as e:
        logger.error(f"[RE-RENDER] Failed: {e}")
        repo.fail_job(job_id, f"Re-render failed: {str(e)}")


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

    Uses the Multi-Agent system (Storyteller + Visual Director) to generate:
    - Structured narrative (HOOK → CONTEXT → BUILD → CLIMAX → PAYOFF)
    - Visual prompts for each segment with art style applied
    - Estimated cost for full generation

    This lets you review and approve the script BEFORE spending money on:
    - DALL-E image generation (~$0.24 for 6 images)
    - TTS audio generation
    - Video rendering

    Returns the complete script with visual prompts for preview.
    """
    from app.services.agents import TechnicalDirector
    from app.services.agents.storyteller import ScriptStyle as AgentScriptStyle

    orchestrator = TechnicalDirector()

    try:
        style = AgentScriptStyle(request.style.lower())
    except ValueError:
        style = AgentScriptStyle.DOCUMENTARY

    # Generate script using Multi-Agent system
    orchestrated = await orchestrator.orchestrate_script_generation(
        topic=request.topic,
        style=style,
        language=request.language,
        duration_seconds=request.duration,
        art_style=request.art_style
    )

    # Convert to legacy format for response
    script_data = orchestrator.convert_to_legacy_format(orchestrated)

    # Calculate estimated costs
    num_segments = len(script_data["segments"])
    estimated_dalle_cost = num_segments * 0.04  # $0.04 per standard image
    estimated_total_cost = estimated_dalle_cost + 0.01  # + GPT-4o-mini cost

    return {
        "script": {
            "title": script_data["title"],
            "hook": script_data["hook"],
            "narrative": script_data.get("narrative", ""),
            "segments": [
                {
                    "text": s["text"],
                    "duration": s["duration"],
                    "visual_prompt": s.get("visual_prompt", ""),
                    "visual_keywords": s.get("visual_keywords", []),
                    "emotion": s.get("emotion", "neutral"),
                    "segment_type": s.get("segment_type", "content")
                }
                for s in script_data["segments"]
            ],
            "cta": script_data["cta"],
            "total_duration": script_data["total_duration"],
            "visual_keywords": script_data["visual_keywords"],
            "background_music_mood": script_data["background_music_mood"],
            "art_style": request.art_style,
            "style_consistency": script_data.get("style_consistency_string", "")
        },
        "generation_info": {
            "used_fallback_story": orchestrated.used_fallback_story,
            "used_fallback_segments": orchestrated.used_fallback_segments,
            "model_used": "gpt-4o-mini",
            "art_style_applied": request.art_style
        },
        "estimated_cost": {
            "script_cost": "$0.01",
            "audio_cost": "free (edge-tts)",
            "images_cost": f"${estimated_dalle_cost:.2f} ({num_segments} images)",
            "total_cost": f"${estimated_total_cost:.2f}",
            "note": "Preview is FREE. Costs apply only when you proceed with /generate"
        }
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
