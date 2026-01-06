"""
Decision Engine - Adaptive clip selection without fixed limits.
Determines how many shorts to create based on content quality.
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from .emotion_scanner import EmotionFeatures
from .semantic_checker import SemanticScore

logger = logging.getLogger(__name__)


@dataclass
class ClipCandidate:
    """A candidate clip for shorts generation."""
    start: float
    end: float
    duration: float = field(init=False)

    # Scores
    emotion_features: Optional[EmotionFeatures] = None
    semantic_score: Optional[SemanticScore] = None

    # Computed
    final_score: float = 0.0
    rank: int = 0
    text: str = ""
    hook_phrase: Optional[str] = None

    def __post_init__(self):
        self.duration = self.end - self.start

    @property
    def is_valid_duration(self) -> bool:
        """Check if duration is valid for shorts (5-60s)."""
        return 5.0 <= self.duration <= 60.0

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "score": self.final_score,
            "rank": self.rank,
            "text": self.text,
            "hook": self.hook_phrase,
        }


class DecisionEngine:
    """
    Makes decisions about which segments become shorts.
    Uses adaptive thresholds based on content distribution.
    """

    def __init__(
        self,
        min_clip_duration: float = 5.0,
        max_clip_duration: float = 60.0,
        ideal_clip_duration: float = 30.0,
        min_quality_threshold: float = 0.3,
        max_clips_per_minute: float = 0.5,  # ~1 clip per 2 minutes of source
    ):
        self.min_clip_duration = min_clip_duration
        self.max_clip_duration = max_clip_duration
        self.ideal_clip_duration = ideal_clip_duration
        self.min_quality_threshold = min_quality_threshold
        self.max_clips_per_minute = max_clips_per_minute

    def _compute_adaptive_threshold(
        self,
        scores: List[float],
        target_percentile: float = 70
    ) -> float:
        """Compute adaptive quality threshold based on score distribution."""
        if not scores:
            return self.min_quality_threshold

        import numpy as np
        sorted_scores = sorted(scores, reverse=True)

        # Use percentile but ensure minimum threshold
        threshold = np.percentile(sorted_scores, 100 - target_percentile)
        return max(self.min_quality_threshold, threshold)

    def _compute_candidate_score(
        self,
        emotion: Optional[EmotionFeatures],
        semantic: Optional[SemanticScore],
    ) -> float:
        """Compute combined score for a candidate."""
        score = 0.0
        weight_sum = 0.0

        if emotion:
            score += emotion.engagement_score * 0.4
            weight_sum += 0.4

        if semantic:
            score += semantic.total_score * 0.6
            weight_sum += 0.6

        if weight_sum == 0:
            return 0.0

        return score / weight_sum

    def _find_optimal_boundaries(
        self,
        start: float,
        end: float,
        text: str,
    ) -> Tuple[float, float]:
        """Adjust boundaries for optimal clip duration."""
        duration = end - start

        # If too short, keep as is
        if duration < self.min_clip_duration:
            return start, end

        # If too long, try to find natural break points
        if duration > self.max_clip_duration:
            # For now, just trim to max duration
            # TODO: Analyze text for sentence boundaries
            return start, start + self.max_clip_duration

        return start, end

    def _merge_overlapping_candidates(
        self,
        candidates: List[ClipCandidate],
        overlap_threshold: float = 0.5,
    ) -> List[ClipCandidate]:
        """Merge overlapping candidates, keeping the best one."""
        if not candidates:
            return []

        # Sort by start time
        sorted_candidates = sorted(candidates, key=lambda x: x.start)
        merged = []

        for candidate in sorted_candidates:
            if not merged:
                merged.append(candidate)
                continue

            last = merged[-1]

            # Check overlap
            overlap = max(0, min(last.end, candidate.end) - max(last.start, candidate.start))
            min_duration = min(last.duration, candidate.duration)

            if overlap / min_duration > overlap_threshold:
                # Keep the one with higher score
                if candidate.final_score > last.final_score:
                    merged[-1] = candidate
            else:
                merged.append(candidate)

        return merged

    def select_clips(
        self,
        emotion_features: List[EmotionFeatures],
        semantic_scores: List[SemanticScore],
        source_duration: float,
    ) -> List[ClipCandidate]:
        """
        Select clips using adaptive thresholds.
        No fixed limit - number of clips depends on content quality.
        """
        # Build candidates from emotion features
        emotion_map = {(e.segment_start, e.segment_end): e for e in emotion_features}
        semantic_map = {(s.segment_start, s.segment_end): s for s in semantic_scores}

        # Combine all segments
        all_segments = set(emotion_map.keys()) | set(semantic_map.keys())

        candidates = []
        all_scores = []

        for start, end in all_segments:
            emotion = emotion_map.get((start, end))
            semantic = semantic_map.get((start, end))

            score = self._compute_candidate_score(emotion, semantic)
            all_scores.append(score)

            # Adjust boundaries
            adj_start, adj_end = self._find_optimal_boundaries(
                start, end,
                semantic.text if semantic else ""
            )

            candidate = ClipCandidate(
                start=adj_start,
                end=adj_end,
                emotion_features=emotion,
                semantic_score=semantic,
                final_score=score,
                text=semantic.text if semantic else "",
            )

            if candidate.is_valid_duration:
                candidates.append(candidate)

        # Compute adaptive threshold
        threshold = self._compute_adaptive_threshold(all_scores)
        logger.info(f"Adaptive threshold: {threshold:.2f}")

        # Filter by threshold
        candidates = [c for c in candidates if c.final_score >= threshold]

        # Merge overlapping
        candidates = self._merge_overlapping_candidates(candidates)

        # Limit based on source duration
        max_clips = int(source_duration / 60 * self.max_clips_per_minute)
        max_clips = max(1, max_clips)  # At least 1 clip

        # Sort by score and take top clips
        candidates.sort(key=lambda x: x.final_score, reverse=True)
        candidates = candidates[:max_clips]

        # Assign ranks
        for i, candidate in enumerate(candidates):
            candidate.rank = i + 1

        logger.info(f"Decision: {len(candidates)} clips selected from {len(all_segments)} candidates")

        return candidates

    def decide_clip_count(
        self,
        source_duration: float,
        quality_scores: List[float],
    ) -> int:
        """
        Decide how many clips to create based on source duration and quality.
        Adaptive - no fixed number.
        """
        if not quality_scores:
            return 0

        # Calculate statistics
        import numpy as np
        mean_quality = np.mean(quality_scores)
        high_quality_count = sum(1 for s in quality_scores if s >= 0.5)

        # Base count on duration
        base_count = int(source_duration / 60 * self.max_clips_per_minute)

        # Adjust based on quality
        if mean_quality > 0.6:
            # High quality source - more clips
            count = int(base_count * 1.5)
        elif mean_quality < 0.3:
            # Low quality source - fewer clips
            count = max(1, base_count // 2)
        else:
            count = base_count

        # Cap at actual high quality segments
        count = min(count, high_quality_count)

        return max(1, count)


def select_best_clips(
    emotion_features: List[EmotionFeatures],
    semantic_scores: List[SemanticScore],
    source_duration: float,
    **kwargs
) -> List[ClipCandidate]:
    """Convenience function."""
    engine = DecisionEngine(**kwargs)
    return engine.select_clips(emotion_features, semantic_scores, source_duration)
