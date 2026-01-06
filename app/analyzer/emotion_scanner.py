"""
Emotion Scanner - Audio feature extraction using opensmile.
Analyzes energy, pitch, speech rate and emotional indicators.
"""
import os
import logging
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import tempfile
import subprocess

logger = logging.getLogger(__name__)

FFMPEG_DIR = Path(__file__).parent.parent.parent / "tools" / "ffmpeg-master-latest-win64-gpl" / "bin"
if FFMPEG_DIR.exists():
    os.environ["PATH"] = str(FFMPEG_DIR) + os.pathsep + os.environ.get("PATH", "")


@dataclass
class EmotionFeatures:
    """Extracted emotion/energy features for a segment."""
    segment_start: float
    segment_end: float
    energy_mean: float
    energy_std: float
    pitch_mean: float
    pitch_std: float
    speech_rate: float
    arousal_score: float
    valence_score: float
    intensity_score: float

    @property
    def engagement_score(self) -> float:
        """Combined engagement score (0-1)."""
        return min(1.0, (
            self.arousal_score * 0.3 +
            self.intensity_score * 0.3 +
            min(self.energy_std / 0.1, 1.0) * 0.2 +
            min(self.pitch_std / 50, 1.0) * 0.2
        ))

    @property
    def is_interesting(self) -> bool:
        """Check if segment has interesting audio characteristics."""
        return self.engagement_score > 0.4


class EmotionScanner:
    """
    Scans audio segments for emotional and energy features.
    Uses opensmile for professional-grade audio analysis.
    """

    def __init__(
        self,
        feature_set: str = "eGeMAPSv02",
        min_energy_threshold: float = 0.01,
    ):
        self.feature_set = feature_set
        self.min_energy_threshold = min_energy_threshold
        self._smile = None

    def _get_smile(self):
        """Lazy load opensmile."""
        if self._smile is None:
            import opensmile
            self._smile = opensmile.Smile(
                feature_set=opensmile.FeatureSet.eGeMAPSv02,
                feature_level=opensmile.FeatureLevel.Functionals,
            )
        return self._smile

    def _extract_segment_audio(
        self,
        audio_path: str,
        start: float,
        end: float,
        output_path: str
    ) -> bool:
        """Extract audio segment using ffmpeg."""
        ffmpeg = str(FFMPEG_DIR / "ffmpeg.exe") if FFMPEG_DIR.exists() else "ffmpeg"

        cmd = [
            ffmpeg, "-y", "-i", audio_path,
            "-ss", str(start), "-to", str(end),
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            output_path
        ]

        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
            return Path(output_path).exists()
        except Exception as e:
            logger.warning(f"Failed to extract segment: {e}")
            return False

    def _analyze_with_opensmile(self, audio_path: str) -> Dict[str, float]:
        """Analyze audio with opensmile."""
        try:
            smile = self._get_smile()
            features = smile.process_file(audio_path)

            if features.empty:
                return {}

            row = features.iloc[0]
            return {
                "F0semitoneFrom27.5Hz_sma3nz_amean": row.get("F0semitoneFrom27.5Hz_sma3nz_amean", 0),
                "F0semitoneFrom27.5Hz_sma3nz_stddevNorm": row.get("F0semitoneFrom27.5Hz_sma3nz_stddevNorm", 0),
                "loudness_sma3_amean": row.get("loudness_sma3_amean", 0),
                "loudness_sma3_stddevNorm": row.get("loudness_sma3_stddevNorm", 0),
                "HNRdBACF_sma3nz_amean": row.get("HNRdBACF_sma3nz_amean", 0),
                "jitterLocal_sma3nz_amean": row.get("jitterLocal_sma3nz_amean", 0),
                "shimmerLocaldB_sma3nz_amean": row.get("shimmerLocaldB_sma3nz_amean", 0),
            }
        except Exception as e:
            logger.warning(f"Opensmile analysis failed: {e}")
            return {}

    def _analyze_with_librosa(self, audio_path: str) -> Dict[str, float]:
        """Fallback analysis using librosa."""
        import librosa

        try:
            y, sr = librosa.load(audio_path, sr=16000)

            rms = librosa.feature.rms(y=y)[0]
            pitches, magnitudes = librosa.piptrack(y=y, sr=sr)
            pitch_values = []
            for t in range(pitches.shape[1]):
                index = magnitudes[:, t].argmax()
                pitch = pitches[index, t]
                if pitch > 0:
                    pitch_values.append(pitch)

            return {
                "energy_mean": float(np.mean(rms)),
                "energy_std": float(np.std(rms)),
                "pitch_mean": float(np.mean(pitch_values)) if pitch_values else 0,
                "pitch_std": float(np.std(pitch_values)) if pitch_values else 0,
                "duration": len(y) / sr,
            }
        except Exception as e:
            logger.warning(f"Librosa analysis failed: {e}")
            return {}

    def scan_segment(
        self,
        audio_path: str,
        start: float,
        end: float,
    ) -> Optional[EmotionFeatures]:
        """Scan a single audio segment for emotional features."""

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            if not self._extract_segment_audio(audio_path, start, end, tmp_path):
                return None

            # Try opensmile first
            smile_features = self._analyze_with_opensmile(tmp_path)

            # Fallback to librosa
            librosa_features = self._analyze_with_librosa(tmp_path)

            if not smile_features and not librosa_features:
                return None

            # Combine features
            energy_mean = smile_features.get("loudness_sma3_amean",
                          librosa_features.get("energy_mean", 0))
            energy_std = smile_features.get("loudness_sma3_stddevNorm",
                         librosa_features.get("energy_std", 0))
            pitch_mean = smile_features.get("F0semitoneFrom27.5Hz_sma3nz_amean",
                         librosa_features.get("pitch_mean", 0))
            pitch_std = smile_features.get("F0semitoneFrom27.5Hz_sma3nz_stddevNorm",
                        librosa_features.get("pitch_std", 0))

            duration = end - start
            word_estimate = duration * 2.5  # ~150 words per minute
            speech_rate = word_estimate / duration if duration > 0 else 0

            # Compute scores
            arousal = min(1.0, (energy_std * 2 + pitch_std / 30) / 2)
            intensity = min(1.0, energy_mean / 0.5) if energy_mean > 0 else 0
            valence = 0.5 + (pitch_mean / 500 - 0.5) * 0.3  # Rough estimate

            return EmotionFeatures(
                segment_start=start,
                segment_end=end,
                energy_mean=float(energy_mean),
                energy_std=float(energy_std),
                pitch_mean=float(pitch_mean),
                pitch_std=float(pitch_std),
                speech_rate=speech_rate,
                arousal_score=arousal,
                valence_score=valence,
                intensity_score=intensity,
            )

        finally:
            try:
                os.unlink(tmp_path)
            except:
                pass

    def scan_segments(
        self,
        audio_path: str,
        segments: List[tuple],  # List of (start, end) tuples
    ) -> List[EmotionFeatures]:
        """Scan multiple segments and return features."""
        results = []

        for start, end in segments:
            features = self.scan_segment(audio_path, start, end)
            if features:
                results.append(features)

        # Sort by engagement score
        results.sort(key=lambda x: x.engagement_score, reverse=True)

        logger.info(f"Emotion scan: {len(results)} segments analyzed, "
                   f"{sum(1 for r in results if r.is_interesting)} interesting")

        return results

    def filter_boring_segments(
        self,
        features_list: List[EmotionFeatures],
        min_engagement: float = 0.3
    ) -> List[EmotionFeatures]:
        """Filter out boring/low-engagement segments."""
        return [f for f in features_list if f.engagement_score >= min_engagement]


def scan_audio_emotions(
    audio_path: str,
    segments: List[tuple],
    **kwargs
) -> List[EmotionFeatures]:
    """Convenience function to scan audio emotions."""
    scanner = EmotionScanner(**kwargs)
    return scanner.scan_segments(audio_path, segments)
