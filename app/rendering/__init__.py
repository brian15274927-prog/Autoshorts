"""
Video Rendering Engine Package.

Production-ready video rendering for vertical AI videos.
"""
from .models import (
    SceneType,
    WordTimestamp,
    AudioTimestamps,
    SceneData,
    VideoScript,
    RenderJob,
    RenderProgress,
    RenderResult,
)
from .subtitles import SubtitleEngine, SubtitleStyle, SRTGenerator
from .audio import AudioMixer
from .engine import VideoRenderEngine
from .cost import (
    CostConfig,
    CostCalculator,
    UsageMetrics,
    RenderCostBreakdown,
    calculate_render_cost,
    get_cost_calculator,
)
from .tasks import render_video_task, get_task_status, cancel_task, cleanup_old_outputs
from .pipeline import (
    TextToVideoPipeline,
    PipelineConfig,
    PipelineResult,
    create_pipeline,
)
from .music_pipeline import (
    MusicToClipPipeline,
    MusicPipelineConfig,
    MusicPipelineResult,
    BeatDetector,
    BeatInfo,
    create_music_pipeline,
)
from .audio_pipeline import (
    AudioToVideoPipeline,
    AudioPipelineConfig,
    AudioPipelineResult,
    create_audio_pipeline,
)
from .long_video_pipeline import (
    LongToShortsPipeline,
    LongVideoPipelineConfig,
    LongVideoPipelineResult,
    ClipData,
    VideoSegment,
    SilenceDetector,
    VideoSegmenter,
    create_long_video_pipeline,
)

__all__ = [
    "SceneType",
    "WordTimestamp",
    "AudioTimestamps",
    "SceneData",
    "VideoScript",
    "RenderJob",
    "RenderProgress",
    "RenderResult",
    "SubtitleEngine",
    "SubtitleStyle",
    "SRTGenerator",
    "AudioMixer",
    "VideoRenderEngine",
    "CostConfig",
    "CostCalculator",
    "UsageMetrics",
    "RenderCostBreakdown",
    "calculate_render_cost",
    "get_cost_calculator",
    "render_video_task",
    "get_task_status",
    "cancel_task",
    "cleanup_old_outputs",
    "TextToVideoPipeline",
    "PipelineConfig",
    "PipelineResult",
    "create_pipeline",
    "MusicToClipPipeline",
    "MusicPipelineConfig",
    "MusicPipelineResult",
    "BeatDetector",
    "BeatInfo",
    "create_music_pipeline",
    "AudioToVideoPipeline",
    "AudioPipelineConfig",
    "AudioPipelineResult",
    "create_audio_pipeline",
    "LongToShortsPipeline",
    "LongVideoPipelineConfig",
    "LongVideoPipelineResult",
    "ClipData",
    "VideoSegment",
    "SilenceDetector",
    "VideoSegmenter",
    "create_long_video_pipeline",
]
