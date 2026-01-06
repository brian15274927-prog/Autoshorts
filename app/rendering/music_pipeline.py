"""
Music-to-Clip Pipeline.

Orchestrates the complete flow from music to beat-synced video:
Music Audio → Beat Detection → Assets → Video Assembly → Celery
"""
import uuid
import wave
import struct
import tempfile
import math
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field

from app.providers import get_assets_provider


@dataclass
class MusicPipelineConfig:
    """Configuration for music-to-clip pipeline."""
    width: int = 1080
    height: int = 1920
    fps: int = 30
    clip_length: float = 10.0
    min_beat_interval: float = 0.3
    max_beat_interval: float = 1.5
    default_beat_interval: float = 0.8
    output_dir: str = field(default_factory=lambda: str(Path(tempfile.gettempdir()) / "dake_output"))
    style: str = "cinematic"
    zoom_intensity: float = 1.05
    flash_duration: float = 0.1
    crossfade_duration: float = 0.15


@dataclass
class BeatInfo:
    """Information about detected beats."""
    timestamps: List[float]
    tempo_bpm: float
    total_duration: float
    beat_interval: float


@dataclass
class MusicPipelineResult:
    """Result of music-to-clip pipeline preparation."""
    job_id: str
    script_json: Dict[str, Any]
    audio_path: str
    total_duration: float
    clip_duration: float
    scenes_count: int
    beats_count: int
    tempo_bpm: float
    config: MusicPipelineConfig

    def to_celery_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs for render_video_task (music variant)."""
        return {
            "job_id": self.job_id,
            "script_json": self.script_json,
            "audio_path": self.audio_path,
            "timestamps_json": {"words": [], "total_duration": self.clip_duration},
            "bgm_path": None,
            "output_dir": self.config.output_dir,
            "output_filename": "output.mp4",
            "generate_srt": False,
            "video_width": self.config.width,
            "video_height": self.config.height,
            "fps": self.config.fps,
            "video_bitrate": "8M",
            "preset": "medium",
            "bgm_volume_db": 0.0,
            "subtitle_font_size": 70,
            "subtitle_color": "white",
            "subtitle_active_color": "#FFD700",
        }


class BeatDetector:
    """
    Lightweight beat detector using amplitude/energy analysis.
    No external dependencies required.
    """

    def __init__(
        self,
        min_interval: float = 0.3,
        max_interval: float = 1.5,
        default_interval: float = 0.8,
    ):
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.default_interval = default_interval

    def detect_beats(
        self,
        audio_path: Path,
        clip_start: float = 0.0,
        clip_duration: Optional[float] = None,
    ) -> BeatInfo:
        """
        Detect beats in audio using energy-based analysis.

        Args:
            audio_path: Path to audio file (WAV)
            clip_start: Start time for clip extraction
            clip_duration: Duration of clip to analyze

        Returns:
            BeatInfo with beat timestamps and tempo
        """
        try:
            audio_data, sample_rate, total_duration = self._load_audio(audio_path)

            if clip_duration is None:
                clip_duration = min(15.0, total_duration)

            end_time = min(clip_start + clip_duration, total_duration)
            actual_duration = end_time - clip_start

            start_sample = int(clip_start * sample_rate)
            end_sample = int(end_time * sample_rate)
            clip_audio = audio_data[start_sample:end_sample]

            if len(clip_audio) < sample_rate * 0.5:
                return self._fallback_beats(actual_duration)

            beats = self._detect_energy_peaks(clip_audio, sample_rate, actual_duration)

            if len(beats) < 2:
                return self._fallback_beats(actual_duration)

            intervals = [beats[i + 1] - beats[i] for i in range(len(beats) - 1)]
            avg_interval = sum(intervals) / len(intervals)
            tempo_bpm = 60.0 / avg_interval if avg_interval > 0 else 120.0

            return BeatInfo(
                timestamps=beats,
                tempo_bpm=round(tempo_bpm, 1),
                total_duration=actual_duration,
                beat_interval=round(avg_interval, 3),
            )

        except Exception:
            duration = clip_duration or 10.0
            return self._fallback_beats(duration)

    def _load_audio(self, audio_path: Path) -> Tuple[List[float], int, float]:
        """Load audio file and return samples, sample rate, duration."""
        path_str = str(audio_path)

        if path_str.lower().endswith('.mp3'):
            return self._load_via_ffmpeg(audio_path)

        try:
            with wave.open(path_str, 'rb') as wf:
                n_channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                sample_rate = wf.getframerate()
                n_frames = wf.getnframes()

                raw_data = wf.readframes(n_frames)

            if sample_width == 1:
                fmt = f'{n_frames * n_channels}B'
                samples = struct.unpack(fmt, raw_data)
                samples = [(s - 128) / 128.0 for s in samples]
            elif sample_width == 2:
                fmt = f'{n_frames * n_channels}h'
                samples = struct.unpack(fmt, raw_data)
                samples = [s / 32768.0 for s in samples]
            else:
                fmt = f'{n_frames * n_channels}i'
                samples = struct.unpack(fmt, raw_data[:n_frames * n_channels * 4])
                samples = [s / 2147483648.0 for s in samples]

            if n_channels > 1:
                mono_samples = []
                for i in range(0, len(samples), n_channels):
                    mono_samples.append(sum(samples[i:i + n_channels]) / n_channels)
                samples = mono_samples

            duration = n_frames / sample_rate
            return samples, sample_rate, duration

        except Exception:
            return self._load_via_ffmpeg(audio_path)

    def _load_via_ffmpeg(self, audio_path: Path) -> Tuple[List[float], int, float]:
        """Load audio via FFmpeg conversion to WAV."""
        import subprocess
        import shutil

        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise RuntimeError("FFmpeg not found")

        temp_wav = Path(tempfile.gettempdir()) / f"temp_audio_{uuid.uuid4().hex[:8]}.wav"

        try:
            cmd = [
                ffmpeg_path, "-y", "-i", str(audio_path),
                "-ar", "22050", "-ac", "1", "-f", "wav",
                str(temp_wav)
            ]
            subprocess.run(cmd, capture_output=True, check=True)

            with wave.open(str(temp_wav), 'rb') as wf:
                sample_rate = wf.getframerate()
                n_frames = wf.getnframes()
                raw_data = wf.readframes(n_frames)

            samples = struct.unpack(f'{n_frames}h', raw_data)
            samples = [s / 32768.0 for s in samples]
            duration = n_frames / sample_rate

            return samples, sample_rate, duration

        finally:
            if temp_wav.exists():
                temp_wav.unlink()

    def _detect_energy_peaks(
        self,
        samples: List[float],
        sample_rate: int,
        duration: float,
    ) -> List[float]:
        """Detect beats using energy peak analysis."""
        window_size = int(sample_rate * 0.02)
        hop_size = int(sample_rate * 0.01)

        energies = []
        times = []

        for i in range(0, len(samples) - window_size, hop_size):
            window = samples[i:i + window_size]
            energy = sum(s * s for s in window) / len(window)
            energies.append(energy)
            times.append(i / sample_rate)

        if not energies:
            return self._generate_fixed_beats(duration)

        avg_energy = sum(energies) / len(energies)
        threshold = avg_energy * 1.5

        beats = []
        min_samples_between = int(self.min_interval / 0.01)
        last_beat_idx = -min_samples_between

        for i, (energy, time) in enumerate(zip(energies, times)):
            if energy > threshold and (i - last_beat_idx) >= min_samples_between:
                if i > 0 and i < len(energies) - 1:
                    if energy >= energies[i - 1] and energy >= energies[i + 1]:
                        beats.append(round(time, 3))
                        last_beat_idx = i

        if len(beats) < 3:
            return self._generate_fixed_beats(duration)

        return beats

    def _generate_fixed_beats(self, duration: float) -> List[float]:
        """Generate fixed interval beats as fallback."""
        beats = []
        t = 0.0
        while t < duration:
            beats.append(round(t, 3))
            t += self.default_interval
        return beats

    def _fallback_beats(self, duration: float) -> BeatInfo:
        """Generate fallback beat info with fixed intervals."""
        beats = self._generate_fixed_beats(duration)
        return BeatInfo(
            timestamps=beats,
            tempo_bpm=60.0 / self.default_interval,
            total_duration=duration,
            beat_interval=self.default_interval,
        )


class MusicToClipPipeline:
    """
    Pipeline for converting music to beat-synced video clip.

    Steps:
    1. Load and analyze music audio
    2. Detect beats using energy analysis
    3. Select video assets
    4. Build scenes aligned to beats
    5. Configure effects (zoom, flash, crossfade)
    6. Build render job configuration
    """

    def __init__(self, config: Optional[MusicPipelineConfig] = None):
        self.config = config or MusicPipelineConfig()
        self._assets_provider = get_assets_provider("auto")
        self._beat_detector = BeatDetector(
            min_interval=self.config.min_beat_interval,
            max_interval=self.config.max_beat_interval,
            default_interval=self.config.default_beat_interval,
        )

    def prepare(
        self,
        audio_path: str,
        job_id: Optional[str] = None,
        style: Optional[str] = None,
        clip_length: Optional[float] = None,
        clip_start: float = 0.0,
    ) -> MusicPipelineResult:
        """
        Prepare render job from music audio.

        Args:
            audio_path: Path to music file
            job_id: Optional job ID
            style: Visual style hint
            clip_length: Target clip duration
            clip_start: Start time in audio

        Returns:
            MusicPipelineResult ready for Celery submission
        """
        job_id = job_id or f"music_{uuid.uuid4().hex[:12]}"
        style = style or self.config.style
        clip_length = clip_length or self.config.clip_length

        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        beats = self._beat_detector.detect_beats(
            audio_file,
            clip_start=clip_start,
            clip_duration=clip_length,
        )

        clip_audio_path = self._extract_clip_audio(
            audio_file, clip_start, beats.total_duration
        )

        assets = self._get_assets(style, len(beats.timestamps))

        scenes = self._build_beat_synced_scenes(assets, beats)

        script_json = self._build_script_json(job_id, scenes, beats.total_duration)

        return MusicPipelineResult(
            job_id=job_id,
            script_json=script_json,
            audio_path=str(clip_audio_path),
            total_duration=beats.total_duration,
            clip_duration=beats.total_duration,
            scenes_count=len(scenes),
            beats_count=len(beats.timestamps),
            tempo_bpm=beats.tempo_bpm,
            config=self.config,
        )

    def _extract_clip_audio(
        self,
        audio_path: Path,
        start: float,
        duration: float,
    ) -> Path:
        """Extract audio clip segment using FFmpeg."""
        import subprocess
        import shutil

        output_path = Path(tempfile.gettempdir()) / f"clip_{uuid.uuid4().hex[:8]}.wav"

        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            return audio_path

        try:
            cmd = [
                ffmpeg_path, "-y",
                "-ss", str(start),
                "-i", str(audio_path),
                "-t", str(duration),
                "-ar", "44100",
                "-ac", "2",
                str(output_path)
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            return output_path
        except Exception:
            return audio_path

    def _get_assets(self, style: str, min_count: int) -> List[Path]:
        """Get video assets based on style."""
        style_keywords = {
            "motivation": ["energy", "fitness", "success", "power"],
            "cinematic": ["cinematic", "epic", "dramatic", "film"],
            "dark": ["dark", "mystery", "night", "shadow"],
            "abstract": ["abstract", "pattern", "motion", "color"],
            "random": ["video", "background", "stock"],
        }

        keywords = style_keywords.get(style, style_keywords["random"])
        assets = []
        needed = max(min_count, 5)

        for keyword in keywords:
            if len(assets) >= needed:
                break
            try:
                found = self._assets_provider.search_videos(keyword, limit=3)
                for path in found:
                    if path not in assets:
                        assets.append(path)
            except Exception:
                continue

        if not assets:
            assets = self._assets_provider.search_videos("background", limit=needed)

        return assets if assets else []

    def _build_beat_synced_scenes(
        self,
        assets: List[Path],
        beats: BeatInfo,
    ) -> List[Dict[str, Any]]:
        """Build scenes with transitions aligned to beats."""
        if not assets:
            assets = self._assets_provider.search_videos("placeholder", limit=1)

        scenes = []
        beat_times = beats.timestamps

        if len(beat_times) < 2:
            beat_times = [0.0, beats.total_duration]

        scene_changes = self._select_scene_change_beats(beat_times)

        for i, (start_time, end_time) in enumerate(scene_changes):
            asset_path = assets[i % len(assets)]

            has_flash = (i % 4 == 0)
            has_zoom = (i % 2 == 0)

            effects = []
            if has_zoom:
                effects.append({
                    "type": "zoom",
                    "intensity": self.config.zoom_intensity,
                    "direction": "in" if i % 4 < 2 else "out",
                })
            if has_flash:
                effects.append({
                    "type": "flash",
                    "duration": self.config.flash_duration,
                    "color": "white",
                })

            scene = {
                "scene_id": f"scene_{i + 1}",
                "scene_type": "video",
                "background_path": str(asset_path),
                "start_time": round(start_time, 3),
                "end_time": round(end_time, 3),
                "text": "",
                "transition_in": "crossfade" if i > 0 else None,
                "transition_duration": self.config.crossfade_duration,
                "effects": effects,
            }
            scenes.append(scene)

        return scenes

    def _select_scene_change_beats(
        self,
        beat_times: List[float],
    ) -> List[Tuple[float, float]]:
        """Select which beats to use for scene changes."""
        if len(beat_times) < 2:
            return [(0.0, beat_times[-1] if beat_times else 1.0)]

        scene_intervals = []

        beats_per_scene = max(2, len(beat_times) // 8)

        i = 0
        while i < len(beat_times):
            start = beat_times[i]

            next_idx = min(i + beats_per_scene, len(beat_times) - 1)
            if next_idx <= i:
                next_idx = len(beat_times) - 1

            end = beat_times[next_idx] if next_idx < len(beat_times) else beat_times[-1]

            if end > start:
                scene_intervals.append((start, end))

            i = next_idx
            if i == len(beat_times) - 1:
                break

        if not scene_intervals:
            scene_intervals = [(0.0, beat_times[-1])]

        return scene_intervals

    def _build_script_json(
        self,
        job_id: str,
        scenes: List[Dict[str, Any]],
        total_duration: float,
    ) -> Dict[str, Any]:
        """Build script JSON for render engine."""
        return {
            "script_id": f"script_{job_id}",
            "title": f"Music Clip {job_id}",
            "scenes": scenes,
            "total_duration": round(total_duration, 3),
        }


def create_music_pipeline(config: Optional[MusicPipelineConfig] = None) -> MusicToClipPipeline:
    """Factory function for creating music-to-clip pipeline."""
    return MusicToClipPipeline(config)
