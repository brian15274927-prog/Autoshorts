"""
Speech Map - Voice Activity Detection using pyannote.audio and librosa.
Generates a map of speech segments across the entire video.
"""
import os
import logging
import subprocess
import re
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple
import warnings

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

FFMPEG_DIR = Path(__file__).parent.parent.parent / "tools" / "ffmpeg-master-latest-win64-gpl" / "bin"
if FFMPEG_DIR.exists():
    os.environ["PATH"] = str(FFMPEG_DIR) + os.pathsep + os.environ.get("PATH", "")


@dataclass
class SpeechSegment:
    """A segment of detected speech."""
    start: float
    end: float
    duration: float = field(init=False)
    confidence: float = 1.0

    def __post_init__(self):
        self.duration = self.end - self.start

    def merge(self, other: "SpeechSegment") -> "SpeechSegment":
        return SpeechSegment(
            start=min(self.start, other.start),
            end=max(self.end, other.end),
            confidence=(self.confidence + other.confidence) / 2
        )


class SpeechMapper:
    """Maps speech segments across entire audio."""

    def __init__(
        self,
        use_pyannote: bool = True,
        min_speech_duration: float = 1.0,
        min_silence_duration: float = 0.3,
        energy_threshold: float = 0.02,
    ):
        self.use_pyannote = use_pyannote
        self.min_speech_duration = min_speech_duration
        self.min_silence_duration = min_silence_duration
        self.energy_threshold = energy_threshold
        self._vad_pipeline = None

    def _load_audio(self, audio_path: str) -> Tuple[np.ndarray, int]:
        import librosa
        y, sr = librosa.load(audio_path, sr=16000, mono=True)
        return y, sr

    def _energy_based_vad(self, audio: np.ndarray, sr: int) -> List[SpeechSegment]:
        import librosa

        rms = librosa.feature.rms(y=audio, frame_length=2048, hop_length=512)[0]
        rms_norm = rms / (np.max(rms) + 1e-8)
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)
        is_speech = rms_norm > self.energy_threshold

        segments = []
        in_speech = False
        start_time = 0

        for i, (t, speech) in enumerate(zip(times, is_speech)):
            if speech and not in_speech:
                start_time = t
                in_speech = True
            elif not speech and in_speech:
                if t - start_time >= self.min_speech_duration:
                    segments.append(SpeechSegment(start=start_time, end=t,
                        confidence=float(np.mean(rms_norm[max(0, i-10):i]))))
                in_speech = False

        if in_speech and times[-1] - start_time >= self.min_speech_duration:
            segments.append(SpeechSegment(start=start_time, end=times[-1],
                confidence=float(np.mean(rms_norm[-10:]))))

        return segments

    def _ffmpeg_silence_detect(self, audio_path: str) -> List[SpeechSegment]:
        ffmpeg = str(FFMPEG_DIR / "ffmpeg.exe") if FFMPEG_DIR.exists() else "ffmpeg"

        cmd = [ffmpeg, "-i", audio_path, "-af",
               f"silencedetect=noise=-30dB:d={self.min_silence_duration}",
               "-f", "null", "-"]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            output = result.stderr

            silence_starts, silence_ends = [], []
            for line in output.split('\n'):
                if 'silence_start' in line:
                    m = re.search(r'silence_start: ([\d.]+)', line)
                    if m: silence_starts.append(float(m.group(1)))
                elif 'silence_end' in line:
                    m = re.search(r'silence_end: ([\d.]+)', line)
                    if m: silence_ends.append(float(m.group(1)))

            dur_m = re.search(r'Duration: (\d+):(\d+):([\d.]+)', output)
            total_dur = int(dur_m.group(1))*3600 + int(dur_m.group(2))*60 + float(dur_m.group(3)) if dur_m else 0

            segments = []
            prev_end = 0
            for s_start, s_end in zip(silence_starts, silence_ends):
                if s_start > prev_end and s_start - prev_end >= self.min_speech_duration:
                    segments.append(SpeechSegment(start=prev_end, end=s_start, confidence=0.8))
                prev_end = s_end

            if total_dur > 0 and total_dur - prev_end >= self.min_speech_duration:
                segments.append(SpeechSegment(start=prev_end, end=total_dur, confidence=0.8))

            return segments
        except Exception as e:
            logger.warning(f"FFmpeg silence detect failed: {e}")
            return []

    def _merge_close_segments(self, segments: List[SpeechSegment], max_gap: float = 0.5) -> List[SpeechSegment]:
        if not segments:
            return []
        merged = [segments[0]]
        for seg in segments[1:]:
            if seg.start - merged[-1].end <= max_gap:
                merged[-1] = merged[-1].merge(seg)
            else:
                merged.append(seg)
        return merged

    def map_speech(self, audio_path: str) -> List[SpeechSegment]:
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio not found: {audio_path}")

        segments = self._ffmpeg_silence_detect(audio_path)

        if not segments:
            audio, sr = self._load_audio(audio_path)
            segments = self._energy_based_vad(audio, sr)

        segments = self._merge_close_segments(segments)
        segments = [s for s in segments if s.duration >= self.min_speech_duration]

        logger.info(f"Speech map: {len(segments)} segments, {sum(s.duration for s in segments):.1f}s total")
        return segments


def create_speech_map(audio_path: str, **kwargs) -> List[SpeechSegment]:
    mapper = SpeechMapper(**kwargs)
    return mapper.map_speech(audio_path)
