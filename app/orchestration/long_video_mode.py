"""
Long Video → Shorts Mode Orchestrator.

Handles the workflow for converting long videos to multiple short clips:
1. Accept long video file
2. Segment video into clips based on silence/content
3. Crop each clip to vertical 9:16
4. Generate subtitles for each clip
5. Return batch of render jobs
"""
import os
from typing import Any, Dict, List

from .base import BaseOrchestrator, OrchestrationResult
from .enums import OrchestrationMode
from app.rendering.long_video_pipeline import (
    LongToShortsPipeline,
    LongVideoPipelineConfig,
    LongVideoPipelineResult,
)


class LongVideoModeOrchestrator(BaseOrchestrator):
    """
    Orchestrator for long video → shorts conversion.

    Input: Long video file (horizontal or vertical)
    Output: Batch of render jobs for multiple short clips
    """

    def __init__(self):
        super().__init__()
        self._pipeline = None

    def _get_mode(self) -> OrchestrationMode:
        """Return LONG mode."""
        return OrchestrationMode.LONG

    def _get_pipeline(self, config: LongVideoPipelineConfig) -> LongToShortsPipeline:
        """Get or create pipeline with config."""
        return LongToShortsPipeline(config)

    def validate_request(self, request: Dict[str, Any]) -> None:
        """
        Validate long video request.

        Required fields:
        - video_path: str (path to source video)

        Optional fields:
        - clip_length: float (target clip duration, default 15s)
        - max_clips: int (maximum clips to generate, default 5)
        - style: str (education, podcast, motivation, etc.)
        - resolution: dict (width, height)
        - fps: int
        - subtitles: dict (font_size, color, etc.)

        Raises:
            ValueError: If required fields missing or invalid
        """
        video_path = request.get("video_path")

        if not video_path:
            raise ValueError("video_path is required")

        if not os.path.exists(video_path):
            raise ValueError(f"Video file not found: {video_path}")

    def build_render_job(self, request: Dict[str, Any]) -> OrchestrationResult:
        """
        Build batch of render jobs from long video.

        Steps:
        1. Load and analyze video file
        2. Segment into clips based on silence/content
        3. Crop each segment to vertical
        4. Generate subtitles for each clip
        5. Build render job for each clip
        6. Return OrchestrationResult with batch info

        Args:
            request: Validated request with video and options

        Returns:
            OrchestrationResult with batch render job data
        """
        self.validate_request(request)

        video_path = request["video_path"]
        style = request.get("style", "education")

        clip_length = request.get("clip_length", 15.0)
        max_clips = request.get("max_clips", 5)
        min_clip_length = request.get("min_clip_length", 8.0)
        max_clip_length = request.get("max_clip_length", 60.0)

        resolution = request.get("resolution", {})
        width = resolution.get("width", 1080)
        height = resolution.get("height", 1920)
        fps = request.get("fps", 30)

        subtitles = request.get("subtitles", {})
        subtitle_font_size = 70
        subtitle_color = "white"
        subtitle_active_color = "#FFD700"

        if subtitles:
            size_map = {"small": 50, "medium": 70, "large": 90}
            subtitle_font_size = size_map.get(subtitles.get("size", "medium"), 70)

        generate_srt = subtitles.get("enabled", True) if subtitles else True

        config = LongVideoPipelineConfig(
            width=width,
            height=height,
            fps=fps,
            clip_length=clip_length,
            max_clips=max_clips,
            min_clip_length=min_clip_length,
            max_clip_length=max_clip_length,
            style=style,
            generate_srt=generate_srt,
            subtitle_font_size=subtitle_font_size,
            subtitle_color=subtitle_color,
            subtitle_active_color=subtitle_active_color,
        )

        pipeline = self._get_pipeline(config)

        batch_id = request.get("batch_id")
        result = pipeline.prepare(
            video_path=video_path,
            batch_id=batch_id,
            style=style,
        )

        render_jobs = self._build_batch_jobs(result)

        metadata = {
            "video_path": video_path,
            "style": style,
            "source_duration": result.source_duration,
            "clips_count": result.clips_count,
            "resolution": f"{width}x{height}",
            "fps": fps,
            "clip_length_target": clip_length,
            "clips": [
                {
                    "clip_id": clip.clip_id,
                    "clip_index": clip.clip_index,
                    "start": clip.start,
                    "end": clip.end,
                    "duration": round(clip.end - clip.start, 3),
                }
                for clip in result.clips
            ],
        }

        total_duration = sum(
            clip.end - clip.start for clip in result.clips
        )

        return OrchestrationResult(
            mode=self.mode,
            render_job=render_jobs,
            metadata=metadata,
            estimated_duration_seconds=total_duration,
            estimated_cost_credits=result.clips_count,
        )

    def _build_batch_jobs(
        self, result: LongVideoPipelineResult
    ) -> Dict[str, Any]:
        """Build batch render jobs from pipeline result."""
        return {
            "batch_id": result.batch_id,
            "source_video_path": result.source_video_path,
            "source_duration": result.source_duration,
            "clips_count": result.clips_count,
            "clips": [
                clip.to_celery_kwargs(result.config)
                for clip in result.clips
            ],
        }
