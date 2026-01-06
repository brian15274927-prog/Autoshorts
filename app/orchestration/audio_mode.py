"""
Audio-to-Video Mode Orchestrator.

Handles the workflow for generating videos from existing audio:
1. Accept pre-recorded audio (voiceover, podcast, etc.)
2. Extract timestamps from audio
3. Generate visuals based on style
4. Build render job with synced subtitles
"""
import os
from typing import Any, Dict

from .base import BaseOrchestrator, OrchestrationResult
from .enums import OrchestrationMode
from app.rendering.audio_pipeline import AudioToVideoPipeline, AudioPipelineConfig


class AudioModeOrchestrator(BaseOrchestrator):
    """
    Orchestrator for audio-to-video generation.

    Input: Audio file (speech/voiceover), optional transcript
    Output: Render job with subtitles and visuals synced to audio
    """

    def __init__(self):
        super().__init__()
        self._pipeline = None

    def _get_mode(self) -> OrchestrationMode:
        """Return AUDIO mode."""
        return OrchestrationMode.AUDIO

    def _get_pipeline(self, config: AudioPipelineConfig) -> AudioToVideoPipeline:
        """Get or create pipeline with config."""
        return AudioToVideoPipeline(config)

    def validate_request(self, request: Dict[str, Any]) -> None:
        """
        Validate audio-to-video request.

        Required fields:
        - audio_path: str (path to audio file)

        Optional fields:
        - transcript_text: str (for better subtitle alignment)
        - style: str (podcast, motivation, news, education, story, random)
        - resolution: dict (width, height)
        - fps: int
        - subtitles: dict (font_size, color, etc.)

        Raises:
            ValueError: If required fields missing or invalid
        """
        audio_path = request.get("audio_path")

        if not audio_path:
            raise ValueError("audio_path is required")

        if not os.path.exists(audio_path):
            raise ValueError(f"Audio file not found: {audio_path}")

    def build_render_job(self, request: Dict[str, Any]) -> OrchestrationResult:
        """
        Build render job from audio file.

        Steps:
        1. Load audio file
        2. Extract timestamps using provider
        3. Select background visuals based on style
        4. Build scenes covering audio duration
        5. Build subtitle timeline from timestamps
        6. Return OrchestrationResult

        Args:
            request: Validated request with audio and options

        Returns:
            OrchestrationResult with complete render job
        """
        self.validate_request(request)

        audio_path = request["audio_path"]
        style = request.get("style", "podcast")
        transcript_text = request.get("transcript_text")

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

        config = AudioPipelineConfig(
            width=width,
            height=height,
            fps=fps,
            style=style,
            generate_srt=generate_srt,
            subtitle_font_size=subtitle_font_size,
            subtitle_color=subtitle_color,
            subtitle_active_color=subtitle_active_color,
        )

        pipeline = self._get_pipeline(config)

        job_id = request.get("job_id")
        result = pipeline.prepare(
            audio_path=audio_path,
            job_id=job_id,
            style=style,
            transcript_text=transcript_text,
        )

        render_job = result.to_celery_kwargs()

        metadata = {
            "audio_path": audio_path,
            "style": style,
            "has_transcript": transcript_text is not None,
            "resolution": f"{width}x{height}",
            "fps": fps,
            "duration": result.total_duration,
            "scenes_count": result.scenes_count,
            "words_count": result.words_count,
        }

        return OrchestrationResult(
            mode=self.mode,
            render_job=render_job,
            metadata=metadata,
            estimated_duration_seconds=result.total_duration,
            estimated_cost_credits=1,
        )
