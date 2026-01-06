"""
Pydantic schemas for API requests and responses.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
from enum import Enum
from datetime import datetime


class TaskStatus(str, Enum):
    """Celery task status enum."""
    PENDING = "PENDING"
    STARTED = "STARTED"
    PROGRESS = "PROGRESS"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    REVOKED = "REVOKED"
    QUEUED = "QUEUED"


class SceneRequest(BaseModel):
    """Single scene in render request."""
    scene_id: str = Field(..., min_length=1)
    scene_type: str = Field(default="video")
    background_path: str = Field(..., min_length=1)
    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., gt=0)
    text: str = Field(default="")
    transition_in: Optional[str] = Field(default=None)
    transition_duration: float = Field(default=0.5, ge=0, le=2.0)


class ScriptRequest(BaseModel):
    """Video script in render request."""
    script_id: str = Field(..., min_length=1)
    title: str = Field(default="Untitled")
    scenes: list[SceneRequest] = Field(..., min_length=1)
    total_duration: float = Field(..., gt=0)


class WordTimestampRequest(BaseModel):
    """Word-level timestamp."""
    word: str = Field(..., min_length=1)
    start: float = Field(..., ge=0)
    end: float = Field(..., ge=0)


class TimestampsRequest(BaseModel):
    """Word-level timestamps from ElevenLabs."""
    words: list[WordTimestampRequest] = Field(..., min_length=1)
    total_duration: float = Field(..., gt=0)


class RenderSettings(BaseModel):
    """Optional render settings."""
    video_width: int = Field(default=1080, ge=480, le=3840)
    video_height: int = Field(default=1920, ge=480, le=3840)
    fps: int = Field(default=30, ge=15, le=60)
    video_bitrate: str = Field(default="8M")
    preset: str = Field(default="medium")
    bgm_volume_db: float = Field(default=-20.0, ge=-60, le=0)
    subtitle_font_size: int = Field(default=70, ge=20, le=200)
    subtitle_color: str = Field(default="white")
    subtitle_active_color: str = Field(default="#FFD700")
    generate_srt: bool = Field(default=True)


class RenderRequest(BaseModel):
    """POST /render request body."""
    job_id: Optional[str] = Field(default=None, description="Custom job ID (auto-generated if not provided)")
    script: ScriptRequest
    audio_path: str = Field(..., min_length=1)
    timestamps: TimestampsRequest
    bgm_path: Optional[str] = Field(default=None)
    output_dir: str = Field(default="/tmp/video_output")
    output_filename: str = Field(default="output.mp4")
    settings: RenderSettings = Field(default_factory=RenderSettings)

    @field_validator("output_filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        if not v.endswith(".mp4"):
            v = f"{v}.mp4"
        return v


class RenderResponse(BaseModel):
    """POST /render response."""
    task_id: str
    job_id: str
    status: TaskStatus = TaskStatus.QUEUED
    message: str = "Render job queued successfully"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProgressInfo(BaseModel):
    """Render progress information."""
    stage: str
    progress: float = Field(ge=0, le=100)
    current_scene: Optional[int] = None
    total_scenes: Optional[int] = None
    message: str = ""


class CostBreakdown(BaseModel):
    """Cost breakdown in response."""
    cpu_cost_usd: float
    storage_cost_usd: float
    gpu_cost_usd: float = 0.0
    bandwidth_cost_usd: float = 0.0
    total_cost_usd: float
    cost_per_second_video: float = 0.0
    cost_per_frame: float = 0.0
    currency: str = "USD"


class UsageMetricsResponse(BaseModel):
    """Usage metrics in response."""
    render_time_seconds: float
    video_duration_seconds: float
    scenes_count: int
    resolution: str
    width: int
    height: int
    fps: int
    output_size_mb: Optional[float] = None
    total_frames: int = 0


class RenderResultResponse(BaseModel):
    """Render result when task is complete."""
    job_id: str
    success: bool
    output_path: Optional[str] = None
    srt_path: Optional[str] = None
    duration_seconds: float = 0
    file_size_mb: Optional[float] = None
    error: Optional[str] = None
    video_duration_seconds: Optional[float] = None
    scenes_count: Optional[int] = None
    resolution: Optional[str] = None
    fps: Optional[int] = None
    cost_usd: Optional[float] = None
    cost_breakdown: Optional[CostBreakdown] = None
    usage_metrics: Optional[UsageMetricsResponse] = None


class RenderStatusResponse(BaseModel):
    """GET /render/{task_id} response."""
    task_id: str
    job_id: Optional[str] = None
    status: TaskStatus
    progress: Optional[ProgressInfo] = None
    result: Optional[RenderResultResponse] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None


class CancelResponse(BaseModel):
    """POST /render/{task_id}/cancel response."""
    task_id: str
    cancelled: bool
    message: str


class HealthResponse(BaseModel):
    """GET /health response."""
    status: str = "healthy"
    service: str = "video-rendering-api"
    version: str = "1.0.0"
    celery_connected: bool = False
    redis_connected: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class EstimateCostRequest(BaseModel):
    """POST /estimate-cost request."""
    video_duration_seconds: float = Field(..., gt=0)
    width: int = Field(default=1080, ge=480, le=3840)
    height: int = Field(default=1920, ge=480, le=3840)
    fps: int = Field(default=30, ge=15, le=60)
    complexity_factor: float = Field(default=1.0, ge=0.5, le=3.0)


class EstimateCostResponse(BaseModel):
    """POST /estimate-cost response."""
    estimated_cost_usd: float
    breakdown: CostBreakdown
    video_duration_seconds: float
    resolution: str
