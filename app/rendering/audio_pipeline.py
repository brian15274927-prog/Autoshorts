"""
Audio-to-Video Pipeline.

Orchestrates the complete flow from audio to video with subtitles:
Audio File → Timestamps → Assets → Video Assembly → Celery
"""
import uuid
import wave
import struct
import tempfile
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field

from app.providers import get_assets_provider, get_timestamps_provider
from app.providers.timestamps import TimestampSegment


@dataclass
class AudioPipelineConfig:
    """Configuration for audio-to-video pipeline."""
    width: int = 1080
    height: int = 1920
    fps: int = 30
    output_dir: str = field(default_factory=lambda: str(Path(tempfile.gettempdir()) / "dake_output"))
    style: str = "podcast"
    generate_srt: bool = True
    subtitle_font_size: int = 70
    subtitle_color: str = "white"
    subtitle_active_color: str = "#FFD700"
    video_bitrate: str = "8M"
    preset: str = "medium"
    scene_duration_min: float = 3.0
    scene_duration_max: float = 8.0


@dataclass
class AudioPipelineResult:
    """Result of audio-to-video pipeline preparation."""
    job_id: str
    script_json: Dict[str, Any]
    timestamps_json: Dict[str, Any]
    audio_path: str
    total_duration: float
    scenes_count: int
    words_count: int
    config: AudioPipelineConfig

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
            "bgm_volume_db": 0.0,
            "subtitle_font_size": self.config.subtitle_font_size,
            "subtitle_color": self.config.subtitle_color,
            "subtitle_active_color": self.config.subtitle_active_color,
        }


class AudioToVideoPipeline:
    """
    Pipeline for converting audio to video with subtitles.

    Steps:
    1. Load and analyze audio file
    2. Extract timestamps using timestamps provider
    3. Select video assets based on style
    4. Build scenes covering audio duration
    5. Build render job configuration
    """

    def __init__(self, config: Optional[AudioPipelineConfig] = None):
        self.config = config or AudioPipelineConfig()
        self._assets_provider = get_assets_provider("auto")
        self._timestamps_provider = get_timestamps_provider("auto")

    def prepare(
        self,
        audio_path: str,
        job_id: Optional[str] = None,
        style: Optional[str] = None,
        transcript_text: Optional[str] = None,
    ) -> AudioPipelineResult:
        """
        Prepare render job from audio file.

        Args:
            audio_path: Path to audio file
            job_id: Optional job ID
            style: Visual style hint
            transcript_text: Optional transcript (for better timestamps)

        Returns:
            AudioPipelineResult ready for Celery submission
        """
        job_id = job_id or f"audio_{uuid.uuid4().hex[:12]}"
        style = style or self.config.style

        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        duration = self._get_audio_duration(audio_file)

        transcript = transcript_text or self._generate_placeholder_transcript(duration)

        timestamps = self._extract_timestamps(audio_file, transcript)

        assets = self._get_assets(style, duration)

        scenes = self._build_scenes(assets, duration, timestamps)

        script_json = self._build_script_json(job_id, scenes, duration)
        timestamps_json = self._build_timestamps_json(timestamps, duration)

        return AudioPipelineResult(
            job_id=job_id,
            script_json=script_json,
            timestamps_json=timestamps_json,
            audio_path=str(audio_file),
            total_duration=duration,
            scenes_count=len(scenes),
            words_count=len(timestamps_json["words"]),
            config=self.config,
        )

    def _get_audio_duration(self, audio_path: Path) -> float:
        """Get audio file duration."""
        try:
            if str(audio_path).lower().endswith('.wav'):
                with wave.open(str(audio_path), 'rb') as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    return frames / rate if rate > 0 else 10.0
        except Exception:
            pass

        try:
            ffprobe = shutil.which("ffprobe")
            if ffprobe:
                cmd = [
                    ffprobe, "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(audio_path)
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    return float(result.stdout.strip())
        except Exception:
            pass

        return 30.0

    def _generate_placeholder_transcript(self, duration: float) -> str:
        """Generate placeholder transcript when none provided."""
        sentences_count = max(3, int(duration / 5))
        sentences = []
        for i in range(sentences_count):
            sentences.append(f"Segment {i + 1} of the audio content.")
        return " ".join(sentences)

    def _extract_timestamps(
        self, audio_path: Path, transcript: str
    ) -> List[TimestampSegment]:
        """Extract timestamps from audio using provider."""
        return self._timestamps_provider.extract(audio_path, transcript)

    def _get_assets(self, style: str, duration: float) -> List[Path]:
        """Get video assets based on style."""
        style_keywords = {
            "podcast": ["studio", "microphone", "podcast", "interview"],
            "motivation": ["success", "achievement", "inspiration", "sunrise"],
            "news": ["city", "office", "business", "professional"],
            "education": ["book", "study", "classroom", "learning"],
            "story": ["nature", "landscape", "journey", "adventure"],
            "random": ["background", "abstract", "motion", "video"],
        }

        keywords = style_keywords.get(style, style_keywords["random"])

        num_scenes = max(3, int(duration / 5))
        assets = []

        for keyword in keywords:
            if len(assets) >= num_scenes:
                break
            try:
                found = self._assets_provider.search_videos(keyword, limit=3)
                for path in found:
                    if path not in assets:
                        assets.append(path)
            except Exception:
                continue

        if not assets:
            assets = self._assets_provider.search_videos("background", limit=num_scenes)

        return assets if assets else []

    def _build_scenes(
        self,
        assets: List[Path],
        total_duration: float,
        timestamps: List[TimestampSegment],
    ) -> List[Dict[str, Any]]:
        """Build scenes covering the audio duration."""
        if not assets:
            assets = self._assets_provider.search_videos("placeholder", limit=1)

        scenes = []

        scene_boundaries = self._calculate_scene_boundaries(timestamps, total_duration)

        for i, (start_time, end_time) in enumerate(scene_boundaries):
            asset_path = assets[i % len(assets)]

            scene_text = self._get_scene_text(timestamps, start_time, end_time)

            scene = {
                "scene_id": f"scene_{i + 1}",
                "scene_type": "video",
                "background_path": str(asset_path),
                "start_time": round(start_time, 3),
                "end_time": round(end_time, 3),
                "text": scene_text,
                "transition_in": "crossfade" if i > 0 else None,
                "transition_duration": 0.5,
            }
            scenes.append(scene)

        return scenes

    def _calculate_scene_boundaries(
        self,
        timestamps: List[TimestampSegment],
        total_duration: float,
    ) -> List[Tuple[float, float]]:
        """Calculate scene start/end times based on content."""
        min_duration = self.config.scene_duration_min
        max_duration = self.config.scene_duration_max

        boundaries = []
        current_start = 0.0

        segment_ends = [seg["end"] for seg in timestamps]

        while current_start < total_duration:
            target_end = current_start + (min_duration + max_duration) / 2

            best_end = None
            for end in segment_ends:
                if current_start + min_duration <= end <= current_start + max_duration:
                    if best_end is None or end > best_end:
                        best_end = end

            if best_end is None:
                end_time = min(current_start + max_duration, total_duration)
            else:
                end_time = best_end

            if end_time <= current_start:
                end_time = min(current_start + min_duration, total_duration)

            boundaries.append((current_start, end_time))
            current_start = end_time

            if current_start >= total_duration - 0.1:
                break

        if boundaries:
            last = boundaries[-1]
            boundaries[-1] = (last[0], total_duration)

        return boundaries

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
            "title": f"Audio Video {job_id}",
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


def create_audio_pipeline(config: Optional[AudioPipelineConfig] = None) -> AudioToVideoPipeline:
    """Factory function for creating audio-to-video pipeline."""
    return AudioToVideoPipeline(config)
