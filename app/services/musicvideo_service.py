"""
Music Video Generator Service - Creates AI-generated music videos.

Flow:
1. User uploads audio + provides theme/lyrics
2. Analyze audio (duration, optionally transcribe)
3. AI creates visual concept based on theme/lyrics
4. Generate images for each segment
5. Assemble video with Ken Burns effect + audio overlay
6. Return final music video
"""

import os
import sys
import asyncio
import logging
import uuid
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

# Windows asyncio fix
if sys.platform == 'win32':
    try:
        from asyncio import WindowsProactorEventLoopPolicy
        asyncio.set_event_loop_policy(WindowsProactorEventLoopPolicy())
    except (ImportError, AttributeError):
        pass

from .audio_analyzer import AudioAnalyzer, AudioAnalysis
from .agents.story_analyzer import StoryAnalyzer, VisualBible
from .agents.visual_director import VisualDirector, ART_STYLE_PROMPTS
from .nanobanana_service import NanoBananaService, get_image_service
from .video_assembler import assemble_slideshow, VideoSegment as AssemblerSegment, AssemblyResult

logger = logging.getLogger(__name__)

# Output directories
MUSICVIDEO_OUTPUT_DIR = Path(r"C:\dake\data\musicvideo")
MUSICVIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_ffmpeg_path() -> str:
    """Get FFmpeg executable path."""
    local_paths = [
        r"C:\dake\tools\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe",
        r"C:\dake\tools\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]
    for path in local_paths:
        if os.path.exists(path):
            return path
    return "ffmpeg"


FFMPEG_PATH = get_ffmpeg_path()


@dataclass
class MusicVideoSegment:
    """A segment of the music video."""
    index: int
    start_time: float
    end_time: float
    duration: float
    image_prompt: str
    image_path: Optional[str] = None
    visual_description: str = ""


@dataclass
class MusicVideoJob:
    """Music video generation job."""
    job_id: str
    audio_path: str
    theme: str
    lyrics: Optional[str]
    art_style: str
    language: str

    # Analysis results
    audio_analysis: Optional[AudioAnalysis] = None
    visual_bible: Optional[VisualBible] = None

    # Generation results
    segments: List[MusicVideoSegment] = field(default_factory=list)
    output_path: Optional[str] = None

    # Status
    status: str = "pending"
    progress: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "theme": self.theme,
            "art_style": self.art_style,
            "status": self.status,
            "progress": self.progress,
            "output_path": self.output_path,
            "error": self.error,
            "duration": self.audio_analysis.duration_seconds if self.audio_analysis else 0,
            "segment_count": len(self.segments),
        }


# System prompt for music video visual concept
MUSICVIDEO_CONCEPT_PROMPT = """You are a MUSIC VIDEO DIRECTOR creating visual concepts.

Given a theme/description and optionally song lyrics, create a visual story for a music video.

RULES:
1. Create visually STRIKING and CINEMATIC images
2. Each segment should flow naturally to the next
3. Match the MOOD of the music/lyrics
4. Use varied shot types (wide, close-up, atmospheric)
5. Characters should appear in only 30-40% of segments
6. Include abstract/symbolic imagery for emotional impact

OUTPUT FORMAT (JSON):
{
  "concept_title": "Brief title for the video concept",
  "mood": "Overall mood (energetic, melancholic, romantic, etc.)",
  "color_palette": ["color1", "color2", "color3"],
  "visual_style": "Visual style description",

  "segments": [
    {
      "index": 0,
      "visual_prompt": "Detailed DALL-E prompt for this segment",
      "shot_type": "wide/medium/close-up/abstract",
      "mood_shift": "building/climax/resolution/steady"
    }
  ]
}

IMPORTANT:
- visual_prompt must be 40-60 words, highly detailed
- Include lighting, atmosphere, composition details
- NO text, words, or watermarks in images
- Vary between landscape, character, object, and abstract shots
"""


class MusicVideoService:
    """
    Main service for generating AI music videos.
    """

    def __init__(self, api_key: Optional[str] = None):
        from app.config import config
        self.api_key = api_key or config.ai.openai_api_key or ""

        self.audio_analyzer = AudioAnalyzer()
        self.story_analyzer = StoryAnalyzer(api_key=self.api_key)
        self.visual_director = VisualDirector(api_key=self.api_key)

        logger.info("[MUSICVIDEO] Service initialized")

    async def generate_music_video(
        self,
        audio_path: str,
        theme: str,
        lyrics: Optional[str] = None,
        art_style: str = "photorealism",
        language: str = "en",
        image_provider: str = "dalle",
        progress_callback: Optional[callable] = None
    ) -> MusicVideoJob:
        """
        Generate a complete music video.

        Args:
            audio_path: Path to uploaded audio file
            theme: Theme/description for the video
            lyrics: Optional song lyrics for better context
            art_style: Visual art style
            language: Language code
            image_provider: "dalle" or "nanobanana"
            progress_callback: Optional callback for progress updates

        Returns:
            MusicVideoJob with results
        """
        job_id = str(uuid.uuid4())
        job_dir = MUSICVIDEO_OUTPUT_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        job = MusicVideoJob(
            job_id=job_id,
            audio_path=audio_path,
            theme=theme,
            lyrics=lyrics,
            art_style=art_style,
            language=language,
            status="processing"
        )

        def update_progress(progress: int, status: str = None):
            job.progress = progress
            if status:
                job.status = status
            if progress_callback:
                progress_callback(progress, status)
            logger.info(f"[MUSICVIDEO] Progress: {progress}% - {status or job.status}")

        try:
            # ═══════════════════════════════════════════════════════════════
            # PHASE 1: AUDIO ANALYSIS (5%)
            # ═══════════════════════════════════════════════════════════════
            update_progress(5, "analyzing_audio")

            job.audio_analysis = self.audio_analyzer.analyze(audio_path)
            if not job.audio_analysis:
                raise Exception("Failed to analyze audio file")

            duration = job.audio_analysis.duration_seconds
            segment_count = self.audio_analyzer.calculate_segment_count(duration)
            segment_duration = duration / segment_count

            logger.info(f"[MUSICVIDEO] Audio: {duration:.1f}s, {segment_count} segments")

            # ═══════════════════════════════════════════════════════════════
            # PHASE 2: VISUAL CONCEPT GENERATION (15%)
            # ═══════════════════════════════════════════════════════════════
            update_progress(15, "creating_concept")

            # Build context for AI
            context = f"Theme: {theme}\n"
            if lyrics:
                context += f"\nLyrics:\n{lyrics}\n"
            context += f"\nDuration: {duration:.1f} seconds\nSegments: {segment_count}"

            # Generate visual concept
            visual_prompts = await self._generate_visual_concept(
                context=context,
                segment_count=segment_count,
                art_style=art_style,
                language=language
            )

            # Create segments
            job.segments = []
            for i, prompt in enumerate(visual_prompts):
                segment = MusicVideoSegment(
                    index=i,
                    start_time=i * segment_duration,
                    end_time=(i + 1) * segment_duration,
                    duration=segment_duration,
                    image_prompt=prompt
                )
                job.segments.append(segment)

            # ═══════════════════════════════════════════════════════════════
            # PHASE 3: IMAGE GENERATION (15% - 85%)
            # ═══════════════════════════════════════════════════════════════
            update_progress(20, "generating_images")

            image_service = get_image_service(image_provider)
            images_dir = job_dir / "images"
            images_dir.mkdir(exist_ok=True)

            for i, segment in enumerate(job.segments):
                progress = 20 + int((i / len(job.segments)) * 60)
                update_progress(progress, f"generating_image_{i+1}")

                image_path = str(images_dir / f"segment_{i:03d}.png")

                # Add art style to prompt
                art_modifier = ART_STYLE_PROMPTS.get(art_style, ART_STYLE_PROMPTS["photorealism"])
                full_prompt = f"{art_modifier}, {segment.image_prompt}, no text, no words, no watermarks"

                try:
                    result = await image_service.generate_image(
                        prompt=full_prompt,
                        output_path=image_path,
                        size="1024x1792"  # Vertical for TikTok/Reels
                    )

                    if result:
                        segment.image_path = result.image_path
                    else:
                        # Create fallback
                        segment.image_path = self._create_fallback_image(image_path)

                except Exception as e:
                    logger.error(f"[MUSICVIDEO] Image {i} failed: {e}")
                    segment.image_path = self._create_fallback_image(image_path)

            await image_service.close()

            # ═══════════════════════════════════════════════════════════════
            # PHASE 4: VIDEO ASSEMBLY (85% - 95%)
            # ═══════════════════════════════════════════════════════════════
            update_progress(85, "assembling_video")

            output_path = str(job_dir / "music_video.mp4")

            success = await self._assemble_video(
                segments=job.segments,
                audio_path=audio_path,
                output_path=output_path,
                duration=duration
            )

            if not success:
                raise Exception("Failed to assemble video")

            job.output_path = output_path

            # ═══════════════════════════════════════════════════════════════
            # COMPLETE (100%)
            # ═══════════════════════════════════════════════════════════════
            update_progress(100, "completed")
            logger.info(f"[MUSICVIDEO] Complete! Output: {output_path}")

            return job

        except Exception as e:
            logger.error(f"[MUSICVIDEO] Generation failed: {e}")
            job.status = "failed"
            job.error = str(e)
            return job

    async def _generate_visual_concept(
        self,
        context: str,
        segment_count: int,
        art_style: str,
        language: str
    ) -> List[str]:
        """Generate visual prompts for each segment using AI."""
        import httpx
        import json

        if not self.api_key:
            # Fallback prompts
            return self._generate_fallback_prompts(context, segment_count)

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                user_prompt = f"""Create a visual concept for a music video:

{context}

Generate exactly {segment_count} visual segments.
Art style: {art_style}

Return JSON with "segments" array containing {segment_count} items.
Each segment needs a detailed "visual_prompt" for image generation.

Remember:
- Vary shot types (wide landscape, close-up details, abstract, character)
- Characters should only appear in ~30% of segments
- Match the mood and energy of the theme/lyrics
- Create visual storytelling through variety"""

                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": MUSICVIDEO_CONCEPT_PROMPT},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.8,
                        "max_tokens": 3000,
                        "response_format": {"type": "json_object"}
                    }
                )

                if response.status_code != 200:
                    logger.error(f"[MUSICVIDEO] Concept API error: {response.status_code}")
                    return self._generate_fallback_prompts(context, segment_count)

                data = response.json()
                content = data["choices"][0]["message"]["content"]
                concept = json.loads(content)

                prompts = []
                for seg in concept.get("segments", [])[:segment_count]:
                    prompts.append(seg.get("visual_prompt", f"Cinematic scene for {context[:50]}"))

                # Ensure we have enough prompts
                while len(prompts) < segment_count:
                    prompts.append(f"Atmospheric cinematic shot related to {context[:50]}")

                return prompts

        except Exception as e:
            logger.error(f"[MUSICVIDEO] Concept generation failed: {e}")
            return self._generate_fallback_prompts(context, segment_count)

    def _generate_fallback_prompts(self, context: str, segment_count: int) -> List[str]:
        """Generate fallback prompts when API is unavailable."""
        theme = context.split('\n')[0].replace('Theme:', '').strip()[:50]

        shot_types = [
            f"Extreme wide cinematic landscape shot related to {theme}, dramatic lighting",
            f"Close-up detail shot of symbolic object representing {theme}",
            f"Atmospheric moody shot capturing the essence of {theme}",
            f"Bird's eye view panoramic scene related to {theme}",
            f"Silhouette shot with dramatic backlight for {theme}",
            f"Abstract artistic interpretation of {theme}, flowing colors",
            f"Medium shot environmental scene for {theme}",
            f"Low angle dramatic shot representing {theme}",
        ]

        prompts = []
        for i in range(segment_count):
            prompts.append(shot_types[i % len(shot_types)])

        return prompts

    def _create_fallback_image(self, output_path: str) -> str:
        """Create a simple solid color fallback image using PIL or minimal PNG."""
        try:
            # Try to use PIL for fast image creation
            from PIL import Image
            img = Image.new('RGB', (1024, 1792), color=(25, 15, 40))
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            img.save(output_path, 'PNG')
            logger.info(f"[MUSICVIDEO] Created fallback image: {output_path}")
            return output_path
        except ImportError:
            pass

        # Minimal fallback - tiny 1x1 PNG scaled
        import struct
        import zlib

        def create_tiny_png():
            # Simple 16x16 solid color PNG (fast)
            w, h = 16, 16
            r, g, b = 25, 15, 40

            def chunk(ct, data):
                c = ct + data
                return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

            sig = b'\x89PNG\r\n\x1a\n'
            ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))

            row = b'\x00' + bytes([r, g, b]) * w
            raw = row * h
            idat = chunk(b'IDAT', zlib.compress(raw, 1))
            iend = chunk(b'IEND', b'')

            return sig + ihdr + idat + iend

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'wb') as f:
            f.write(create_tiny_png())

        logger.info(f"[MUSICVIDEO] Created minimal fallback image: {output_path}")
        return output_path

    async def _assemble_video(
        self,
        segments: List[MusicVideoSegment],
        audio_path: str,
        output_path: str,
        duration: float
    ) -> bool:
        """
        Assemble final video with images and audio.

        Uses MoviePy for cleaner video assembly with Ken Burns effect.
        Falls back to FFmpeg if MoviePy fails.
        """
        # Convert segments to assembler format
        assembler_segments = []
        for seg in segments:
            if seg.image_path and os.path.exists(seg.image_path):
                assembler_segments.append(AssemblerSegment(
                    image_path=seg.image_path,
                    duration=seg.duration
                ))

        if not assembler_segments:
            logger.error("[MUSICVIDEO] No valid image segments to assemble")
            return False

        # Try MoviePy first (cleaner code, better effects)
        logger.info(f"[MUSICVIDEO] Assembling video with MoviePy ({len(assembler_segments)} segments)...")

        result = assemble_slideshow(
            segments=assembler_segments,
            audio_path=audio_path,
            output_path=output_path,
            resolution=(1080, 1920),
            fps=25,
            zoom_effect=True,
            zoom_ratio=0.04
        )

        if result.success:
            logger.info(f"[MUSICVIDEO] Video assembled with MoviePy: {output_path}")
            return True

        # Fallback to FFmpeg if MoviePy fails
        logger.warning(f"[MUSICVIDEO] MoviePy failed ({result.error}), trying FFmpeg fallback...")
        return await self._assemble_video_ffmpeg(segments, audio_path, output_path, duration)

    async def _assemble_video_ffmpeg(
        self,
        segments: List[MusicVideoSegment],
        audio_path: str,
        output_path: str,
        duration: float
    ) -> bool:
        """FFmpeg fallback for video assembly."""
        try:
            # Create concat file for FFmpeg
            concat_file = Path(output_path).parent / "concat.txt"

            with open(concat_file, 'w') as f:
                for seg in segments:
                    if seg.image_path and os.path.exists(seg.image_path):
                        escaped_path = seg.image_path.replace('\\', '/').replace("'", "'\\''")
                        f.write(f"file '{escaped_path}'\n")
                        f.write(f"duration {seg.duration}\n")

                if segments and segments[-1].image_path:
                    escaped_path = segments[-1].image_path.replace('\\', '/').replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")

            temp_video = Path(output_path).parent / "temp_video.mp4"

            # Create video from images
            cmd1 = [
                FFMPEG_PATH, '-y',
                '-f', 'concat', '-safe', '0',
                '-i', str(concat_file),
                '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2',
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                '-t', str(duration), '-pix_fmt', 'yuv420p',
                str(temp_video)
            ]

            logger.info("[MUSICVIDEO] FFmpeg: Creating slideshow...")
            result1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=300)

            if not temp_video.exists():
                logger.error("[MUSICVIDEO] FFmpeg failed to create temp video")
                return False

            # Add audio
            cmd2 = [
                FFMPEG_PATH, '-y',
                '-i', str(temp_video),
                '-i', audio_path,
                '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                '-shortest', output_path
            ]

            logger.info("[MUSICVIDEO] FFmpeg: Adding audio...")
            subprocess.run(cmd2, capture_output=True, text=True, timeout=120)

            # Cleanup
            temp_video.unlink(missing_ok=True)
            concat_file.unlink(missing_ok=True)

            logger.info(f"[MUSICVIDEO] FFmpeg assembled: {output_path}")
            return os.path.exists(output_path)

        except Exception as e:
            logger.error(f"[MUSICVIDEO] FFmpeg fallback failed: {e}")
            return False

    async def close(self):
        """Close all services."""
        await self.story_analyzer.close()
        await self.visual_director.close()
        logger.info("[MUSICVIDEO] Service closed")
