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

    # In-memory job storage (use Redis in production)
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

    async def create_faceless_video(
        self,
        topic: str,
        style: ScriptStyle = ScriptStyle.VIRAL,
        language: str = "ru",
        voice: str = VoicePreset.RU_MALE_DMITRY,
        duration: int = 60,
        format: str = "9:16",
        subtitle_style: str = "hormozi",
        background_music: bool = True,
        music_volume: float = 0.2
    ) -> str:
        """
        Create a complete faceless video from a topic.

        Args:
            topic: Video topic or keyword
            style: Script style
            language: Output language
            voice: TTS voice preset
            duration: Target duration in seconds
            format: Video format (9:16, 1:1, 16:9)
            subtitle_style: Subtitle style preset
            background_music: Include background music
            music_volume: Background music volume (0-1)

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
            background_music=background_music,
            music_volume=music_volume
        )

        self._jobs[job_id] = job

        # Start generation in background
        asyncio.create_task(self._run_pipeline(job))

        return job_id

    async def _run_pipeline(self, job: FacelessJob):
        """
        Run the complete AI-powered faceless video generation pipeline.

        Pipeline stages:
        1. Generate Script (0-15%) - GPT-4o creates viral script
        2. Generate Audio (15-30%) - edge-tts creates narration
        3. Generate Visual Prompts (30-35%) - GPT-4o creates DALL-E prompts
        4. Generate AI Images (35-60%) - DALL-E 3 creates cinematic visuals
        5. Ken Burns Animation (60-80%) - Animate static images
        6. Final Render (80-100%) - Combine with audio and subtitles
        """
        job_dir = FACELESS_DIR / job.job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        # Create temp directories
        images_dir = job_dir / "images"
        clips_dir = job_dir / "clips"
        images_dir.mkdir(exist_ok=True)
        clips_dir.mkdir(exist_ok=True)

        try:
            # ═══════════════════════════════════════════════════════════════
            # Step 1: Generate Script (0-15%)
            # ═══════════════════════════════════════════════════════════════
            await self._update_progress(job, JobStatus.GENERATING_SCRIPT, 5, "🎬 Генерация сценария с помощью ИИ...")

            script = await self.llm.generate_script(
                topic=job.topic,
                style=ScriptStyle(job.style),
                duration_seconds=job.duration,
                language=job.language
            )

            job.script = {
                "title": script.title,
                "hook": script.hook,
                "segments": [
                    {
                        "text": s.text,
                        "duration": s.duration,
                        "visual_prompt": s.visual_prompt,  # Cinematic DALL-E prompt
                        "visual_keywords": s.visual_keywords,
                        "emotion": s.emotion,
                        "segment_type": s.segment_type,
                        "camera_direction": getattr(s, 'camera_direction', 'static'),
                        "lighting_mood": getattr(s, 'lighting_mood', 'natural')
                    }
                    for s in script.segments
                ],
                "cta": script.cta,
                "total_duration": script.total_duration,
                "visual_keywords": script.visual_keywords,
                "background_music_mood": script.background_music_mood
            }

            # Check if fallback script was used
            if not hasattr(script, 'topic') or "fallback" in str(type(script)).lower():
                job.used_fallback_script = True
                job.status_details += "Used fallback script (API unavailable). "

            await self._update_progress(job, JobStatus.GENERATING_SCRIPT, 15, f"✅ Сценарий готов: {script.title}")

            # ═══════════════════════════════════════════════════════════════
            # Step 2: Generate Audio (15-30%)
            # ═══════════════════════════════════════════════════════════════
            await self._update_progress(job, JobStatus.GENERATING_AUDIO, 20, "🎙️ Генерация озвучки...")

            self.tts.voice = job.voice

            full_text = " ".join([s.text for s in script.segments])
            audio_path = str(job_dir / "narration.mp3")

            tts_result = await self.tts.generate_audio(full_text, audio_path)

            job.audio_path = tts_result.audio_path
            job.audio_duration = tts_result.duration

            # Save word timings for subtitles
            words_path = str(job_dir / "words.json")
            with open(words_path, 'w', encoding='utf-8') as f:
                json.dump([
                    {"word": w.word, "start": w.start, "end": w.end}
                    for w in tts_result.words
                ], f, ensure_ascii=False, indent=2)

            await self._update_progress(job, JobStatus.GENERATING_AUDIO, 30, f"✅ Озвучка готова: {tts_result.duration:.1f}с")

            # ═══════════════════════════════════════════════════════════════
            # Step 3: Extract Visual Prompts from Script (30-35%)
            # ═══════════════════════════════════════════════════════════════
            await self._update_progress(job, JobStatus.GENERATING_VISUALS, 32, "🎨 Подготовка визуальных промптов...")

            # Use visual_prompt from script segments if available (new format)
            # Otherwise fall back to generating with GPT-4o
            visual_prompts = []
            for seg in job.script["segments"]:
                if seg.get("visual_prompt"):
                    visual_prompts.append(seg["visual_prompt"])
                else:
                    # Fallback: generate prompt from keywords
                    keywords = ", ".join(seg.get("visual_keywords", [job.topic]))
                    emotion = seg.get("emotion", "cinematic")
                    visual_prompts.append(
                        f"Cinematic photorealistic scene depicting {keywords}, "
                        f"{emotion} atmosphere, professional lighting, 8K resolution, "
                        f"documentary style, no text or words"
                    )

            # If no prompts extracted, try generating with GPT-4o
            if not visual_prompts or all(not p for p in visual_prompts):
                try:
                    visual_prompts = await self.prompt_generator.generate_prompts(
                        segments=job.script["segments"],
                        overall_theme=job.topic,
                        mood=script.background_music_mood
                    )
                except Exception as e:
                    logger.warning(f"Visual prompt generation failed: {e}, using fallback")
                    visual_prompts = [
                        f"Cinematic scene related to {job.topic}, dramatic lighting, 8K"
                        for _ in job.script["segments"]
                    ]

            job.visual_prompts = visual_prompts

            await self._update_progress(job, JobStatus.GENERATING_VISUALS, 35, f"✅ Подготовлено {len(visual_prompts)} промптов")

            # ═══════════════════════════════════════════════════════════════
            # Step 4: Generate AI Images with DALL-E 3 (35-60%)
            # ═══════════════════════════════════════════════════════════════
            await self._update_progress(job, JobStatus.GENERATING_VISUALS, 38, "🖼️ Генерация AI-изображений с DALL-E 3...")

            generated_images = await self.dalle.generate_images_for_segments(
                segments=job.script["segments"],
                visual_prompts=visual_prompts,
                output_dir=str(images_dir),
                video_format=job.format,
                topic=job.topic  # Pass topic for fallback images
            )

            job.image_paths = [img.image_path for img in generated_images]

            # Check how many images are fallbacks (check for [fallback] in prompt)
            fallback_count = sum(1 for img in generated_images if "[fallback" in img.prompt)
            if fallback_count > 0:
                job.used_fallback_visuals = True
                job.api_limit_reached = True
                job.status_details += f"API Limit Reached - Used {fallback_count} fallback visuals. "
                logger.warning(f"Job {job.job_id}: {fallback_count}/{len(generated_images)} images are fallbacks (API limit)")

            status_msg = f"✅ Создано {len(generated_images)} изображений"
            if fallback_count > 0:
                status_msg += f" ({fallback_count} fallback)"
            await self._update_progress(job, JobStatus.GENERATING_VISUALS, 60, status_msg)

            # ═══════════════════════════════════════════════════════════════
            # Step 5: Ken Burns Animation (60-80%)
            # ═══════════════════════════════════════════════════════════════
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
                job.progress_message = "✅ Видео готово (с fallback-визуалами из-за лимита API)"
            elif job.used_fallback_visuals:
                job.progress_message = "✅ Видео готово (использованы запасные изображения)"
            elif job.used_fallback_script:
                job.progress_message = "✅ Видео готово (использован запасной сценарий)"
            else:
                job.progress_message = "🎉 AI-видео готово!"

            await self._notify_progress(job)

            # Cleanup temporary files (keep final video)
            await self.cleanup_job(job.job_id, keep_final=True)

        except Exception as e:
            logger.error(f"Faceless pipeline failed for {job.job_id}: {e}")
            import traceback
            traceback.print_exc()
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.progress_message = f"❌ Ошибка: {str(e)}"
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
        """Update job progress."""
        job.status = status
        job.progress = progress
        job.progress_message = message
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
        """Get job by ID."""
        return self._jobs.get(job_id)

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job status as dict."""
        job = self._jobs.get(job_id)
        if not job:
            return None

        return {
            "job_id": job.job_id,
            "topic": job.topic,
            "status": job.status.value,
            "progress": job.progress,
            "progress_message": job.progress_message,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "output_path": job.output_path,
            "error": job.error,
            "script": job.script,
            "audio_duration": job.audio_duration,
            # New status flags for UI
            "used_fallback_script": job.used_fallback_script,
            "used_fallback_visuals": job.used_fallback_visuals,
            "api_limit_reached": job.api_limit_reached,
            "status_details": job.status_details,
        }

    def list_jobs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List recent jobs."""
        jobs = sorted(
            self._jobs.values(),
            key=lambda j: j.created_at,
            reverse=True
        )[:limit]

        return [self.get_job_status(j.job_id) for j in jobs]

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

        # Delete temp folders (images, clips, footage)
        import shutil
        for folder_name in ["images", "clips", "footage"]:
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
