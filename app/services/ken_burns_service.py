"""
Ken Burns Service - Image Animation with Zoom/Pan Effects.
Converts static DALL-E images into dynamic video clips.
"""
import sys
import asyncio

# CRITICAL: Windows asyncio fix - MUST be at very top before any other asyncio usage
if sys.platform == 'win32':
    try:
        from asyncio import WindowsProactorEventLoopPolicy
        asyncio.set_event_loop_policy(WindowsProactorEventLoopPolicy())
    except (ImportError, AttributeError):
        pass

import os
import logging
import random
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class KenBurnsEffect(str, Enum):
    """Available Ken Burns animation effects."""
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    PAN_UP = "pan_up"
    PAN_DOWN = "pan_down"
    ZOOM_IN_PAN_RIGHT = "zoom_in_pan_right"
    ZOOM_OUT_PAN_LEFT = "zoom_out_pan_left"


@dataclass
class AnimatedClip:
    """Animated video clip from a static image."""
    clip_path: str
    source_image: str
    duration: float
    effect: KenBurnsEffect
    width: int
    height: int


def get_ffmpeg_path() -> str:
    """Get FFmpeg executable path - prioritize local installation."""
    local_paths = [
        r"C:\dake\tools\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]

    for path in local_paths:
        if os.path.exists(path):
            logger.info(f"Found local FFmpeg: {path}")
            return path

    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(ffmpeg_path):
            logger.info(f"Using imageio-ffmpeg: {ffmpeg_path}")
            return ffmpeg_path
    except ImportError:
        pass

    logger.warning("Using system FFmpeg from PATH")
    return "ffmpeg"


FFMPEG_PATH = get_ffmpeg_path()
logger.info(f"Ken Burns Service initialized with FFmpeg: {FFMPEG_PATH}")


class KenBurnsService:
    """
    Ken Burns Animation Service.
    Converts static images into dynamic video clips with zoom/pan effects.
    Uses synchronous subprocess.run to avoid Windows asyncio issues.
    """

    def __init__(self, fps: int = 30, default_duration: float = 5.0):
        self.fps = fps
        self.default_duration = default_duration
        logger.info(f"KenBurnsService initialized (FPS: {fps}, FFmpeg: {FFMPEG_PATH})")

    def _get_zoom_filter(
        self,
        effect: KenBurnsEffect,
        duration: float,
        input_width: int,
        input_height: int,
        output_width: int,
        output_height: int
    ) -> str:
        """
        Generate FFmpeg zoompan filter for Ken Burns effect.
        STABILIZED: Reduced zoom factors and strictly linear interpolation
        to eliminate jitter and handheld camera shake.
        """
        total_frames = int(duration * self.fps)

        # STABILIZATION: Use very gentle zoom increments for smooth motion
        # Max zoom reduced from 1.5 to 1.12 for cinematic smoothness
        zoom_increment = 0.12 / total_frames  # Exactly 12% zoom over duration
        pan_distance = 0.08  # Reduced from 0.3 to 0.08 for subtle pan

        if effect == KenBurnsEffect.ZOOM_IN:
            # Gentle zoom in - strictly linear, centered
            zoom_expr = f"1+on*{zoom_increment}"
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih/2-(ih/zoom/2)"

        elif effect == KenBurnsEffect.ZOOM_OUT:
            # Gentle zoom out - start at 1.12, end at 1.0
            zoom_expr = f"1.12-on*{zoom_increment}"
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih/2-(ih/zoom/2)"

        elif effect == KenBurnsEffect.PAN_LEFT:
            # Subtle pan left with slight zoom for depth
            zoom_expr = "1.08"
            pan_per_frame = pan_distance / total_frames
            x_expr = f"iw*{pan_distance}-on*{pan_per_frame}*iw"
            y_expr = "ih/2-(ih/zoom/2)"

        elif effect == KenBurnsEffect.PAN_RIGHT:
            # Subtle pan right with slight zoom for depth
            zoom_expr = "1.08"
            pan_per_frame = pan_distance / total_frames
            x_expr = f"on*{pan_per_frame}*iw"
            y_expr = "ih/2-(ih/zoom/2)"

        elif effect == KenBurnsEffect.PAN_UP:
            # Subtle pan up - good for vertical video
            zoom_expr = "1.08"
            pan_per_frame = pan_distance / total_frames
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = f"ih*{pan_distance}-on*{pan_per_frame}*ih"

        elif effect == KenBurnsEffect.PAN_DOWN:
            # Subtle pan down - good for vertical video
            zoom_expr = "1.08"
            pan_per_frame = pan_distance / total_frames
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = f"on*{pan_per_frame}*ih"

        elif effect == KenBurnsEffect.ZOOM_IN_PAN_RIGHT:
            # Combined effect - very subtle for stability
            zoom_expr = f"1+on*{zoom_increment * 0.8}"
            pan_per_frame = (pan_distance * 0.6) / total_frames
            x_expr = f"on*{pan_per_frame}*iw"
            y_expr = "ih/2-(ih/zoom/2)"

        elif effect == KenBurnsEffect.ZOOM_OUT_PAN_LEFT:
            # Combined effect - very subtle for stability
            zoom_expr = f"1.10-on*{zoom_increment * 0.8}"
            pan_per_frame = (pan_distance * 0.6) / total_frames
            x_expr = f"iw*{pan_distance*0.6}-on*{pan_per_frame}*iw"
            y_expr = "ih/2-(ih/zoom/2)"

        else:
            # Default: gentle zoom in
            zoom_expr = f"1+on*{zoom_increment}"
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih/2-(ih/zoom/2)"

        filter_str = (
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
            f"d={total_frames}:s={output_width}x{output_height}:fps={self.fps}"
        )

        return filter_str

    def _animate_image_sync(
        self,
        image_path: str,
        output_path: str,
        duration: float,
        effect: KenBurnsEffect,
        output_width: int,
        output_height: int
    ) -> Optional[AnimatedClip]:
        """
        Synchronous image animation using subprocess.run.
        This avoids Windows asyncio issues entirely.
        """
        if not os.path.exists(image_path):
            logger.error(f"[STOP] ERROR: Image NOT FOUND - STOPPING")
            logger.error(f"[STOP] Path checked: {image_path}")
            return None

        # Normalize paths for FFmpeg
        image_path_normalized = image_path.replace('\\', '/')
        output_path_normalized = output_path.replace('\\', '/')

        input_width = 1024
        input_height = 1792

        zoom_filter = self._get_zoom_filter(
            effect, duration,
            input_width, input_height,
            output_width, output_height
        )

        cmd = [
            FFMPEG_PATH, "-y",
            "-loop", "1",
            "-i", image_path_normalized,
            "-vf", zoom_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-t", str(duration),
            output_path_normalized
        ]

        logger.info(f"Ken Burns animation: {effect.value}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode != 0:
                logger.error(f"Ken Burns animation failed (exit code {result.returncode})")
                logger.error(f"FFmpeg stderr: {result.stderr[:1000]}")

                # Try simpler fallback
                logger.info("Trying simple scale animation as fallback...")
                if not self._simple_animate_sync(
                    image_path_normalized, output_path_normalized,
                    duration, output_width, output_height
                ):
                    return None

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"Animation complete: {Path(output_path).name} ({os.path.getsize(output_path)} bytes)")
                return AnimatedClip(
                    clip_path=output_path,
                    source_image=image_path,
                    duration=duration,
                    effect=effect,
                    width=output_width,
                    height=output_height
                )
            else:
                logger.error(f"Output file not created or empty: {output_path}")
                return None

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg animation timed out")
            return None
        except Exception as e:
            logger.error(f"Animation exception: {e}")
            return None

    def _simple_animate_sync(
        self,
        image_path: str,
        output_path: str,
        duration: float,
        width: int,
        height: int
    ) -> bool:
        """Simple fallback animation without zoompan."""
        cmd = [
            FFMPEG_PATH, "-y",
            "-loop", "1",
            "-i", image_path,
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-t", str(duration),
            output_path
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                logger.error(f"Simple animation also failed: {result.stderr[:500]}")
                return False

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"Simple animation succeeded: {Path(output_path).name}")
                return True
            return False

        except subprocess.TimeoutExpired:
            logger.error("Simple animation timed out")
            return False
        except Exception as e:
            logger.error(f"Simple animation exception: {e}")
            return False

    def _concatenate_clips_sync(
        self,
        clips: List[AnimatedClip],
        output_path: str
    ) -> str:
        """
        Synchronous clip concatenation using subprocess.run.
        """
        valid_clips = []
        for clip in clips:
            if os.path.exists(clip.clip_path) and os.path.getsize(clip.clip_path) > 0:
                valid_clips.append(clip)
            else:
                logger.warning(f"Skipping missing/empty clip: {clip.clip_path}")

        if not valid_clips:
            raise ValueError("No valid clips to concatenate")

        logger.info(f"Concatenating {len(valid_clips)} clips...")

        if len(valid_clips) == 1:
            shutil.copy(valid_clips[0].clip_path, output_path)
            logger.info(f"Single clip copied to: {output_path}")
            return output_path

        list_path = output_path.replace('.mp4', '_list.txt')
        with open(list_path, 'w', encoding='utf-8') as f:
            for clip in valid_clips:
                clean_path = clip.clip_path.replace('\\', '/')
                f.write(f"file '{clean_path}'\n")

        cmd = [
            FFMPEG_PATH, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_path.replace('\\', '/'),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            output_path.replace('\\', '/')
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode != 0:
                logger.error(f"Concatenation failed: {result.stderr[:1000]}")
                raise Exception(f"Failed to concatenate clips: {result.stderr[:200]}")

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"Concatenation complete: {output_path} ({os.path.getsize(output_path)} bytes)")
            else:
                raise Exception("Concatenated output file is missing or empty")

        finally:
            try:
                if os.path.exists(list_path):
                    os.remove(list_path)
            except:
                pass

        return output_path

    # Async wrappers that call synchronous methods
    async def animate_image(
        self,
        image_path: str,
        output_path: str,
        duration: float,
        effect: Optional[KenBurnsEffect] = None,
        output_width: int = 1080,
        output_height: int = 1920
    ) -> Optional[AnimatedClip]:
        """
        Convert a static image to an animated video clip with Ken Burns effect.
        Returns None if animation fails completely.
        """
        if effect is None:
            effect = random.choice(list(KenBurnsEffect))

        # Run in thread pool to not block event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._animate_image_sync,
            image_path, output_path, duration, effect, output_width, output_height
        )

    async def animate_images_for_segments(
        self,
        image_paths: List[str],
        segment_durations: List[float],
        output_dir: str,
        output_width: int = 1080,
        output_height: int = 1920
    ) -> List[AnimatedClip]:
        """
        Animate multiple images with Ken Burns effects.
        Returns only successfully animated clips.
        """
        os.makedirs(output_dir, exist_ok=True)

        logger.info(f"Starting Ken Burns animation for {len(image_paths)} images")
        logger.info(f"   Output directory: {output_dir}")
        logger.info(f"   Output resolution: {output_width}x{output_height}")

        effects = [
            KenBurnsEffect.ZOOM_IN,
            KenBurnsEffect.ZOOM_OUT,
            KenBurnsEffect.ZOOM_IN_PAN_RIGHT,
            KenBurnsEffect.PAN_LEFT,
            KenBurnsEffect.ZOOM_OUT_PAN_LEFT,
            KenBurnsEffect.PAN_RIGHT,
        ]

        results = []

        # Process sequentially to avoid FFmpeg conflicts
        for idx, (image_path, duration) in enumerate(zip(image_paths, segment_durations)):
            output_path = os.path.join(output_dir, f"clip_{idx:03d}.mp4")
            effect = effects[idx % len(effects)]

            logger.info(f"Processing image {idx + 1}/{len(image_paths)}: {Path(image_path).name}")

            # Use synchronous method via executor
            clip = self._animate_image_sync(
                image_path,
                output_path,
                duration,
                effect,
                output_width,
                output_height
            )

            if clip is not None:
                results.append(clip)
            else:
                logger.warning(f"Skipping failed animation for image {idx}")

        logger.info(f"Ken Burns complete: {len(results)}/{len(image_paths)} clips created")

        if not results:
            logger.error("No clips were created - all animations failed!")

        return results

    async def concatenate_clips(
        self,
        clips: List[AnimatedClip],
        output_path: str,
        crossfade_duration: float = 0.3
    ) -> str:
        """
        Concatenate animated clips into a single video.
        """
        # Use synchronous method
        return self._concatenate_clips_sync(clips, output_path)
