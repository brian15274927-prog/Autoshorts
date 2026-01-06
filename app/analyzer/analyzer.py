"""
Audio Analyzer - Main orchestrator for AI-powered video analysis.
Coordinates speech detection, emotion analysis, semantic checking, and clip selection.
"""
import os
import logging
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor

from .speech_map import SpeechMapper, SpeechSegment
from .emotion_scanner import EmotionScanner, EmotionFeatures
from .semantic_checker import SemanticChecker, SemanticScore
from .decision_engine import DecisionEngine, ClipCandidate

logger = logging.getLogger(__name__)

FFMPEG_DIR = Path(__file__).parent.parent.parent / "tools" / "ffmpeg-master-latest-win64-gpl" / "bin"
if FFMPEG_DIR.exists():
    os.environ["PATH"] = str(FFMPEG_DIR) + os.pathsep + os.environ.get("PATH", "")


@dataclass
class DetectedClip:
    """A detected clip ready for shorts creation."""
    clip_id: str
    start: float
    end: float
    duration: float
    score: float
    rank: int
    text: str
    hook_phrase: Optional[str] = None
    emotion_score: float = 0.0
    semantic_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "clip_id": self.clip_id,
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "score": self.score,
            "rank": self.rank,
            "text": self.text,
            "hook_phrase": self.hook_phrase,
        }


@dataclass
class AnalysisResult:
    """Result of full audio analysis."""
    audio_path: str
    duration: float
    clips: List[DetectedClip]
    speech_segments_count: int
    analyzed_segments_count: int
    processing_time: float

    @property
    def clip_count(self) -> int:
        return len(self.clips)

    def to_dict(self) -> dict:
        return {
            "audio_path": self.audio_path,
            "duration": self.duration,
            "clip_count": self.clip_count,
            "clips": [c.to_dict() for c in self.clips],
            "speech_segments": self.speech_segments_count,
            "analyzed_segments": self.analyzed_segments_count,
            "processing_time": self.processing_time,
        }


class AudioAnalyzer:
    """
    Main analyzer that orchestrates the full analysis pipeline.

    Pipeline:
    1. Speech Map - Detect all speech regions
    2. Emotion Scan - Analyze energy/emotion for each segment
    3. Semantic Check - Transcribe and analyze content (candidates only)
    4. Decision Engine - Select best clips adaptively
    """

    def __init__(
        self,
        whisper_model: str = "base",
        language: Optional[str] = None,
        min_clip_duration: float = 5.0,
        max_clip_duration: float = 60.0,
        use_pyannote: bool = False,  # Disable by default for speed
        parallel_workers: int = 2,
    ):
        self.whisper_model = whisper_model
        self.language = language
        self.min_clip_duration = min_clip_duration
        self.max_clip_duration = max_clip_duration
        self.use_pyannote = use_pyannote
        self.parallel_workers = parallel_workers

        # Components
        self.speech_mapper = SpeechMapper(
            use_pyannote=use_pyannote,
            min_speech_duration=min_clip_duration,
        )
        self.emotion_scanner = EmotionScanner()
        self.semantic_checker = SemanticChecker(
            whisper_model=whisper_model,
            language=language,
        )
        self.decision_engine = DecisionEngine(
            min_clip_duration=min_clip_duration,
            max_clip_duration=max_clip_duration,
        )

    def _get_audio_duration(self, audio_path: str) -> float:
        """Get audio duration using librosa."""
        import librosa
        y, sr = librosa.load(audio_path, sr=None, duration=1)
        return librosa.get_duration(path=audio_path)

    def _group_segments_for_analysis(
        self,
        segments: List[SpeechSegment],
    ) -> List[tuple]:
        """Group short segments for analysis."""
        result = []
        current_start = None
        current_end = None

        for seg in segments:
            if current_start is None:
                current_start = seg.start
                current_end = seg.end
            elif seg.start - current_end < 2.0:  # Merge if gap < 2s
                current_end = seg.end
            else:
                if current_end - current_start >= self.min_clip_duration:
                    result.append((current_start, current_end))
                current_start = seg.start
                current_end = seg.end

        if current_start is not None and current_end - current_start >= self.min_clip_duration:
            result.append((current_start, current_end))

        return result

    def analyze(
        self,
        audio_path: str,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ) -> AnalysisResult:
        """
        Run full analysis pipeline on audio file.

        Args:
            audio_path: Path to audio file
            progress_callback: Optional callback(stage, progress 0-1)

        Returns:
            AnalysisResult with detected clips
        """
        import time
        start_time = time.time()

        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio not found: {audio_path}")

        def report_progress(stage: str, progress: float):
            if progress_callback:
                progress_callback(stage, progress)
            logger.info(f"[{stage}] {progress*100:.0f}%")

        # Step 1: Get duration
        report_progress("init", 0.05)
        duration = self._get_audio_duration(audio_path)
        logger.info(f"Audio duration: {duration:.1f}s")

        # Step 2: Speech Map
        report_progress("speech_map", 0.1)
        speech_segments = self.speech_mapper.map_speech(audio_path)
        logger.info(f"Speech segments: {len(speech_segments)}")

        if not speech_segments:
            return AnalysisResult(
                audio_path=audio_path,
                duration=duration,
                clips=[],
                speech_segments_count=0,
                analyzed_segments_count=0,
                processing_time=time.time() - start_time,
            )

        # Group segments for analysis
        analysis_segments = self._group_segments_for_analysis(speech_segments)
        logger.info(f"Grouped segments: {len(analysis_segments)}")

        # Step 3: Emotion Scan (fast)
        report_progress("emotion_scan", 0.3)
        emotion_features = self.emotion_scanner.scan_segments(
            audio_path,
            analysis_segments,
        )

        # Filter to top candidates for semantic check (expensive)
        interesting_segments = [
            (e.segment_start, e.segment_end)
            for e in emotion_features
            if e.is_interesting
        ]
        logger.info(f"Interesting segments: {len(interesting_segments)}")

        # Step 4: Semantic Check (only for interesting segments)
        report_progress("semantic_check", 0.5)
        semantic_scores = []

        if interesting_segments:
            # Limit to top segments to avoid long processing
            max_semantic_checks = min(20, len(interesting_segments))
            top_segments = interesting_segments[:max_semantic_checks]

            semantic_scores = self.semantic_checker.check_segments(
                audio_path,
                top_segments,
            )

        report_progress("decision", 0.8)

        # Step 5: Decision Engine
        candidates = self.decision_engine.select_clips(
            emotion_features,
            semantic_scores,
            duration,
        )

        # Convert to DetectedClip
        clips = []
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"

        for candidate in candidates:
            clip_id = f"{batch_id}_clip_{candidate.rank:02d}"

            emotion_score = 0.0
            if candidate.emotion_features:
                emotion_score = candidate.emotion_features.engagement_score

            semantic_score_val = 0.0
            if candidate.semantic_score:
                semantic_score_val = candidate.semantic_score.total_score

            clips.append(DetectedClip(
                clip_id=clip_id,
                start=candidate.start,
                end=candidate.end,
                duration=candidate.duration,
                score=candidate.final_score,
                rank=candidate.rank,
                text=candidate.text,
                hook_phrase=candidate.hook_phrase,
                emotion_score=emotion_score,
                semantic_score=semantic_score_val,
            ))

        report_progress("complete", 1.0)

        processing_time = time.time() - start_time
        logger.info(f"Analysis complete: {len(clips)} clips in {processing_time:.1f}s")

        return AnalysisResult(
            audio_path=audio_path,
            duration=duration,
            clips=clips,
            speech_segments_count=len(speech_segments),
            analyzed_segments_count=len(analysis_segments),
            processing_time=processing_time,
        )


def analyze_audio(
    audio_path: str,
    whisper_model: str = "base",
    language: Optional[str] = None,
    **kwargs
) -> AnalysisResult:
    """Convenience function to analyze audio."""
    analyzer = AudioAnalyzer(
        whisper_model=whisper_model,
        language=language,
        **kwargs
    )
    return analyzer.analyze(audio_path)
