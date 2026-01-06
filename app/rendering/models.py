"""
Pydantic models for Video Rendering Engine.
Production-ready data structures.
"""
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Self
from pathlib import Path
from enum import Enum


class SceneType(str, Enum):
    VIDEO = "video"
    IMAGE = "image"


class WordTimestamp(BaseModel):
    word: str = Field(..., min_length=1)
    start: float = Field(..., ge=0)
    end: float = Field(..., ge=0)

    @model_validator(mode="after")
    def validate_timing(self) -> Self:
        if self.end < self.start:
            raise ValueError(f"end ({self.end}) must be >= start ({self.start})")
        return self


class AudioTimestamps(BaseModel):
    words: list[WordTimestamp] = Field(..., min_length=1)
    total_duration: float = Field(..., gt=0)

    def get_words_in_range(self, start: float, end: float) -> list[WordTimestamp]:
        result = []
        for w in self.words:
            if w.end > start and w.start < end:
                result.append(w)
        return result

    def get_active_word_at(self, time: float) -> Optional[WordTimestamp]:
        for word in self.words:
            if word.start <= time < word.end:
                return word
        return None


class SceneData(BaseModel):
    scene_id: str = Field(..., min_length=1)
    scene_type: SceneType = SceneType.VIDEO
    background_path: str = Field(..., min_length=1)
    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., gt=0)
    text: str = Field(default="")
    transition_in: Optional[str] = Field(default=None)
    transition_duration: float = Field(default=0.5, ge=0, le=2.0)

    @model_validator(mode="after")
    def validate_timing(self) -> Self:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be > start_time")
        return self

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


class VideoScript(BaseModel):
    script_id: str = Field(..., min_length=1)
    title: str = Field(default="Untitled")
    scenes: list[SceneData] = Field(..., min_length=1)
    total_duration: float = Field(..., gt=0)

    @field_validator("scenes")
    @classmethod
    def sort_scenes(cls, v: list[SceneData]) -> list[SceneData]:
        return sorted(v, key=lambda s: s.start_time)


class RenderJob(BaseModel):
    job_id: str = Field(..., min_length=1)
    script: VideoScript
    audio_path: str = Field(..., min_length=1)
    timestamps: AudioTimestamps
    bgm_path: Optional[str] = Field(default=None)
    output_dir: str = Field(default="/tmp/video_output")
    output_filename: str = Field(default="output.mp4")
    generate_srt: bool = Field(default=True)

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir) / self.job_id / self.output_filename

    @property
    def srt_path(self) -> Path:
        return self.output_path.with_suffix(".srt")


class RenderProgress(BaseModel):
    job_id: str
    stage: str
    progress: float = Field(..., ge=0, le=100)
    current_scene: Optional[int] = None
    total_scenes: Optional[int] = None
    message: str = ""


class RenderResult(BaseModel):
    job_id: str
    success: bool
    output_path: Optional[str] = None
    srt_path: Optional[str] = None
    duration_seconds: float = Field(default=0, ge=0)
    file_size_mb: Optional[float] = None
    error: Optional[str] = None

    video_duration_seconds: Optional[float] = Field(default=None, ge=0)
    scenes_count: Optional[int] = Field(default=None, ge=0)
    resolution: Optional[str] = Field(default=None)
    fps: Optional[int] = Field(default=None, ge=1)

    cost_usd: Optional[float] = Field(default=None, ge=0)
    cost_breakdown: Optional[dict] = Field(default=None)
    usage_metrics: Optional[dict] = Field(default=None)
