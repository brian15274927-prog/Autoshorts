"""
Video Assembler - Clean video assembly using MoviePy.

Provides high-level functions for creating videos from images and audio.
Uses MoviePy for cleaner code and better effects handling.
"""

import os
import logging
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VideoSegment:
    """A segment for video assembly."""
    image_path: str
    duration: float


@dataclass
class AssemblyResult:
    """Result of video assembly."""
    success: bool
    output_path: Optional[str] = None
    error: Optional[str] = None


def assemble_slideshow(
    segments: List[VideoSegment],
    audio_path: str,
    output_path: str,
    resolution: Tuple[int, int] = (1080, 1920),
    fps: int = 25,
    zoom_effect: bool = True,
    zoom_ratio: float = 0.04
) -> AssemblyResult:
    """
    Assemble a slideshow video from images with audio.

    Args:
        segments: List of VideoSegment with image paths and durations
        audio_path: Path to audio file
        output_path: Output video path
        resolution: Video resolution (width, height)
        fps: Frames per second
        zoom_effect: Apply Ken Burns zoom effect
        zoom_ratio: Zoom amount (0.04 = 4% zoom over duration)

    Returns:
        AssemblyResult with success status and output path
    """
    try:
        from moviepy.editor import (
            ImageClip,
            AudioFileClip,
            concatenate_videoclips,
            CompositeVideoClip
        )
        import numpy as np

        width, height = resolution
        clips = []

        logger.info(f"[VIDEO_ASSEMBLER] Creating slideshow: {len(segments)} segments")

        for i, segment in enumerate(segments):
            if not segment.image_path or not os.path.exists(segment.image_path):
                logger.warning(f"[VIDEO_ASSEMBLER] Skipping missing image: {segment.image_path}")
                continue

            # Create image clip
            clip = ImageClip(segment.image_path)

            # Resize to fit resolution while maintaining aspect ratio
            clip = resize_to_fill(clip, width, height)

            # Set duration
            clip = clip.set_duration(segment.duration)

            # Apply Ken Burns zoom effect
            if zoom_effect:
                clip = apply_ken_burns(clip, zoom_ratio)

            clips.append(clip)
            logger.debug(f"[VIDEO_ASSEMBLER] Added segment {i}: {segment.duration:.2f}s")

        if not clips:
            return AssemblyResult(success=False, error="No valid image segments")

        # Concatenate all clips
        logger.info("[VIDEO_ASSEMBLER] Concatenating clips...")
        video = concatenate_videoclips(clips, method="compose")

        # Add audio
        logger.info("[VIDEO_ASSEMBLER] Adding audio track...")
        audio = AudioFileClip(audio_path)

        # Match video duration to audio
        if video.duration > audio.duration:
            video = video.subclip(0, audio.duration)

        video = video.set_audio(audio)

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Write final video
        logger.info(f"[VIDEO_ASSEMBLER] Writing video to {output_path}")
        video.write_videofile(
            output_path,
            fps=fps,
            codec='libx264',
            audio_codec='aac',
            audio_bitrate='192k',
            preset='medium',
            threads=4,
            logger=None  # Suppress MoviePy's verbose output
        )

        # Cleanup
        video.close()
        audio.close()
        for clip in clips:
            clip.close()

        logger.info(f"[VIDEO_ASSEMBLER] Video created successfully: {output_path}")
        return AssemblyResult(success=True, output_path=output_path)

    except Exception as e:
        logger.error(f"[VIDEO_ASSEMBLER] Assembly failed: {e}")
        return AssemblyResult(success=False, error=str(e))


def resize_to_fill(clip, target_width: int, target_height: int):
    """
    Resize clip to fill target dimensions, cropping if necessary.
    Maintains aspect ratio and centers the image.
    """
    from moviepy.editor import CompositeVideoClip

    # Get original dimensions
    orig_width, orig_height = clip.size

    # Calculate scale to fill (cover) the target
    scale_w = target_width / orig_width
    scale_h = target_height / orig_height
    scale = max(scale_w, scale_h)

    # Resize
    new_width = int(orig_width * scale)
    new_height = int(orig_height * scale)
    clip = clip.resize((new_width, new_height))

    # Crop to exact target size (centered)
    x_center = new_width / 2
    y_center = new_height / 2

    x1 = int(x_center - target_width / 2)
    y1 = int(y_center - target_height / 2)

    clip = clip.crop(x1=x1, y1=y1, width=target_width, height=target_height)

    return clip


def apply_ken_burns(clip, zoom_ratio: float = 0.04):
    """
    Apply Ken Burns (slow zoom) effect to a clip.

    Args:
        clip: MoviePy clip
        zoom_ratio: Total zoom amount (0.04 = zoom from 100% to 104%)

    Returns:
        Clip with zoom effect applied
    """
    width, height = clip.size
    duration = clip.duration

    def zoom_effect(get_frame, t):
        """Apply progressive zoom."""
        # Calculate zoom factor: starts at 1.0, ends at 1.0 + zoom_ratio
        progress = t / duration if duration > 0 else 0
        zoom = 1.0 + (zoom_ratio * progress)

        frame = get_frame(t)

        # Calculate new dimensions
        new_w = int(width * zoom)
        new_h = int(height * zoom)

        # Resize frame
        from PIL import Image
        import numpy as np

        img = Image.fromarray(frame)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        # Crop back to original size (centered)
        left = (new_w - width) // 2
        top = (new_h - height) // 2
        img = img.crop((left, top, left + width, top + height))

        return np.array(img)

    return clip.fl(zoom_effect)


def add_audio_to_video(
    video_path: str,
    audio_path: str,
    output_path: str
) -> AssemblyResult:
    """
    Add or replace audio track in a video.

    Args:
        video_path: Path to input video
        audio_path: Path to audio file
        output_path: Output video path

    Returns:
        AssemblyResult with success status
    """
    try:
        from moviepy.editor import VideoFileClip, AudioFileClip

        logger.info(f"[VIDEO_ASSEMBLER] Adding audio to video")

        video = VideoFileClip(video_path)
        audio = AudioFileClip(audio_path)

        # Match durations
        final_duration = min(video.duration, audio.duration)
        video = video.subclip(0, final_duration)
        audio = audio.subclip(0, final_duration)

        video = video.set_audio(audio)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        video.write_videofile(
            output_path,
            codec='libx264',
            audio_codec='aac',
            audio_bitrate='192k',
            preset='medium',
            logger=None
        )

        video.close()
        audio.close()

        return AssemblyResult(success=True, output_path=output_path)

    except Exception as e:
        logger.error(f"[VIDEO_ASSEMBLER] Add audio failed: {e}")
        return AssemblyResult(success=False, error=str(e))


def extract_audio(
    video_path: str,
    output_path: str,
    sample_rate: int = 44100
) -> AssemblyResult:
    """
    Extract audio track from video.

    Args:
        video_path: Path to input video
        output_path: Output audio path
        sample_rate: Audio sample rate

    Returns:
        AssemblyResult with success status
    """
    try:
        from moviepy.editor import VideoFileClip

        logger.info(f"[VIDEO_ASSEMBLER] Extracting audio from {video_path}")

        video = VideoFileClip(video_path)

        if video.audio is None:
            return AssemblyResult(success=False, error="Video has no audio track")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        video.audio.write_audiofile(
            output_path,
            fps=sample_rate,
            logger=None
        )

        video.close()

        return AssemblyResult(success=True, output_path=output_path)

    except Exception as e:
        logger.error(f"[VIDEO_ASSEMBLER] Extract audio failed: {e}")
        return AssemblyResult(success=False, error=str(e))


def create_video_thumbnail(
    video_path: str,
    output_path: str,
    time_offset: float = 1.0,
    size: Tuple[int, int] = (320, 180)
) -> AssemblyResult:
    """
    Create thumbnail from video frame.

    Args:
        video_path: Path to input video
        output_path: Output image path
        time_offset: Time in seconds to capture frame
        size: Thumbnail size (width, height)

    Returns:
        AssemblyResult with success status
    """
    try:
        from moviepy.editor import VideoFileClip

        video = VideoFileClip(video_path)

        # Clamp time offset to video duration
        t = min(time_offset, video.duration - 0.1)
        t = max(0, t)

        # Get frame
        frame = video.get_frame(t)

        # Convert to PIL and resize
        from PIL import Image
        img = Image.fromarray(frame)
        img.thumbnail(size, Image.LANCZOS)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path, 'JPEG', quality=85)

        video.close()

        return AssemblyResult(success=True, output_path=output_path)

    except Exception as e:
        logger.error(f"[VIDEO_ASSEMBLER] Thumbnail failed: {e}")
        return AssemblyResult(success=False, error=str(e))
