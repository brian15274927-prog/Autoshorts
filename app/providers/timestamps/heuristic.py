"""
Heuristic timestamps provider - REQUIRED fallback.
"""
import re
import wave
from pathlib import Path
from typing import List

from .base import BaseTimestampsProvider, TimestampSegment


class HeuristicTimestampsProvider(BaseTimestampsProvider):
    """Heuristic-based timestamps provider. Always available."""

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "heuristic"

    @property
    def is_available(self) -> bool:
        return True

    def extract(self, audio_path: Path, text: str) -> List[TimestampSegment]:
        duration = self._get_audio_duration(audio_path)
        sentences = self._split_into_sentences(text)

        if not sentences:
            return [{"start": 0.0, "end": duration, "text": text or ""}]

        return self._distribute_timestamps(sentences, duration)

    def _get_audio_duration(self, audio_path: Path) -> float:
        if not audio_path.exists():
            return 10.0

        try:
            with wave.open(str(audio_path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return frames / rate if rate > 0 else 10.0
        except Exception:
            return 10.0

    def _split_into_sentences(self, text: str) -> List[str]:
        if not text or not text.strip():
            return []

        pattern = r"(?<=[.!?])\s+"
        sentences = re.split(pattern, text.strip())
        return [s.strip() for s in sentences if s.strip()]

    def _distribute_timestamps(
        self, sentences: List[str], total_duration: float
    ) -> List[TimestampSegment]:
        if not sentences:
            return [{"start": 0.0, "end": total_duration, "text": ""}]

        total_chars = sum(len(s) for s in sentences)
        if total_chars == 0:
            segment_duration = total_duration / len(sentences)
            segments = []
            for i, sentence in enumerate(sentences):
                segments.append({
                    "start": round(i * segment_duration, 3),
                    "end": round((i + 1) * segment_duration, 3),
                    "text": sentence,
                })
            return segments

        segments: List[TimestampSegment] = []
        current_time = 0.0

        for sentence in sentences:
            char_ratio = len(sentence) / total_chars
            segment_duration = total_duration * char_ratio
            end_time = min(current_time + segment_duration, total_duration)

            segments.append({
                "start": round(current_time, 3),
                "end": round(end_time, 3),
                "text": sentence,
            })
            current_time = end_time

        if segments:
            segments[-1]["end"] = round(total_duration, 3)

        return segments
