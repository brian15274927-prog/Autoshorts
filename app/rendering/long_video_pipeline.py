"""
Long Video → Shorts Pipeline.

Orchestrates batch processing of long videos into multiple short vertical clips:
Long Video → Segmentation → Crop → Subtitles → Multiple RenderJobs
"""
import uuid
import wave
import struct
import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field

from app.providers import get_timestamps_provider
from app.providers.timestamps import TimestampSegment


@dataclass
class LongVideoPipelineConfig:
    """Configuration for long video → shorts pipeline."""
    width: int = 1080
    height: int = 1920
    fps: int = 30
    clip_length: float = 15.0
    max_clips: int = 5
    min_clip_length: float = 8.0
    max_clip_length: float = 60.0
    silence_threshold: float = 0.02
    silence_min_duration: float = 0.3
    window_overlap: float = 2.0
    output_dir: str = field(default_factory=lambda: str(Path(tempfile.gettempdir()) / "dake_output"))
    style: str = "education"
    generate_srt: bool = True
    subtitle_font_size: int = 70
    subtitle_color: str = "white"
    subtitle_active_color: str = "#FFD700"
    video_bitrate: str = "8M"
    preset: str = "medium"


@dataclass
class VideoSegment:
    """A segment extracted from the long video."""
    segment_id: str
    start: float
    end: float
    duration: float
    audio_path: str
    video_path: str


@dataclass
class ClipData:
    """Complete data for a single generated clip."""
    batch_id: str
    clip_id: str
    clip_index: int
    start: float
    end: float
    video_path: str
    audio_path: str
    cropped_video_path: str
    subtitles: List[Dict[str, Any]]
    srt_path: Optional[str]
    timestamps_json: Dict[str, Any]
    script_json: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "batch_id": self.batch_id,
            "clip_id": self.clip_id,
            "clip_index": self.clip_index,
            "start": self.start,
            "end": self.end,
            "video_path": self.video_path,
            "audio_path": self.audio_path,
            "cropped_video_path": self.cropped_video_path,
            "subtitles": self.subtitles,
            "srt_path": self.srt_path,
        }

    def to_celery_kwargs(self, config: LongVideoPipelineConfig) -> Dict[str, Any]:
        """Convert to kwargs for render_video_task."""
        return {
            "job_id": self.clip_id,
            "script_json": self.script_json,
            "audio_path": self.audio_path,
            "timestamps_json": self.timestamps_json,
            "bgm_path": None,
            "output_dir": config.output_dir,
            "output_filename": f"clip_{self.clip_index:02d}.mp4",
            "generate_srt": config.generate_srt,
            "video_width": config.width,
            "video_height": config.height,
            "fps": config.fps,
            "video_bitrate": config.video_bitrate,
            "preset": config.preset,
            "bgm_volume_db": 0.0,
            "subtitle_font_size": config.subtitle_font_size,
            "subtitle_color": config.subtitle_color,
            "subtitle_active_color": config.subtitle_active_color,
        }


@dataclass
class LongVideoPipelineResult:
    """Result of long video → shorts pipeline preparation."""
    batch_id: str
    source_video_path: str
    source_duration: float
    clips: List[ClipData]
    clips_count: int
    config: LongVideoPipelineConfig

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "batch_id": self.batch_id,
            "source_video_path": self.source_video_path,
            "source_duration": self.source_duration,
            "clips_count": self.clips_count,
            "clips": [clip.to_dict() for clip in self.clips],
        }


class SilenceDetector:
    """Detects silence/pauses in audio for segmentation."""

    def __init__(
        self,
        threshold: float = 0.02,
        min_duration: float = 0.3,
    ):
        self.threshold = threshold
        self.min_duration = min_duration

    def detect_silence_points(
        self,
        audio_path: Path,
        total_duration: float,
    ) -> List[float]:
        """
        Detect silence points in audio.

        Returns list of timestamps where silence occurs.
        Falls back to empty list if detection fails.
        """
        try:
            samples, sample_rate = self._load_audio(audio_path)
            if not samples or sample_rate == 0:
                return []

            window_size = int(sample_rate * 0.05)
            hop_size = int(sample_rate * 0.02)

            silence_points = []
            in_silence = False
            silence_start = 0.0

            for i in range(0, len(samples) - window_size, hop_size):
                window = samples[i:i + window_size]
                rms = (sum(s * s for s in window) / len(window)) ** 0.5
                time = i / sample_rate

                if rms < self.threshold:
                    if not in_silence:
                        in_silence = True
                        silence_start = time
                else:
                    if in_silence:
                        silence_duration = time - silence_start
                        if silence_duration >= self.min_duration:
                            silence_points.append(silence_start + silence_duration / 2)
                        in_silence = False

            return silence_points

        except Exception:
            return []

    def _load_audio(self, audio_path: Path) -> Tuple[List[float], int]:
        """Load audio samples from file."""
        try:
            with wave.open(str(audio_path), 'rb') as wf:
                n_channels = wf.getnchannels()
                sample_rate = wf.getframerate()
                n_frames = wf.getnframes()
                raw_data = wf.readframes(n_frames)

            samples = struct.unpack(f'{n_frames * n_channels}h', raw_data)
            samples = [s / 32768.0 for s in samples]

            if n_channels > 1:
                mono = []
                for i in range(0, len(samples), n_channels):
                    mono.append(sum(samples[i:i + n_channels]) / n_channels)
                samples = mono

            return samples, sample_rate

        except Exception:
            return [], 0


class VideoSegmenter:
    """Segments long video into clips based on silence or fixed windows."""

    def __init__(self, config: LongVideoPipelineConfig):
        self.config = config
        self.silence_detector = SilenceDetector(
            threshold=config.silence_threshold,
            min_duration=config.silence_min_duration,
        )

    def segment(
        self,
        video_path: Path,
        audio_path: Path,
        total_duration: float,
    ) -> List[Tuple[float, float]]:
        """
        Segment video into clips.

        Returns list of (start, end) tuples.
        Always returns at least 1 segment.
        """
        target_length = self.config.clip_length
        max_clips = self.config.max_clips

        silence_points = self.silence_detector.detect_silence_points(
            audio_path, total_duration
        )

        if silence_points and len(silence_points) >= 2:
            segments = self._segment_by_silence(
                silence_points, total_duration, target_length, max_clips
            )
            if segments:
                return segments

        return self._segment_fixed_windows(
            total_duration, target_length, max_clips
        )

    def _segment_by_silence(
        self,
        silence_points: List[float],
        total_duration: float,
        target_length: float,
        max_clips: int,
    ) -> List[Tuple[float, float]]:
        """Segment based on silence points."""
        segments = []
        current_start = 0.0

        all_points = [0.0] + sorted(silence_points) + [total_duration]

        for point in all_points[1:]:
            segment_duration = point - current_start

            if segment_duration >= self.config.min_clip_length:
                if segment_duration <= self.config.max_clip_length:
                    segments.append((current_start, point))
                    current_start = point
                else:
                    while current_start < point:
                        end = min(current_start + target_length, point)
                        if end - current_start >= self.config.min_clip_length:
                            segments.append((current_start, end))
                        current_start = end

            if len(segments) >= max_clips:
                break

        return segments[:max_clips]

    def _segment_fixed_windows(
        self,
        total_duration: float,
        target_length: float,
        max_clips: int,
    ) -> List[Tuple[float, float]]:
        """Fallback: fixed sliding window segmentation."""
        segments = []
        step = target_length - self.config.window_overlap

        current = 0.0
        while current < total_duration and len(segments) < max_clips:
            end = min(current + target_length, total_duration)
            if end - current >= self.config.min_clip_length:
                segments.append((round(current, 3), round(end, 3)))
            current += step

        if not segments and total_duration > 0:
            segments = [(0.0, min(target_length, total_duration))]

        return segments


class LongToShortsPipeline:
    """
    Pipeline for converting long video to multiple short vertical clips.

    Steps:
    1. Extract audio from video
    2. Analyze and segment based on silence/content
    3. For each segment:
       - Extract video clip
       - Crop to vertical (9:16)
       - Generate timestamps/subtitles
       - Build render job
    4. Return batch of clips ready for Celery
    """

    def __init__(self, config: Optional[LongVideoPipelineConfig] = None):
        self.config = config or LongVideoPipelineConfig()
        self._timestamps_provider = get_timestamps_provider("auto")
        self._segmenter = VideoSegmenter(self.config)

    def prepare(
        self,
        video_path: str,
        batch_id: Optional[str] = None,
        style: Optional[str] = None,
    ) -> LongVideoPipelineResult:
        """
        Prepare batch of short clips from long video.

        Args:
            video_path: Path to source video file
            batch_id: Optional batch ID
            style: Visual style hint

        Returns:
            LongVideoPipelineResult with all clips ready for submission
        """
        batch_id = batch_id or f"batch_{uuid.uuid4().hex[:12]}"
        style = style or self.config.style

        video_file = Path(video_path)
        if not video_file.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        total_duration = self._get_video_duration(video_file)
        if total_duration < self.config.min_clip_length:
            raise ValueError(
                f"Video too short ({total_duration:.1f}s). "
                f"Minimum: {self.config.min_clip_length}s"
            )

        audio_path = self._extract_audio(video_file, batch_id)

        segments = self._segmenter.segment(video_file, audio_path, total_duration)

        clips = []
        for i, (start, end) in enumerate(segments):
            clip = self._process_segment(
                video_file=video_file,
                audio_path=audio_path,
                batch_id=batch_id,
                clip_index=i,
                start=start,
                end=end,
                style=style,
            )
            clips.append(clip)

        return LongVideoPipelineResult(
            batch_id=batch_id,
            source_video_path=str(video_file),
            source_duration=total_duration,
            clips=clips,
            clips_count=len(clips),
            config=self.config,
        )

    def _get_video_duration(self, video_path: Path) -> float:
        """Get video duration using FFprobe."""
        try:
            ffprobe = shutil.which("ffprobe")
            if ffprobe:
                cmd = [
                    ffprobe, "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(video_path)
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    return float(result.stdout.strip())
        except Exception:
            pass

        return 60.0

    def _extract_audio(self, video_path: Path, batch_id: str) -> Path:
        """Extract audio track from video."""
        output_dir = Path(tempfile.gettempdir()) / "dake_long" / batch_id
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / "full_audio.wav"

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            cmd = [
                ffmpeg, "-y", "-i", str(video_path),
                "-vn", "-ar", "44100", "-ac", "1",
                "-f", "wav", str(audio_path)
            ]
            subprocess.run(cmd, capture_output=True, check=True)

        return audio_path

    def _extract_segment_audio(
        self,
        full_audio_path: Path,
        batch_id: str,
        clip_index: int,
        start: float,
        duration: float,
    ) -> Path:
        """Extract audio segment for a clip."""
        output_dir = Path(tempfile.gettempdir()) / "dake_long" / batch_id
        output_dir.mkdir(parents=True, exist_ok=True)
        segment_path = output_dir / f"audio_{clip_index:02d}.wav"

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            cmd = [
                ffmpeg, "-y",
                "-ss", str(start),
                "-i", str(full_audio_path),
                "-t", str(duration),
                "-ar", "44100", "-ac", "1",
                str(segment_path)
            ]
            subprocess.run(cmd, capture_output=True, check=True)

        return segment_path

    def _crop_video_segment(
        self,
        video_path: Path,
        batch_id: str,
        clip_index: int,
        start: float,
        duration: float,
    ) -> Path:
        """Extract and crop video segment to vertical 9:16."""
        output_dir = Path(tempfile.gettempdir()) / "dake_long" / batch_id
        output_dir.mkdir(parents=True, exist_ok=True)
        cropped_path = output_dir / f"cropped_{clip_index:02d}.mp4"

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            crop_filter = (
                f"crop=ih*9/16:ih,"
                f"scale={self.config.width}:{self.config.height},"
                f"setsar=1"
            )

            cmd = [
                ffmpeg, "-y",
                "-ss", str(start),
                "-i", str(video_path),
                "-t", str(duration),
                "-vf", crop_filter,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-an",
                str(cropped_path)
            ]
            subprocess.run(cmd, capture_output=True, check=True)

        return cropped_path

    def _process_segment(
        self,
        video_file: Path,
        audio_path: Path,
        batch_id: str,
        clip_index: int,
        start: float,
        end: float,
        style: str,
    ) -> ClipData:
        """Process a single segment into a clip."""
        clip_id = f"{batch_id}_clip_{clip_index:02d}"
        duration = end - start

        segment_audio = self._extract_segment_audio(
            audio_path, batch_id, clip_index, start, duration
        )

        cropped_video = self._crop_video_segment(
            video_file, batch_id, clip_index, start, duration
        )

        placeholder_text = self._generate_placeholder_transcript(duration)
        timestamps = self._timestamps_provider.extract(segment_audio, placeholder_text)

        subtitles = self._build_subtitles(timestamps)
        timestamps_json = self._build_timestamps_json(timestamps, duration)
        script_json = self._build_script_json(clip_id, cropped_video, duration)

        srt_path = self._generate_srt(
            batch_id, clip_index, timestamps, duration
        ) if self.config.generate_srt else None

        return ClipData(
            batch_id=batch_id,
            clip_id=clip_id,
            clip_index=clip_index,
            start=start,
            end=end,
            video_path=str(video_file),
            audio_path=str(segment_audio),
            cropped_video_path=str(cropped_video),
            subtitles=subtitles,
            srt_path=str(srt_path) if srt_path else None,
            timestamps_json=timestamps_json,
            script_json=script_json,
        )

    def _generate_placeholder_transcript(self, duration: float) -> str:
        """Generate placeholder transcript for timestamp extraction."""
        sentences_count = max(3, int(duration / 4))
        sentences = [f"Content segment {i + 1}." for i in range(sentences_count)]
        return " ".join(sentences)

    def _build_subtitles(
        self,
        timestamps: List[TimestampSegment],
    ) -> List[Dict[str, Any]]:
        """Build subtitles list from timestamps."""
        subtitles = []
        for i, seg in enumerate(timestamps):
            subtitles.append({
                "id": f"s{i + 1}",
                "start": round(seg["start"], 3),
                "end": round(seg["end"], 3),
                "text": seg["text"],
            })
        return subtitles

    def _build_timestamps_json(
        self,
        timestamps: List[TimestampSegment],
        duration: float,
    ) -> Dict[str, Any]:
        """Build timestamps JSON for render engine."""
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
            words = [{"word": "...", "start": 0.0, "end": min(1.0, duration)}]

        return {
            "words": words,
            "total_duration": round(duration, 3),
        }

    def _build_script_json(
        self,
        clip_id: str,
        cropped_video_path: Path,
        duration: float,
    ) -> Dict[str, Any]:
        """Build script JSON for render engine."""
        return {
            "script_id": f"script_{clip_id}",
            "title": f"Short Clip {clip_id}",
            "scenes": [{
                "scene_id": "scene_1",
                "scene_type": "video",
                "background_path": str(cropped_video_path),
                "start_time": 0.0,
                "end_time": round(duration, 3),
                "text": "",
                "transition_in": None,
                "transition_duration": 0.0,
            }],
            "total_duration": round(duration, 3),
        }

    def _generate_srt(
        self,
        batch_id: str,
        clip_index: int,
        timestamps: List[TimestampSegment],
        duration: float,
    ) -> Path:
        """Generate SRT subtitle file."""
        output_dir = Path(tempfile.gettempdir()) / "dake_long" / batch_id
        output_dir.mkdir(parents=True, exist_ok=True)
        srt_path = output_dir / f"clip_{clip_index:02d}.srt"

        lines = []
        for i, seg in enumerate(timestamps):
            start_srt = self._seconds_to_srt_time(seg["start"])
            end_srt = self._seconds_to_srt_time(seg["end"])
            lines.append(f"{i + 1}")
            lines.append(f"{start_srt} --> {end_srt}")
            lines.append(seg["text"])
            lines.append("")

        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return srt_path

    def _seconds_to_srt_time(self, seconds: float) -> str:
        """Convert seconds to SRT timestamp format."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def create_long_video_pipeline(
    config: Optional[LongVideoPipelineConfig] = None
) -> LongToShortsPipeline:
    """Factory function for creating long video pipeline."""
    return LongToShortsPipeline(config)
