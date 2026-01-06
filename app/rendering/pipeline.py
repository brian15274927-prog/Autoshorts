"""
Text-to-Video Pipeline.

Orchestrates the complete flow from text to render job:
Text → Assets → Voice → Timestamps → RenderJob → Celery
"""
import uuid
import re
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from app.providers import (
    get_assets_provider,
    get_voice_provider,
    get_timestamps_provider,
)
from app.providers.timestamps import TimestampSegment


@dataclass
class PipelineConfig:
    """Configuration for text-to-video pipeline."""
    width: int = 1080
    height: int = 1920
    fps: int = 30
    min_clip_duration: float = 1.5
    max_clip_duration: float = 3.0
    clips_per_video: int = 5
    output_dir: str = field(default_factory=lambda: str(Path(tempfile.gettempdir()) / "dake_output"))
    lang: str = "ru"
    generate_srt: bool = True
    video_bitrate: str = "8M"
    preset: str = "medium"
    subtitle_font_size: int = 70
    subtitle_color: str = "white"
    subtitle_active_color: str = "#FFD700"


@dataclass
class PipelineResult:
    """Result of text-to-video pipeline preparation."""
    job_id: str
    script_json: Dict[str, Any]
    timestamps_json: Dict[str, Any]
    audio_path: str
    total_duration: float
    scenes_count: int
    config: PipelineConfig

    def to_celery_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs for render_video_task."""
        return {
            "job_id": self.job_id,
            "script_json": self.script_json,
            "audio_path": self.audio_path,
            "timestamps_json": self.timestamps_json,
            "bgm_path": None,
            "output_dir": self.config.output_dir,
            "output_filename": "output.mp4",
            "generate_srt": self.config.generate_srt,
            "video_width": self.config.width,
            "video_height": self.config.height,
            "fps": self.config.fps,
            "video_bitrate": self.config.video_bitrate,
            "preset": self.config.preset,
            "bgm_volume_db": -20.0,
            "subtitle_font_size": self.config.subtitle_font_size,
            "subtitle_color": self.config.subtitle_color,
            "subtitle_active_color": self.config.subtitle_active_color,
        }


class TextToVideoPipeline:
    """
    Pipeline for converting text to video render job.

    Steps:
    1. Generate voice audio from text (TTS)
    2. Extract timestamps from audio
    3. Search for video assets based on text keywords
    4. Build scenes that cover the audio duration
    5. Build render job configuration
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self._assets_provider = get_assets_provider("auto")
        self._voice_provider = get_voice_provider("auto")
        self._timestamps_provider = get_timestamps_provider("auto")

    def prepare(
        self,
        text: str,
        job_id: Optional[str] = None,
        style: Optional[str] = None,
        lang: Optional[str] = None,
    ) -> PipelineResult:
        """
        Prepare render job from text input.

        Args:
            text: Input text script
            job_id: Optional job ID (generated if not provided)
            style: Visual style hint for asset search
            lang: Language code for TTS

        Returns:
            PipelineResult ready for Celery submission
        """
        job_id = job_id or f"text_{uuid.uuid4().hex[:12]}"
        lang = lang or self.config.lang

        audio_path = self._generate_voice(text, lang)

        timestamps = self._extract_timestamps(audio_path, text)

        total_duration = self._get_audio_duration(audio_path, timestamps)

        keywords = self._extract_keywords(text, style)

        asset_paths = self._get_assets(keywords)

        scenes = self._build_scenes(asset_paths, total_duration, timestamps)

        script_json = self._build_script_json(job_id, scenes, total_duration)
        timestamps_json = self._build_timestamps_json(timestamps, total_duration)

        return PipelineResult(
            job_id=job_id,
            script_json=script_json,
            timestamps_json=timestamps_json,
            audio_path=str(audio_path),
            total_duration=total_duration,
            scenes_count=len(scenes),
            config=self.config,
        )

    def _generate_voice(self, text: str, lang: str) -> Path:
        """Generate TTS audio from text."""
        return self._voice_provider.synthesize(text, lang)

    def _extract_timestamps(
        self, audio_path: Path, text: str
    ) -> List[TimestampSegment]:
        """Extract word/sentence timestamps from audio."""
        return self._timestamps_provider.extract(audio_path, text)

    def _get_audio_duration(
        self, audio_path: Path, timestamps: List[TimestampSegment]
    ) -> float:
        """Get total audio duration from timestamps or file."""
        if timestamps:
            return max(seg["end"] for seg in timestamps)

        try:
            import wave
            with wave.open(str(audio_path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return frames / rate if rate > 0 else 10.0
        except Exception:
            return 10.0

    def _extract_keywords(
        self, text: str, style: Optional[str] = None
    ) -> List[str]:
        """Extract keywords from text for asset search."""
        words = re.findall(r"\b[a-zA-Zа-яА-ЯёЁ]{4,}\b", text.lower())

        stopwords = {
            "this", "that", "with", "from", "have", "been", "were", "they",
            "will", "would", "could", "should", "there", "their", "about",
            "which", "when", "what", "your", "more", "some", "into", "only",
            "other", "than", "then", "very", "just", "also", "back", "after",
            "это", "этот", "эта", "быть", "было", "были", "есть", "если",
            "для", "как", "так", "что", "чтобы", "при", "или", "все", "всё",
            "они", "она", "его", "него", "неё", "них", "ним", "ней", "нем",
            "которые", "который", "которая", "которое", "между", "через",
        }

        filtered = [w for w in words if w not in stopwords]

        unique_keywords = list(dict.fromkeys(filtered))[:10]

        if style:
            unique_keywords.insert(0, style)

        return unique_keywords if unique_keywords else ["video", "background"]

    def _get_assets(self, keywords: List[str]) -> List[Path]:
        """Get video assets based on keywords."""
        assets = []
        needed = self.config.clips_per_video

        for keyword in keywords:
            if len(assets) >= needed:
                break
            try:
                found = self._assets_provider.search_videos(keyword, limit=2)
                for path in found:
                    if path not in assets:
                        assets.append(path)
                        if len(assets) >= needed:
                            break
            except Exception:
                continue

        if not assets:
            assets = self._assets_provider.search_videos("background", limit=needed)

        return assets[:needed] if assets else []

    def _build_scenes(
        self,
        asset_paths: List[Path],
        total_duration: float,
        timestamps: List[TimestampSegment],
    ) -> List[Dict[str, Any]]:
        """Build scene list covering the total duration."""
        if not asset_paths:
            asset_paths = self._assets_provider.search_videos("placeholder", limit=1)

        scenes = []
        current_time = 0.0
        asset_index = 0

        scene_count = max(3, min(6, int(total_duration / 2.0)))
        base_duration = total_duration / scene_count

        for i in range(scene_count):
            scene_duration = base_duration

            if i == scene_count - 1:
                scene_duration = total_duration - current_time

            end_time = min(current_time + scene_duration, total_duration)

            scene_text = self._get_scene_text(timestamps, current_time, end_time)

            asset_path = asset_paths[asset_index % len(asset_paths)]
            asset_index += 1

            scene = {
                "scene_id": f"scene_{i + 1}",
                "scene_type": "video",
                "background_path": str(asset_path),
                "start_time": round(current_time, 3),
                "end_time": round(end_time, 3),
                "text": scene_text,
                "transition_in": "crossfade" if i > 0 else None,
                "transition_duration": 0.3,
            }
            scenes.append(scene)
            current_time = end_time

        return scenes

    def _get_scene_text(
        self,
        timestamps: List[TimestampSegment],
        start: float,
        end: float,
    ) -> str:
        """Get text content for a scene time range."""
        texts = []
        for seg in timestamps:
            if seg["end"] > start and seg["start"] < end:
                texts.append(seg["text"])
        return " ".join(texts)

    def _build_script_json(
        self,
        job_id: str,
        scenes: List[Dict[str, Any]],
        total_duration: float,
    ) -> Dict[str, Any]:
        """Build script JSON for render engine."""
        return {
            "script_id": f"script_{job_id}",
            "title": f"Video {job_id}",
            "scenes": scenes,
            "total_duration": round(total_duration, 3),
        }

    def _build_timestamps_json(
        self,
        timestamps: List[TimestampSegment],
        total_duration: float,
    ) -> Dict[str, Any]:
        """Build timestamps JSON for render engine with word-level timing."""
        words = []

        for seg in timestamps:
            segment_text = seg["text"].strip()
            if not segment_text:
                continue

            segment_words = segment_text.split()
            if not segment_words:
                continue

            segment_duration = seg["end"] - seg["start"]
            word_duration = segment_duration / len(segment_words)

            current_time = seg["start"]
            for word_text in segment_words:
                word_end = min(current_time + word_duration, seg["end"])
                words.append({
                    "word": word_text,
                    "start": round(current_time, 3),
                    "end": round(word_end, 3),
                })
                current_time = word_end

        if not words:
            words = [{"word": "...", "start": 0.0, "end": min(1.0, total_duration)}]

        return {
            "words": words,
            "total_duration": round(total_duration, 3),
        }


def create_pipeline(config: Optional[PipelineConfig] = None) -> TextToVideoPipeline:
    """Factory function for creating text-to-video pipeline."""
    return TextToVideoPipeline(config)
