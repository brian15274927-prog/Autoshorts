"""
Music-to-Clip Mode Orchestrator.

Handles the workflow for generating music videos/clips:
1. Accept audio track (music file)
2. Analyze audio for beats, energy, structure
3. Generate visuals synchronized to music
4. Build render job with beat-synced scenes
"""
import os
from typing import Any, Dict

from .base import BaseOrchestrator, OrchestrationResult
from .enums import OrchestrationMode
from app.rendering.music_pipeline import MusicToClipPipeline, MusicPipelineConfig


class MusicModeOrchestrator(BaseOrchestrator):
    """
    Orchestrator for music-to-clip video generation.

    Input: Audio file (music), visual style preferences
    Output: Render job with beat-synced visuals
    """

    def __init__(self):
        super().__init__()
        self._pipeline = None

    def _get_mode(self) -> OrchestrationMode:
        """Return MUSIC mode."""
        return OrchestrationMode.MUSIC

    def _get_pipeline(self, config: MusicPipelineConfig) -> MusicToClipPipeline:
        """Get or create pipeline with config."""
        return MusicToClipPipeline(config)

    def validate_request(self, request: Dict[str, Any]) -> None:
        """
        Validate music-to-clip request.

        Required fields:
        - audio_path: str (path to music file)

        Optional fields:
        - style: str (motivation, cinematic, dark, abstract, random)
        - clip_length: float (8-30 seconds)
        - clip_start: float (start time in audio)
        - resolution: dict (width, height)
        - fps: int

        Raises:
            ValueError: If required fields missing or invalid
        """
        audio_path = request.get("audio_path")

        if not audio_path:
            raise ValueError("audio_path is required")

        if not os.path.exists(audio_path):
            raise ValueError(f"Audio file not found: {audio_path}")

        clip_length = request.get("clip_length", 10.0)
        if clip_length < 3.0:
            raise ValueError("clip_length must be at least 3 seconds")
        if clip_length > 60.0:
            raise ValueError("clip_length must be at most 60 seconds")

        clip_start = request.get("clip_start", 0.0)
        if clip_start < 0:
            raise ValueError("clip_start must be >= 0")

    def build_render_job(self, request: Dict[str, Any]) -> OrchestrationResult:
        """
        Build render job from music track.

        Steps:
        1. Load audio file from path
        2. Detect beats using energy analysis
        3. Select/generate visuals for beat-synced scenes
        4. Time scene transitions to beat grid
        5. Build script JSON with beat-synced scenes
        6. Return OrchestrationResult

        Args:
            request: Validated request with audio and options

        Returns:
            OrchestrationResult with complete render job
        """
        self.validate_request(request)

        audio_path = request["audio_path"]
        style = request.get("style", "cinematic")
        clip_length = request.get("clip_length", 10.0)
        clip_start = request.get("clip_start", 0.0)

        resolution = request.get("resolution", {})
        width = resolution.get("width", 1080)
        height = resolution.get("height", 1920)
        fps = request.get("fps", 30)

        config = MusicPipelineConfig(
            width=width,
            height=height,
            fps=fps,
            clip_length=clip_length,
            style=style,
        )

        pipeline = self._get_pipeline(config)

        job_id = request.get("job_id")
        result = pipeline.prepare(
            audio_path=audio_path,
            job_id=job_id,
            style=style,
            clip_length=clip_length,
            clip_start=clip_start,
        )

        render_job = result.to_celery_kwargs()

        metadata = {
            "audio_path": audio_path,
            "style": style,
            "clip_length": result.clip_duration,
            "clip_start": clip_start,
            "resolution": f"{width}x{height}",
            "fps": fps,
            "beats_detected": result.beats_count,
            "tempo_bpm": result.tempo_bpm,
            "scenes_count": result.scenes_count,
        }

        return OrchestrationResult(
            mode=self.mode,
            render_job=render_job,
            metadata=metadata,
            estimated_duration_seconds=result.clip_duration,
            estimated_cost_credits=1,
        )
