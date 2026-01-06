"""
Text-to-Video Mode Orchestrator.

Handles the workflow for generating videos from text scripts:
1. Accept text script input
2. Generate TTS audio from text (via provider)
3. Extract word-level timestamps
4. Match/generate background visuals
5. Build render job for the pipeline
"""
from typing import Any, Dict

from .base import BaseOrchestrator, OrchestrationResult
from .enums import OrchestrationMode
from app.rendering.pipeline import TextToVideoPipeline, PipelineConfig


class TextModeOrchestrator(BaseOrchestrator):
    """
    Orchestrator for text-to-video generation.

    Input: Text script, voice settings, visual preferences
    Output: Render job with TTS audio, timestamps, and scenes
    """

    def __init__(self):
        super().__init__()
        self._pipeline = None

    def _get_mode(self) -> OrchestrationMode:
        """Return TEXT mode."""
        return OrchestrationMode.TEXT

    def _get_pipeline(self, config: PipelineConfig) -> TextToVideoPipeline:
        """Get or create pipeline with config."""
        return TextToVideoPipeline(config)

    def validate_request(self, request: Dict[str, Any]) -> None:
        """
        Validate text-to-video request.

        Required fields:
        - script_text: str (min 10 chars)

        Optional fields:
        - voice_id: str (TTS voice identifier)
        - visual_style: str (cinematic, minimal, etc.)
        - resolution: dict (width, height)
        - fps: int

        Raises:
            ValueError: If required fields missing or invalid
        """
        script_text = request.get("script_text", "")

        if not script_text:
            raise ValueError("script_text is required")

        if len(script_text) < 10:
            raise ValueError("script_text must be at least 10 characters")

        if len(script_text) > 10000:
            raise ValueError("script_text must be at most 10000 characters")

    def build_render_job(self, request: Dict[str, Any]) -> OrchestrationResult:
        """
        Build render job from text script.

        Steps:
        1. Extract script_text and settings from request
        2. Call TTS provider: text -> audio + word timestamps
        3. Fetch background assets for scenes
        4. Build script JSON with scenes array
        5. Build timestamps JSON with word timings
        6. Return OrchestrationResult

        Args:
            request: Validated request with script_text and options

        Returns:
            OrchestrationResult with complete render job
        """
        self.validate_request(request)

        script_text = request["script_text"]
        visual_style = request.get("visual_style", "cinematic")
        lang = request.get("lang", "ru")

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

        config = PipelineConfig(
            width=width,
            height=height,
            fps=fps,
            lang=lang,
            subtitle_font_size=subtitle_font_size,
            subtitle_color=subtitle_color,
            subtitle_active_color=subtitle_active_color,
        )

        pipeline = self._get_pipeline(config)

        job_id = request.get("job_id")
        result = pipeline.prepare(
            text=script_text,
            job_id=job_id,
            style=visual_style,
            lang=lang,
        )

        render_job = result.to_celery_kwargs()

        metadata = {
            "input_text_length": len(script_text),
            "visual_style": visual_style,
            "language": lang,
            "resolution": f"{width}x{height}",
            "fps": fps,
            "audio_path": result.audio_path,
        }

        return OrchestrationResult(
            mode=self.mode,
            render_job=render_job,
            metadata=metadata,
            estimated_duration_seconds=result.total_duration,
            estimated_cost_credits=1,
        )
