"""
Faceless Engine - Complete Auto-Pilot Video Generation.
Orchestrates LLM, TTS, DALL-E 3, and Ken Burns animation for faceless content.
"""
import os
import sys
import asyncio
import logging
import uuid
import json
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum

# CRITICAL: Fix Windows asyncio for subprocess support
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from .llm_service import LLMService, GeneratedScript, ScriptStyle
from .tts_service import TTSService, TTSResult, VoicePreset
from .dalle_service import DalleService, VisualPromptGenerator, GeneratedImage
from .ken_burns_service import KenBurnsService, AnimatedClip, KenBurnsEffect

# Multi-Agent Orchestration System
from .agents import TechnicalDirector, MasterStoryteller, VisualDirector
from .agents.storyteller import ScriptStyle as AgentScriptStyle

# Import persistence layer for SQLite storage
from app.persistence.faceless_jobs_repo import (
    FacelessJobsRepository,
    get_faceless_jobs_repository,
    FacelessJobRecord
)

logger = logging.getLogger(__name__)

# Output directories
DATA_DIR = Path(__file__).parent.parent.parent / "data"
FACELESS_DIR = DATA_DIR / "faceless"
FACELESS_DIR.mkdir(parents=True, exist_ok=True)


def get_ffmpeg_path() -> str:
    """Get FFmpeg executable path - prioritize local installation."""
    # Check for local FFmpeg installation first (Windows)
    local_paths = [
        r"C:\dake\tools\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe",
        r"C:\dake\tools\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]

    for path in local_paths:
        if os.path.exists(path):
            logger.info(f"Found local FFmpeg: {path}")
            return path

    # Try imageio-ffmpeg as fallback
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(ffmpeg_path):
            logger.info(f"Using imageio-ffmpeg: {ffmpeg_path}")
            return ffmpeg_path
    except ImportError:
        pass

    # System PATH as last resort
    logger.warning("Using system FFmpeg from PATH")
    return "ffmpeg"


def get_ffprobe_path() -> str:
    """Get FFprobe executable path - prioritize local installation."""
    # Check for local FFprobe installation first (Windows)
    local_paths = [
        r"C:\dake\tools\ffmpeg-master-latest-win64-gpl\bin\ffprobe.exe",
        r"C:\dake\tools\ffmpeg-8.0.1-essentials_build\bin\ffprobe.exe",
        r"C:\ffmpeg\bin\ffprobe.exe",
        r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
    ]

    for path in local_paths:
        if os.path.exists(path):
            return path

    # Try imageio-ffmpeg as fallback
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")
        if os.path.exists(ffprobe_path):
            return ffprobe_path
    except ImportError:
        pass

    return "ffprobe"


FFMPEG_PATH = get_ffmpeg_path()
FFPROBE_PATH = get_ffprobe_path()

# STARTUP DIAGNOSTIC - Log configuration status
logger.info("=" * 60)
logger.info("FACELESS ENGINE CONFIGURATION")
logger.info("=" * 60)
logger.info(f"[OK] FFmpeg Path: {FFMPEG_PATH}")
logger.info(f"[OK] FFprobe Path: {FFPROBE_PATH}")
logger.info(f"[OK] FFmpeg Exists: {os.path.exists(FFMPEG_PATH)}")
logger.info("=" * 60)

logger.info(f"Using FFmpeg: {FFMPEG_PATH}")
logger.info(f"Using FFprobe: {FFPROBE_PATH}")


class JobStatus(str, Enum):
    """Job status states."""
    PENDING = "pending"
    GENERATING_SCRIPT = "generating_script"
    GENERATING_AUDIO = "generating_audio"
    GENERATING_VISUALS = "generating_visuals"  # DALL-E image generation
    ANIMATING_VISUALS = "animating_visuals"    # Ken Burns animation
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class FacelessJob:
    """Faceless video generation job."""
    job_id: str
    topic: str
    status: JobStatus
    progress: float  # 0-100
    progress_message: str
    created_at: str
    completed_at: Optional[str] = None

    # Settings
    style: str = "viral"
    language: str = "ru"
    voice: str = "ru-RU-DmitryNeural"
    duration: int = 60
    format: str = "9:16"
    width: int = 1080
    height: int = 1920
    subtitle_style: str = "hormozi"
    art_style: str = "photorealism"
    background_music: bool = True
    music_volume: float = 0.2

    # Generated content
    script: Optional[Dict[str, Any]] = None
    audio_path: Optional[str] = None
    audio_duration: Optional[float] = None
    footage_paths: List[str] = field(default_factory=list)
    output_path: Optional[str] = None

    # AI Visual generation
    image_paths: List[str] = field(default_factory=list)
    clip_paths: List[str] = field(default_factory=list)
    visual_prompts: List[str] = field(default_factory=list)

    # Error info
    error: Optional[str] = None

    # Status flags for UI
    used_fallback_script: bool = False
    used_fallback_visuals: bool = False
    api_limit_reached: bool = False
    status_details: str = ""

    # Checkpoint for resume functionality
    checkpoint: str = "none"

    # Custom idea from user
    custom_idea: Optional[str] = None
    idea_mode: str = "expand"  # expand, polish, strict

    # Image generation provider: "dalle" or "nanobanana"
    image_provider: str = "dalle"


@dataclass
class SubtitleStyle:
    """Subtitle styling configuration."""
    name: str
    font_family: str
    font_size: int
    font_weight: str
    primary_color: str
    secondary_color: str
    outline_color: str
    outline_width: int
    shadow: bool
    animation: str
    position: str  # top, center, bottom


# Predefined subtitle styles
SUBTITLE_STYLES = {
    "hormozi": SubtitleStyle(
        name="Hormozi Style",
        font_family="Montserrat",
        font_size=48,
        font_weight="900",
        primary_color="#FFFF00",
        secondary_color="#FFFFFF",
        outline_color="#000000",
        outline_width=4,
        shadow=True,
        animation="pop",
        position="center"
    ),
    "clean": SubtitleStyle(
        name="Clean",
        font_family="Inter",
        font_size=36,
        font_weight="600",
        primary_color="#FFFFFF",
        secondary_color="#FFFFFF",
        outline_color="#000000",
        outline_width=2,
        shadow=True,
        animation="fade",
        position="bottom"
    ),
    "neon": SubtitleStyle(
        name="Neon",
        font_family="Poppins",
        font_size=42,
        font_weight="700",
        primary_color="#00FFFF",
        secondary_color="#FF00FF",
        outline_color="#000000",
        outline_width=0,
        shadow=True,
        animation="glow",
        position="center"
    ),
    "bold": SubtitleStyle(
        name="Bold",
        font_family="Roboto",
        font_size=52,
        font_weight="900",
        primary_color="#FFFFFF",
        secondary_color="#FF0000",
        outline_color="#000000",
        outline_width=6,
        shadow=True,
        animation="scale",
        position="center"
    ),
}


class FacelessEngine:
    """
    Main orchestrator for faceless video generation.
    Combines LLM, TTS, DALL-E 3 AI Visuals, Ken Burns Animation, and FFmpeg rendering.

    Pipeline:
    1. Generate script with GPT-4o
    2. Generate audio narration with edge-tts
    3. Generate visual prompts with GPT-4o
    4. Generate AI images with DALL-E 3
    5. Animate images with Ken Burns effects
    6. Render final video with subtitles
    """

    # In-memory job storage (also persisted to SQLite)
    _jobs: Dict[str, FacelessJob] = {}

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        tts_service: Optional[TTSService] = None,
        dalle_service: Optional[DalleService] = None,
        ken_burns_service: Optional[KenBurnsService] = None,
        progress_callback: Optional[Callable[[str, float, str], None]] = None
    ):
        self.llm = llm_service or LLMService()
        self.tts = tts_service or TTSService()
        self.dalle = dalle_service or DalleService()
        self.ken_burns = ken_burns_service or KenBurnsService()
        self.prompt_generator = VisualPromptGenerator()
        self.progress_callback = progress_callback

        # Initialize Multi-Agent Orchestration System
        self.orchestrator = TechnicalDirector()
        logger.info("[ENGINE] Multi-Agent Orchestration System initialized")

        # Initialize SQLite persistence
        self.db = get_faceless_jobs_repository()
        logger.info("FacelessEngine initialized with SQLite persistence")

    async def create_faceless_video(
        self,
        topic: str,
        style: ScriptStyle = ScriptStyle.VIRAL,
        language: str = "ru",
        voice: str = VoicePreset.RU_MALE_DMITRY,
        duration: int = 60,
        format: str = "9:16",
        subtitle_style: str = "hormozi",
        art_style: str = "photorealism",
        background_music: bool = True,
        music_volume: float = 0.2,
        custom_idea: Optional[str] = None,
        idea_mode: str = "expand",
        image_provider: str = "dalle"
    ) -> str:
        """
        Create a complete faceless video from a topic or custom idea.

        Args:
            topic: Video topic or keyword
            style: Script style
            language: Output language
            voice: TTS voice preset
            duration: Target duration in seconds
            format: Video format (9:16, 1:1, 16:9)
            subtitle_style: Subtitle style preset
            art_style: Visual art style for DALL-E (photorealism, anime, etc.)
            background_music: Include background music
            music_volume: Background music volume (0-1)
            custom_idea: User's own idea/draft to be processed by Storyteller
            idea_mode: How to process custom_idea:
                - 'expand': Develop into full structured script
                - 'polish': Improve structure, keep content
                - 'strict': Keep as close as possible to original
            image_provider: Image generation provider:
                - 'dalle': DALL-E 3 (~$0.04/image)
                - 'nanobanana': Google Gemini (~$0.039/image)

        Returns:
            job_id for tracking progress
        """
        # Create job
        job_id = str(uuid.uuid4())
        width, height = self._get_dimensions(format)

        job = FacelessJob(
            job_id=job_id,
            topic=topic,
            status=JobStatus.PENDING,
            progress=0,
            progress_message="Инициализация...",
            created_at=datetime.utcnow().isoformat(),
            style=style.value,
            language=language,
            voice=voice,
            duration=duration,
            format=format,
            width=width,
            height=height,
            subtitle_style=subtitle_style,
            art_style=art_style,
            background_music=background_music,
            music_volume=music_volume,
            custom_idea=custom_idea,
            idea_mode=idea_mode,
            image_provider=image_provider
        )

        # Store in memory
        self._jobs[job_id] = job

        # PERSIST TO DATABASE - Jobs survive server restarts
        self.db.create_job(
            job_id=job_id,
            user_id="default",  # TODO: Get from request context
            topic=topic,
            style=style.value,
            language=language,
            voice=voice,
            duration=duration,
            format=format,
            width=width,
            height=height,
            subtitle_style=subtitle_style,
            art_style=art_style
        )
        logger.info(f"Job {job_id} persisted to SQLite database")

        # Start generation in background
        asyncio.create_task(self._run_pipeline(job))

        return job_id

    async def resume_job(self, job_id: str) -> bool:
        """
        Resume a failed job from its last checkpoint.

        This saves money by not re-generating content that already exists:
        - If script exists, skip script generation
        - If audio exists, skip audio generation
        - If images exist, skip DALL-E calls (most expensive!)
        - If clips exist, skip Ken Burns animation

        Returns:
            True if job was resumed, False if job cannot be resumed
        """
        from app.persistence.faceless_jobs_repo import PipelineCheckpoint

        # Get job from database
        job_record = self.db.get_job(job_id)
        if not job_record:
            logger.error(f"[RESUME] Job {job_id} not found")
            return False

        # Check if job can be resumed
        if job_record.status == "completed":
            logger.info(f"[RESUME] Job {job_id} already completed")
            return False

        if job_record.checkpoint == PipelineCheckpoint.NONE.value:
            logger.info(f"[RESUME] Job {job_id} has no checkpoint, starting fresh")

        # Reset job status for resume
        self.db.reset_job_for_resume(job_id)

        # Reconstruct FacelessJob from database record
        width, height = self._get_dimensions(job_record.format)

        job = FacelessJob(
            job_id=job_id,
            topic=job_record.topic,
            status=JobStatus.PENDING,
            progress=0,
            progress_message="Resuming from checkpoint...",
            created_at=job_record.created_at,
            style=job_record.style,
            language=job_record.language,
            voice=job_record.voice,
            duration=job_record.duration,
            format=job_record.format,
            width=width,
            height=height,
            subtitle_style=job_record.subtitle_style,
            art_style=job_record.art_style
        )

        # Restore saved data based on checkpoint
        checkpoint = job_record.checkpoint

        if checkpoint in [PipelineCheckpoint.SCRIPT_DONE.value,
                          PipelineCheckpoint.AUDIO_DONE.value,
                          PipelineCheckpoint.IMAGES_DONE.value,
                          PipelineCheckpoint.CLIPS_DONE.value]:
            # Restore script
            if job_record.script_json:
                import json
                job.script = json.loads(job_record.script_json)
                logger.info(f"[RESUME] Restored script for job {job_id}")

        if checkpoint in [PipelineCheckpoint.AUDIO_DONE.value,
                          PipelineCheckpoint.IMAGES_DONE.value,
                          PipelineCheckpoint.CLIPS_DONE.value]:
            # Restore audio
            job.audio_path = job_record.audio_path
            job.audio_duration = job_record.audio_duration
            logger.info(f"[RESUME] Restored audio for job {job_id}")

        if checkpoint in [PipelineCheckpoint.IMAGES_DONE.value,
                          PipelineCheckpoint.CLIPS_DONE.value]:
            # Restore images
            if job_record.image_paths_json:
                import json
                job.image_paths = json.loads(job_record.image_paths_json)
                logger.info(f"[RESUME] Restored {len(job.image_paths)} images for job {job_id}")
            if job_record.visual_prompts_json:
                import json
                job.visual_prompts = json.loads(job_record.visual_prompts_json)

        if checkpoint == PipelineCheckpoint.CLIPS_DONE.value:
            # Restore clips
            if job_record.clip_paths_json:
                import json
                job.clip_paths = json.loads(job_record.clip_paths_json)
                logger.info(f"[RESUME] Restored {len(job.clip_paths)} clips for job {job_id}")

        # Store checkpoint in job for pipeline to use
        job.checkpoint = checkpoint

        # Store in memory
        self._jobs[job_id] = job

        logger.info(f"[RESUME] Resuming job {job_id} from checkpoint: {checkpoint}")

        # Start pipeline with resume flag
        asyncio.create_task(self._run_pipeline(job, resume=True))

        return True

    async def _run_pipeline(self, job: FacelessJob, resume: bool = False):
        """
        Run the complete AI-powered faceless video generation pipeline.

        Pipeline stages:
        1. Generate Script (0-15%) - GPT-4o creates viral script
        2. Generate Audio (15-30%) - edge-tts creates narration
        3. Generate Visual Prompts (30-35%) - GPT-4o creates DALL-E prompts
        4. Generate AI Images (35-60%) - DALL-E 3 creates cinematic visuals
        5. Ken Burns Animation (60-80%) - Animate static images
        6. Final Render (80-100%) - Combine with audio and subtitles

        When resume=True, skips stages that are already complete based on checkpoint.
        """
        from app.persistence.faceless_jobs_repo import PipelineCheckpoint

        job_dir = FACELESS_DIR / job.job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        # Create temp directories - Use ABSOLUTE PATHS for Windows reliability
        # Images go to centralized temp_images directory for easier debugging
        temp_images_base = Path(r"C:\dake\data\temp_images")
        temp_images_base.mkdir(parents=True, exist_ok=True)
        images_dir = temp_images_base / job.job_id
        clips_dir = job_dir / "clips"
        images_dir.mkdir(exist_ok=True)
        clips_dir.mkdir(exist_ok=True)
        logger.info(f"[DIR] Image output directory: {images_dir}")

        # Helper to check if we should skip a stage
        def should_skip(required_checkpoint: str) -> bool:
            """Check if we should skip this stage based on checkpoint."""
            if not resume:
                return False
            checkpoint_order = [
                PipelineCheckpoint.NONE.value,
                PipelineCheckpoint.SCRIPT_DONE.value,
                PipelineCheckpoint.AUDIO_DONE.value,
                PipelineCheckpoint.IMAGES_DONE.value,
                PipelineCheckpoint.CLIPS_DONE.value,
                PipelineCheckpoint.RENDERED.value
            ]
            current_idx = checkpoint_order.index(job.checkpoint) if job.checkpoint in checkpoint_order else 0
            required_idx = checkpoint_order.index(required_checkpoint) if required_checkpoint in checkpoint_order else 0
            return current_idx >= required_idx

        # Helper classes for script compatibility (defined once)
        class ScriptCompat:
            def __init__(self, data, segments_list):
                self.title = data["title"]
                self.hook = data["hook"]
                self.segments = segments_list
                self.cta = data["cta"]
                self.total_duration = data["total_duration"]
                self.visual_keywords = data["visual_keywords"]
                self.background_music_mood = data["background_music_mood"]
                self.topic = data.get("topic", "")

        class SegmentCompat:
            def __init__(self, seg_data):
                self.text = seg_data["text"]
                self.duration = seg_data["duration"]
                self.visual_prompt = seg_data["visual_prompt"]
                self.visual_keywords = seg_data.get("visual_keywords", [])
                self.emotion = seg_data.get("emotion", "neutral")
                self.segment_type = seg_data.get("segment_type", "content")
                self.camera_direction = seg_data.get("camera_direction", "static")
                self.lighting_mood = seg_data.get("lighting_mood", "cinematic")

        try:
            # ═══════════════════════════════════════════════════════════════
            # Step 1: MULTI-AGENT SCRIPT GENERATION (0-15%)
            # Agent 1 (Storyteller) + Agent 2 (Visual Director)
            # ═══════════════════════════════════════════════════════════════
            if should_skip(PipelineCheckpoint.SCRIPT_DONE.value):
                # SKIP - Script already exists
                logger.info(f"[RESUME] Skipping script generation - already done")
                await self._update_progress(job, JobStatus.GENERATING_SCRIPT, 15, "⏭️ Сценарий уже готов (resume)")
                segment_objects = [SegmentCompat(s) for s in job.script["segments"]]
                script = ScriptCompat(job.script, segment_objects)
            else:
                await self._update_progress(job, JobStatus.GENERATING_SCRIPT, 2, "🎬 Запуск Multi-Agent системы...")

                # Map style string to AgentScriptStyle enum
                try:
                    agent_style = AgentScriptStyle(job.style.lower())
                except ValueError:
                    agent_style = AgentScriptStyle.DOCUMENTARY
                    logger.warning(f"Unknown style '{job.style}', defaulting to DOCUMENTARY")

                # Check if using custom idea
                if job.custom_idea:
                    await self._update_progress(job, JobStatus.GENERATING_SCRIPT, 5, f"🤖 Agent 1: Обработка вашей идеи ({job.idea_mode})...")
                    logger.info(f"[CUSTOM_IDEA] Processing user idea in '{job.idea_mode}' mode")
                else:
                    await self._update_progress(job, JobStatus.GENERATING_SCRIPT, 5, f"🤖 Agent 1: Генерация {agent_style.value.upper()} истории...")

                # Use Multi-Agent Orchestrator for script generation
                orchestrated = await self.orchestrator.orchestrate_script_generation(
                    topic=job.topic,
                    style=agent_style,
                    language=job.language,
                    duration_seconds=job.duration,
                    art_style=job.art_style,
                    custom_idea=job.custom_idea,
                    idea_mode=job.idea_mode
                )

                await self._update_progress(job, JobStatus.GENERATING_SCRIPT, 12, "🎨 Agent 2: Сегментация и визуальные промпты...")

                # Convert orchestrated result to legacy format for backward compatibility
                job.script = self.orchestrator.convert_to_legacy_format(orchestrated)

                segment_objects = [SegmentCompat(s) for s in job.script["segments"]]
                script = ScriptCompat(job.script, segment_objects)

                # Track if fallback was used
                if orchestrated.used_fallback_story or orchestrated.used_fallback_segments:
                    job.used_fallback_script = True
                    job.status_details += "Multi-Agent: "
                    if orchestrated.used_fallback_story:
                        job.status_details += "Fallback story used. "
                    if orchestrated.used_fallback_segments:
                        job.status_details += "Fallback segments used. "

                # PERSIST script to database for editor access (also sets checkpoint)
                self.db.update_job_script(
                    job_id=job.job_id,
                    script=job.script,
                    used_fallback=job.used_fallback_script
                )
                logger.info(f"[MULTI-AGENT] Script persisted to database for job {job.job_id}")
                logger.info(f"[MULTI-AGENT] Style: {agent_style.value}, Segments: {len(script.segments)}")
                logger.info(f"[MULTI-AGENT] Visual consistency: {orchestrated.style_consistency_string[:50]}...")

                await self._update_progress(job, JobStatus.GENERATING_SCRIPT, 15, f"✅ Сценарий готов: {script.title}")

            # ═══════════════════════════════════════════════════════════════
            # Step 2 & 3: PARALLEL Generation of Audio + Images
            # Audio and Images are independent - run them simultaneously!
            # This saves ~30-40% of total generation time
            # ═══════════════════════════════════════════════════════════════

            skip_audio = should_skip(PipelineCheckpoint.AUDIO_DONE.value)
            skip_images = should_skip(PipelineCheckpoint.IMAGES_DONE.value)

            # Prepare visual prompts first (needed for images)
            visual_prompts = []
            if not skip_images:
                for seg in job.script["segments"]:
                    if seg.get("visual_prompt"):
                        visual_prompts.append(seg["visual_prompt"])
                    else:
                        keywords = ", ".join(seg.get("visual_keywords", [job.topic]))
                        emotion = seg.get("emotion", "cinematic")
                        visual_prompts.append(
                            f"Cinematic photorealistic scene depicting {keywords}, "
                            f"{emotion} atmosphere, professional lighting, 8K resolution, "
                            f"documentary style, no text or words"
                        )
                job.visual_prompts = visual_prompts
            else:
                visual_prompts = job.visual_prompts

            # Define async tasks
            async def generate_audio_task():
                """Generate TTS audio."""
                if skip_audio:
                    logger.info(f"[RESUME] Skipping audio generation - already done")
                    return None

                self.tts.voice = job.voice
                full_text = " ".join([s.text for s in script.segments])
                audio_path = str(job_dir / "narration.mp3")

                tts_result = await self.tts.generate_audio(full_text, audio_path)

                # Save word timings for subtitles
                words_path = str(job_dir / "words.json")
                with open(words_path, 'w', encoding='utf-8') as f:
                    json.dump([
                        {"word": w.word, "start": w.start, "end": w.end}
                        for w in tts_result.words
                    ], f, ensure_ascii=False, indent=2)

                return tts_result

            async def generate_images_task():
                """Generate AI images using selected provider (DALL-E or Nano Banana)."""
                if skip_images:
                    logger.info(f"[RESUME] Skipping images generation - already done")
                    return None

                # Use factory function to get the appropriate image service
                from app.services.nanobanana_service import get_image_service
                image_service = get_image_service(job.image_provider)
                logger.info(f"[IMAGE] Using provider: {job.image_provider}")

                generated_images = await image_service.generate_images_for_segments(
                    segments=job.script["segments"],
                    visual_prompts=visual_prompts,
                    output_dir=str(images_dir),
                    video_format=job.format,
                    topic=job.topic
                )

                # Close the service if it has a close method
                if hasattr(image_service, 'close'):
                    await image_service.close()

                return generated_images

            # Run both tasks in parallel!
            if not skip_audio and not skip_images:
                await self._update_progress(job, JobStatus.GENERATING_AUDIO, 20, "🚀 Параллельная генерация: Аудио + Изображения...")
                logger.info("[PARALLEL] Starting Audio + Images generation simultaneously")

                tts_result, generated_images = await asyncio.gather(
                    generate_audio_task(),
                    generate_images_task()
                )

                logger.info("[PARALLEL] Both tasks completed!")

            elif not skip_audio:
                await self._update_progress(job, JobStatus.GENERATING_AUDIO, 20, "🎙️ Генерация озвучки...")
                tts_result = await generate_audio_task()
                generated_images = None

            elif not skip_images:
                await self._update_progress(job, JobStatus.GENERATING_VISUALS, 38, "🖼️ Генерация AI-изображений с DALL-E 3...")
                tts_result = None
                generated_images = await generate_images_task()

            else:
                # Both skipped (resume case)
                tts_result = None
                generated_images = None

            # Process audio result
            if tts_result:
                job.audio_path = tts_result.audio_path
                job.audio_duration = tts_result.duration
                self.db.update_job_audio(
                    job_id=job.job_id,
                    audio_path=job.audio_path,
                    audio_duration=job.audio_duration
                )
                logger.info(f"Audio persisted: {job.audio_duration:.1f}s")
            elif skip_audio:
                await self._update_progress(job, JobStatus.GENERATING_AUDIO, 30, f"⏭️ Озвучка уже готова (resume): {job.audio_duration:.1f}с")

            # Process images result
            if generated_images:
                job.image_paths = [img.image_path for img in generated_images]

                # Verify images
                missing_images = []
                for idx, img_path in enumerate(job.image_paths):
                    if not os.path.exists(img_path):
                        missing_images.append(f"Image {idx}: {img_path}")
                    elif os.path.getsize(img_path) == 0:
                        missing_images.append(f"Image {idx} (empty): {img_path}")

                if missing_images:
                    raise Exception(f"Cannot proceed: {len(missing_images)} images missing or empty")

                # Check fallbacks
                fallback_count = sum(1 for img in generated_images if "[fallback" in img.prompt)
                if fallback_count > 0:
                    job.used_fallback_visuals = True
                    job.api_limit_reached = True

                self.db.update_job_visuals(
                    job_id=job.job_id,
                    visual_prompts=job.visual_prompts,
                    image_paths=job.image_paths,
                    used_fallback=job.used_fallback_visuals,
                    api_limit_reached=job.api_limit_reached
                )
                logger.info(f"Images persisted: {len(job.image_paths)} images")

            elif skip_images:
                await self._update_progress(job, JobStatus.GENERATING_VISUALS, 60, f"⏭️ Изображения уже готовы (resume): {len(job.image_paths)} шт")

            # Update progress after parallel generation completes
            if tts_result and generated_images:
                await self._update_progress(job, JobStatus.GENERATING_VISUALS, 60, f"✅ Параллельная генерация завершена: аудио {job.audio_duration:.1f}с + {len(job.image_paths)} изображений")

            # ═══════════════════════════════════════════════════════════════
            # Step 5: Ken Burns Animation (60-80%)
            # ═══════════════════════════════════════════════════════════════
            if should_skip(PipelineCheckpoint.CLIPS_DONE.value):
                # SKIP - Clips already exist
                logger.info(f"[RESUME] Skipping Ken Burns animation - already done")
                await self._update_progress(job, JobStatus.ANIMATING_VISUALS, 80, f"⏭️ Анимация уже готова (resume): {len(job.clip_paths)} клипов")
                animated_clips = []  # Will be loaded from clip_paths
                for clip_path in job.clip_paths:
                    animated_clips.append(AnimatedClip(clip_path=clip_path, duration=0, effect=KenBurnsEffect.ZOOM_IN))
            else:
                await self._update_progress(job, JobStatus.ANIMATING_VISUALS, 62, "🎬 Анимация изображений (Ken Burns эффект)...")

                # Calculate durations for each segment based on audio timing
                segment_durations = self._calculate_segment_durations(
                    job.script["segments"],
                    job.audio_duration
                )

                logger.info(f"Animating {len(job.image_paths)} images with durations: {segment_durations}")

                animated_clips = await self.ken_burns.animate_images_for_segments(
                    image_paths=job.image_paths,
                    segment_durations=segment_durations,
                    output_dir=str(clips_dir),
                    output_width=job.width,
                    output_height=job.height
                )

                job.clip_paths = [clip.clip_path for clip in animated_clips]

                # PERSIST clip paths to database (also sets checkpoint)
                self.db.update_job_clips(job.job_id, job.clip_paths)

                # Validate we have clips - if not, create fallback black video
                if not animated_clips:
                    logger.warning("⚠️ No clips created - using fallback black video")
                    await self._update_progress(job, JobStatus.ANIMATING_VISUALS, 75, "⚠️ Создание запасного видео...")
                    concat_video_path = str(job_dir / "concat_video.mp4")
                    await self._create_fallback_video(concat_video_path, job.audio_duration, job.width, job.height)
                else:
                    await self._update_progress(job, JobStatus.ANIMATING_VISUALS, 80, f"✅ Анимировано {len(animated_clips)} клипов")

            # ═══════════════════════════════════════════════════════════════
            # Step 6: Final Render with Audio & Subtitles (80-100%)
            # ═══════════════════════════════════════════════════════════════
            await self._update_progress(job, JobStatus.RENDERING, 82, "🎥 Финальный рендеринг видео...")

            # Concatenate animated clips (only if we have clips)
            concat_video_path = str(job_dir / "concat_video.mp4")
            if animated_clips:
                await self.ken_burns.concatenate_clips(animated_clips, concat_video_path)

            await self._update_progress(job, JobStatus.RENDERING, 88, "📝 Добавление субтитров...")

            # Render final video with audio and subtitles
            output_path = str(job_dir / "final.mp4")
            await self._render_final_video(job, concat_video_path, output_path)

            job.output_path = output_path

            await self._update_progress(job, JobStatus.RENDERING, 95, "✨ Финализация...")

            # Complete - set appropriate message based on what happened
            job.status = JobStatus.COMPLETED
            job.progress = 100
            job.completed_at = datetime.utcnow().isoformat()

            # Set completion message based on fallback status
            if job.api_limit_reached:
                job.progress_message = "Video ready (with fallback visuals due to API limit)"
            elif job.used_fallback_visuals:
                job.progress_message = "Video ready (using fallback images)"
            elif job.used_fallback_script:
                job.progress_message = "Video ready (using fallback script)"
            else:
                job.progress_message = "AI video ready!"

            # PERSIST completion to database
            self.db.complete_job(
                job_id=job.job_id,
                output_path=output_path,
                status_details=job.status_details
            )

            # PERSIST segments for editor integration
            if job.script and "segments" in job.script:
                self.db.save_segments(
                    job_id=job.job_id,
                    segments=job.script["segments"],
                    image_paths=job.image_paths or []
                )
                logger.info(f"Saved {len(job.script['segments'])} segments for editor")

            logger.info(f"Job {job.job_id} completed and persisted to database")

            # ═══════════════════════════════════════════════════════════════
            # TOTAL COST ESTIMATION
            # ═══════════════════════════════════════════════════════════════
            num_images = len(job.image_paths) if job.image_paths else 0
            # Count non-fallback images (actual API calls)
            actual_dalle_calls = sum(1 for img in generated_images if "[fallback" not in img.prompt and "[reused]" not in img.prompt)
            reused_count = sum(1 for img in generated_images if "[reused]" in img.prompt)

            # Cost calculation (optimized settings)
            dalle_cost = actual_dalle_calls * 0.04  # Standard 1024x1024
            gpt_cost = 0.04  # ~2 GPT-4o calls (story + segments)
            total_cost = dalle_cost + gpt_cost

            logger.info("=" * 70)
            logger.info("ESTIMATED COST FOR THIS VIDEO")
            logger.info("=" * 70)
            logger.info(f"  GPT-4o (script generation): $0.04")
            logger.info(f"  DALL-E 3 ({actual_dalle_calls} images x $0.04): ${dalle_cost:.2f}")
            logger.info(f"  Images reused (saved): {reused_count} (saved ${reused_count * 0.04:.2f})")
            logger.info(f"  Fallback images (free): {num_images - actual_dalle_calls - reused_count}")
            logger.info("-" * 70)
            logger.info(f"  TOTAL ESTIMATED COST: ${total_cost:.2f}")
            logger.info("=" * 70)

            await self._notify_progress(job)

            # Cleanup temporary files (keep final video)
            await self.cleanup_job(job.job_id, keep_final=True)

        except Exception as e:
            logger.error(f"Faceless pipeline failed for {job.job_id}: {e}")
            import traceback
            traceback.print_exc()
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.progress_message = f"Error: {str(e)}"

            # PERSIST failure to database
            self.db.fail_job(job.job_id, str(e))
            logger.error(f"Job {job.job_id} failed and persisted to database")

            await self._notify_progress(job)

    def _calculate_segment_durations(
        self,
        segments: List[Dict[str, Any]],
        total_audio_duration: float
    ) -> List[float]:
        """
        Calculate duration for each segment based on script and audio.
        Ensures total matches audio duration.
        """
        # Get script-specified durations
        script_durations = [seg.get("duration", 5.0) for seg in segments]
        total_script_duration = sum(script_durations)

        # Scale to match audio duration
        if total_script_duration > 0:
            scale_factor = total_audio_duration / total_script_duration
            durations = [d * scale_factor for d in script_durations]
        else:
            # Equal distribution
            durations = [total_audio_duration / len(segments)] * len(segments)

        # Ensure minimum duration per segment
        min_duration = 3.0
        durations = [max(d, min_duration) for d in durations]

        return durations

    async def _render_final_video(
        self,
        job: FacelessJob,
        video_path: str,
        output_path: str
    ):
        """
        Render final video with audio overlay and burned-in subtitles.
        Uses synchronous subprocess.run to avoid Windows asyncio issues.
        """
        job_dir = Path(output_path).parent

        # Get subtitle style
        style = SUBTITLE_STYLES.get(job.subtitle_style, SUBTITLE_STYLES["hormozi"])

        # Generate ASS subtitles from words
        words_path = job_dir / "words.json"
        ass_path = job_dir / "subtitles.ass"

        if words_path.exists():
            await self._generate_ass_subtitles(words_path, ass_path, style, job.width, job.height)

        # Build FFmpeg command
        filter_parts = []

        # Add subtitles if available
        if ass_path.exists():
            ass_path_escaped = str(ass_path).replace('\\', '/').replace(':', '\\:')
            filter_parts.append(f"ass='{ass_path_escaped}'")

        filter_str = ",".join(filter_parts) if filter_parts else "copy"

        cmd = [
            FFMPEG_PATH, "-y",
            "-i", video_path,
            "-i", job.audio_path,
            "-filter_complex", f"[0:v]{filter_str}[vout]",
            "-map", "[vout]",
            "-map", "1:a",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(job.audio_duration),
            "-shortest",
            output_path
        ]

        logger.info("Rendering final video with audio and subtitles...")

        # Use synchronous subprocess.run to avoid Windows asyncio issues
        import subprocess
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            logger.error(f"Final render failed: {result.stderr}")
            # Try simple merge as fallback
            await self._simple_final_render(job, video_path, output_path)

    async def _simple_final_render(
        self,
        job: FacelessJob,
        video_path: str,
        output_path: str
    ):
        """Simple fallback render without subtitles. Uses synchronous subprocess."""
        logger.info("Using simple render fallback...")

        cmd = [
            FFMPEG_PATH, "-y",
            "-i", video_path,
            "-i", job.audio_path,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "libx264",
            "-preset", "fast",
            "-c:a", "aac",
            "-t", str(job.audio_duration),
            "-shortest",
            output_path
        ]

        import subprocess
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            logger.error(f"Simple final render also failed: {result.stderr}")
            raise Exception("Failed to render final video")

    async def _create_fallback_video(
        self,
        output_path: str,
        duration: float,
        width: int,
        height: int
    ):
        """Create a fallback black video when all animations fail. Uses synchronous subprocess."""
        logger.info(f"Creating fallback black video: {duration}s @ {width}x{height}")

        cmd = [
            FFMPEG_PATH, "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s={width}x{height}:r=30:d={duration + 1}",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-t", str(duration + 1),
            output_path
        ]

        import subprocess
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            logger.error(f"Failed to create fallback video: {result.stderr}")
            raise Exception("Failed to create fallback video")

        logger.info(f"Fallback video created: {output_path}")

    # Legacy method kept for compatibility - no longer used in main pipeline
    async def _render_video_legacy(self, job: FacelessJob, output_path: str):
        """Render the final video using FFmpeg."""
        job_dir = Path(output_path).parent
        concat_footage_path = job_dir / "concat_footage.mp4"

        # Get subtitle style
        style = SUBTITLE_STYLES.get(job.subtitle_style, SUBTITLE_STYLES["hormozi"])

        # Generate ASS subtitles from words
        words_path = job_dir / "words.json"
        ass_path = job_dir / "subtitles.ass"

        if words_path.exists():
            await self._generate_ass_subtitles(words_path, ass_path, style, job.width, job.height)

        # First, prepare video source
        if job.footage_paths:
            # Concatenate and scale footage clips
            footage_list_path = job_dir / "footage_list.txt"
            with open(footage_list_path, 'w', encoding='utf-8') as f:
                for path in job.footage_paths:
                    # Use forward slashes for FFmpeg compatibility
                    clean_path = path.replace('\\', '/')
                    f.write(f"file '{clean_path}'\n")

            # Concatenate footage with scaling to target resolution
            cmd = [
                FFMPEG_PATH, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(footage_list_path),
                "-vf", f"scale={job.width}:{job.height}:force_original_aspect_ratio=decrease,pad={job.width}:{job.height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-an",  # No audio from footage
                str(concat_footage_path)
            ]

            logger.info(f"Concatenating {len(job.footage_paths)} footage clips...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode != 0 or not concat_footage_path.exists():
                logger.warning(f"Footage concat failed: {result.stderr}, using fallback")
                job.footage_paths = []  # Fall through to create black video

        # If no footage or concat failed, create a black video
        if not job.footage_paths or not concat_footage_path.exists():
            logger.info(f"Creating black video background for {job.audio_duration}s")
            cmd = [
                FFMPEG_PATH, "-y",
                "-f", "lavfi",
                "-i", f"color=c=black:s={job.width}x{job.height}:r=30:d={job.audio_duration + 1}",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-t", str(job.audio_duration + 1),
                str(concat_footage_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                logger.error(f"Failed to create black video: {result.stderr}")
                raise Exception("Failed to create background video")

        # Now render final video with audio and subtitles
        # Use stream_loop to loop the video if needed
        filter_complex = []

        # Loop video to match audio duration
        filter_complex.append(f"[0:v]loop=-1:size=32767,setpts=N/FRAME_RATE/TB[v1]")

        # Add subtitles
        if ass_path.exists():
            # Escape path for FFmpeg filter
            ass_path_escaped = str(ass_path).replace('\\', '/').replace(':', '\\:')
            filter_complex.append(f"[v1]ass='{ass_path_escaped}'[vout]")
        else:
            filter_complex.append("[v1]copy[vout]")

        filter_str = ";".join(filter_complex)

        cmd = [
            FFMPEG_PATH, "-y",
            "-i", str(concat_footage_path),
            "-i", job.audio_path,
            "-filter_complex", filter_str,
            "-map", "[vout]",
            "-map", "1:a",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(job.audio_duration),
            "-shortest",
            output_path
        ]

        logger.info("Rendering final video with subtitles...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            logger.error(f"FFmpeg render failed: {result.stderr}")
            # Try simpler render as fallback
            await self._simple_render(job, output_path)

    async def _simple_render(self, job: FacelessJob, output_path: str):
        """Simple fallback render without complex filters. Uses synchronous subprocess."""
        job_dir = Path(output_path).parent
        concat_footage_path = job_dir / "concat_footage.mp4"

        # Use existing concat footage if available, otherwise create black video
        if concat_footage_path.exists():
            input_video = str(concat_footage_path)
        elif job.footage_paths:
            input_video = job.footage_paths[0]
        else:
            # Create black video
            black_video = job_dir / "black.mp4"
            cmd = [
                FFMPEG_PATH, "-y",
                "-f", "lavfi",
                "-i", f"color=c=black:s={job.width}x{job.height}:r=30:d={job.audio_duration + 1}",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-t", str(job.audio_duration + 1),
                str(black_video)
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            input_video = str(black_video)

        # Simple combine with loop to match audio duration
        logger.info(f"Simple render: combining {input_video} with {job.audio_path}")
        cmd = [
            FFMPEG_PATH, "-y",
            "-stream_loop", "-1",  # Loop video
            "-i", input_video,
            "-i", job.audio_path,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "libx264",
            "-preset", "fast",
            "-c:a", "aac",
            "-t", str(job.audio_duration),
            "-shortest",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            logger.error(f"Simple render also failed: {result.stderr}")

    async def _generate_ass_subtitles(
        self,
        words_path: Path,
        ass_path: Path,
        style: SubtitleStyle,
        width: int,
        height: int
    ):
        """Generate ASS subtitles with Hormozi-style formatting."""
        with open(words_path, 'r', encoding='utf-8') as f:
            words = json.load(f)

        # ASS header
        ass_content = f"""[Script Info]
Title: Generated Subtitles
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font_family},{style.font_size},&H00{style.primary_color[1:]},&H00{style.secondary_color[1:]},&H00{style.outline_color[1:]},&H80000000,1,0,0,0,100,100,0,0,1,{style.outline_width},2,5,10,10,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        # Group words into phrases (3-5 words each)
        phrases = []
        current_phrase = []

        for word in words:
            current_phrase.append(word)
            if len(current_phrase) >= 4 or word['word'].endswith(('.', '!', '?', ',')):
                if current_phrase:
                    phrases.append(current_phrase)
                    current_phrase = []

        if current_phrase:
            phrases.append(current_phrase)

        # Generate dialogue lines
        for phrase in phrases:
            if not phrase:
                continue

            start = phrase[0]['start']
            end = phrase[-1]['end']
            text = ' '.join([w['word'] for w in phrase])

            # Convert to ASS time format
            start_time = self._seconds_to_ass_time(start)
            end_time = self._seconds_to_ass_time(end)

            # Add animation effect based on style
            effect = ""
            if style.animation == "pop":
                effect = "{\\fscx110\\fscy110\\t(0,100,\\fscx100\\fscy100)}"
            elif style.animation == "fade":
                effect = "{\\alpha&HFF&\\t(0,200,\\alpha&H00&)}"
            elif style.animation == "glow":
                effect = "{\\blur5\\t(0,300,\\blur0)}"
            elif style.animation == "scale":
                effect = "{\\fscx80\\fscy80\\t(0,150,\\fscx100\\fscy100)}"

            ass_content += f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{effect}{text}\n"

        with open(ass_path, 'w', encoding='utf-8') as f:
            f.write(ass_content)

    def _seconds_to_ass_time(self, seconds: float) -> str:
        """Convert seconds to ASS time format (H:MM:SS.CC)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}:{minutes:02d}:{secs:05.2f}"

    async def _update_progress(
        self,
        job: FacelessJob,
        status: JobStatus,
        progress: float,
        message: str
    ):
        """Update job progress and persist to database."""
        job.status = status
        job.progress = progress
        job.progress_message = message

        # PERSIST progress to database
        self.db.update_job_status(
            job_id=job.job_id,
            status=status.value,
            progress=progress,
            progress_message=message
        )

        await self._notify_progress(job)

    async def _notify_progress(self, job: FacelessJob):
        """Notify progress via callback if set."""
        if self.progress_callback:
            try:
                self.progress_callback(job.job_id, job.progress, job.progress_message)
            except Exception as e:
                logger.error(f"Progress callback failed: {e}")

    def _get_dimensions(self, format: str) -> tuple:
        """Get width and height from format string."""
        dimensions = {
            "9:16": (1080, 1920),
            "1:1": (1080, 1080),
            "16:9": (1920, 1080),
        }
        return dimensions.get(format, (1080, 1920))

    def get_job(self, job_id: str) -> Optional[FacelessJob]:
        """Get job by ID. Checks memory first, then database."""
        # Check memory first
        if job_id in self._jobs:
            return self._jobs[job_id]

        # Load from database if not in memory
        db_record = self.db.get_job(job_id)
        if db_record:
            # Reconstruct FacelessJob from database record
            job = self._db_record_to_job(db_record)
            self._jobs[job_id] = job  # Cache in memory
            return job

        return None

    def _db_record_to_job(self, record: FacelessJobRecord) -> FacelessJob:
        """Convert database record to FacelessJob object."""
        import json

        # Parse JSON fields
        script = None
        if record.script_json:
            try:
                script = json.loads(record.script_json)
            except:
                pass

        image_paths = []
        if record.image_paths_json:
            try:
                image_paths = json.loads(record.image_paths_json)
            except:
                pass

        clip_paths = []
        if record.clip_paths_json:
            try:
                clip_paths = json.loads(record.clip_paths_json)
            except:
                pass

        return FacelessJob(
            job_id=record.job_id,
            topic=record.topic,
            status=JobStatus(record.status),
            progress=record.progress,
            progress_message=record.progress_message,
            created_at=record.created_at,
            completed_at=record.completed_at,
            style=record.style,
            language=record.language,
            voice=record.voice,
            duration=record.duration,
            format=record.format,
            width=record.width,
            height=record.height,
            subtitle_style=record.subtitle_style,
            script=script,
            audio_path=record.audio_path,
            audio_duration=record.audio_duration,
            image_paths=image_paths,
            clip_paths=clip_paths,
            output_path=record.output_path,
            error=record.error,
            used_fallback_script=record.used_fallback_script,
            used_fallback_visuals=record.used_fallback_visuals,
            api_limit_reached=record.api_limit_reached,
            status_details=record.status_details
        )

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job status as dict. Loads from database if not in memory."""
        job = self.get_job(job_id)  # Use get_job which checks both memory and DB
        if not job:
            return None

        # Build image URLs for UI display
        image_urls = []
        images_dir = FACELESS_DIR / job_id / "images"
        temp_images_dir = Path(r"C:\dake\data\temp_images") / job_id

        # Check both possible image locations
        for check_dir in [images_dir, temp_images_dir]:
            if check_dir.exists():
                for img_path in sorted(check_dir.glob("*.png")):
                    if "temp_images" in str(check_dir):
                        image_urls.append(f"/data/temp_images/{job_id}/{img_path.name}")
                    else:
                        image_urls.append(f"/data/faceless/{job_id}/images/{img_path.name}")
                break  # Use first found location

        # Build video URL
        video_url = None
        if job.output_path and job.status == JobStatus.COMPLETED:
            video_url = f"/data/faceless/{job_id}/final.mp4"

        return {
            "job_id": job.job_id,
            "topic": job.topic,
            "status": job.status.value,
            "progress": job.progress,
            "progress_message": job.progress_message,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "output_path": job.output_path,
            "video_url": video_url,
            "error": job.error,
            "script": job.script,
            "audio_duration": job.audio_duration,
            # Image URLs for preview
            "image_urls": image_urls,
            # New status flags for UI
            "used_fallback_script": job.used_fallback_script,
            "used_fallback_visuals": job.used_fallback_visuals,
            "api_limit_reached": job.api_limit_reached,
            "status_details": job.status_details,
        }

    def list_jobs(self, limit: int = 20, user_id: str = None) -> List[Dict[str, Any]]:
        """List recent jobs from database."""
        # Load from database for persistence across restarts
        if user_id:
            db_records = self.db.get_user_jobs(user_id, limit=limit)
        else:
            db_records = self.db.get_all_jobs(limit=limit)

        # Convert to API response format
        return [self.db.to_api_response(record) for record in db_records]

    async def close(self):
        """Close all services."""
        await self.llm.close()
        await self.dalle.close()
        await self.prompt_generator.close()

    async def cleanup_job(self, job_id: str, keep_final: bool = True):
        """
        Cleanup temporary files for a job.

        Args:
            job_id: Job ID to cleanup
            keep_final: If True, keep the final.mp4, delete only temp files
        """
        job_dir = FACELESS_DIR / job_id
        if not job_dir.exists():
            return

        temp_patterns = [
            "*.json",  # word timings
            "*.ass",   # subtitles
            "*.txt",   # footage/clip list
            "narration.mp3",  # TTS audio
            "concat_footage.mp4",  # intermediate footage
            "concat_video.mp4",  # concatenated AI clips
            "black.mp4",  # fallback video
        ]

        # Delete temp folders (clips, footage) - keep images for preview
        import shutil
        for folder_name in ["clips", "footage"]:
            folder_dir = job_dir / folder_name
            if folder_dir.exists():
                shutil.rmtree(folder_dir, ignore_errors=True)

        # Delete temp files
        for pattern in temp_patterns:
            for f in job_dir.glob(pattern):
                try:
                    f.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete {f}: {e}")

        if not keep_final:
            # Delete entire job directory
            import shutil
            shutil.rmtree(job_dir, ignore_errors=True)

        logger.info(f"Cleaned up job {job_id}")

    async def cleanup_old_jobs(self, max_age_hours: int = 24):
        """
        Cleanup jobs older than max_age_hours.
        """
        from datetime import datetime, timedelta

        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)

        for job_id, job in list(self._jobs.items()):
            try:
                created = datetime.fromisoformat(job.created_at)
                if created < cutoff and job.status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                    await self.cleanup_job(job_id, keep_final=False)
                    del self._jobs[job_id]
            except Exception as e:
                logger.error(f"Failed to cleanup old job {job_id}: {e}")


# Global engine instance
_engine: Optional[FacelessEngine] = None


def get_faceless_engine() -> FacelessEngine:
    """Get or create the global faceless engine instance."""
    global _engine
    if _engine is None:
        _engine = FacelessEngine()
    return _engine
