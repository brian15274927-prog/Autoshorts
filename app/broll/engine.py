"""
B-Roll Engine - Automated B-Roll matching and composition
Matches transcript segments to relevant stock footage
"""
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple

from .search import BRollSearch, VideoClip

logger = logging.getLogger(__name__)


@dataclass
class TranscriptSegment:
    """A segment of the transcript with timing."""
    text: str
    start: float
    end: float
    keywords: List[str] = field(default_factory=list)
    broll_clip: Optional[VideoClip] = None


@dataclass
class BRollComposition:
    """The final B-Roll composition for a video."""
    segments: List[TranscriptSegment]
    clips: List[VideoClip]
    total_duration: float
    coverage: float  # Percentage of segments with B-Roll


class BRollEngine:
    """
    Automated B-Roll engine that:
    1. Analyzes transcript segments
    2. Extracts keywords for each segment
    3. Searches for matching B-Roll footage
    4. Downloads and assigns clips to segments
    """

    def __init__(
        self,
        pexels_api_key: Optional[str] = None,
        pixabay_api_key: Optional[str] = None,
        download_dir: Optional[Path] = None,
    ):
        self.search = BRollSearch(
            pexels_api_key=pexels_api_key,
            pixabay_api_key=pixabay_api_key,
            download_dir=download_dir,
        )
        self.cache: Dict[str, List[VideoClip]] = {}

    async def process_transcript(
        self,
        subtitles: List[Dict[str, Any]],
        min_segment_duration: float = 2.0,
        max_clips_per_segment: int = 3,
    ) -> BRollComposition:
        """
        Process transcript and find matching B-Roll for each segment.

        Args:
            subtitles: List of subtitle dicts with 'text', 'start', 'end'
            min_segment_duration: Minimum duration for B-Roll consideration
            max_clips_per_segment: Max clips to search per segment

        Returns:
            BRollComposition with matched clips
        """
        # Convert subtitles to segments
        segments = self._create_segments(subtitles, min_segment_duration)

        # Extract keywords for each segment
        for segment in segments:
            segment.keywords = BRollSearch.extract_keywords_from_text(segment.text)

        # Search and match B-Roll
        all_clips = []
        matched_count = 0

        for segment in segments:
            if not segment.keywords:
                continue

            # Create search query from top keywords
            query = " ".join(segment.keywords[:3])

            # Check cache first
            if query in self.cache:
                clips = self.cache[query]
            else:
                clips = await self.search.search_all(
                    query,
                    orientation="portrait",
                    max_results=max_clips_per_segment,
                )
                self.cache[query] = clips

            if clips:
                # Select best matching clip
                best_clip = self._select_best_clip(clips, segment)
                if best_clip:
                    segment.broll_clip = best_clip
                    if best_clip not in all_clips:
                        all_clips.append(best_clip)
                    matched_count += 1

        # Calculate coverage
        total_duration = sum(s.end - s.start for s in segments)
        coverage = matched_count / len(segments) if segments else 0

        return BRollComposition(
            segments=segments,
            clips=all_clips,
            total_duration=total_duration,
            coverage=coverage,
        )

    async def download_all_clips(
        self,
        composition: BRollComposition,
        progress_callback: Optional[callable] = None,
    ) -> int:
        """
        Download all B-Roll clips in a composition.

        Returns:
            Number of successfully downloaded clips
        """
        downloaded = 0
        total = len(composition.clips)

        for i, clip in enumerate(composition.clips):
            if clip.local_path and Path(clip.local_path).exists():
                downloaded += 1
                continue

            path = await self.search.download_clip(clip)
            if path:
                downloaded += 1

            if progress_callback:
                progress_callback(i + 1, total)

        return downloaded

    def _create_segments(
        self,
        subtitles: List[Dict[str, Any]],
        min_duration: float,
    ) -> List[TranscriptSegment]:
        """Group subtitles into segments suitable for B-Roll."""
        segments = []
        current_text = ""
        current_start = None
        current_end = None

        for sub in subtitles:
            text = sub.get("text", "")
            start = sub.get("start", 0)
            end = sub.get("end", 0)

            if current_start is None:
                current_start = start
                current_text = text
                current_end = end
            else:
                # Check if we should merge or create new segment
                gap = start - current_end
                if gap < 0.5:  # Small gap, merge
                    current_text += " " + text
                    current_end = end
                else:
                    # Save current segment if long enough
                    duration = current_end - current_start
                    if duration >= min_duration:
                        segments.append(TranscriptSegment(
                            text=current_text.strip(),
                            start=current_start,
                            end=current_end,
                        ))
                    # Start new segment
                    current_start = start
                    current_text = text
                    current_end = end

        # Don't forget last segment
        if current_start is not None:
            duration = current_end - current_start
            if duration >= min_duration:
                segments.append(TranscriptSegment(
                    text=current_text.strip(),
                    start=current_start,
                    end=current_end,
                ))

        return segments

    def _select_best_clip(
        self,
        clips: List[VideoClip],
        segment: TranscriptSegment,
    ) -> Optional[VideoClip]:
        """Select the best clip for a segment based on duration and quality."""
        if not clips:
            return None

        segment_duration = segment.end - segment.start

        # Score clips by:
        # 1. Duration match (prefer clips close to segment duration)
        # 2. Quality (prefer higher resolution)
        # 3. Orientation (prefer vertical for shorts)

        def score_clip(clip: VideoClip) -> float:
            score = 0.0

            # Duration match (max 40 points)
            if clip.duration > 0:
                duration_diff = abs(clip.duration - segment_duration)
                duration_score = max(0, 40 - (duration_diff * 5))
                score += duration_score

            # Quality (max 30 points)
            if clip.width > 0 and clip.height > 0:
                pixels = clip.width * clip.height
                quality_score = min(30, pixels / 100000)
                score += quality_score

            # Vertical orientation bonus (max 30 points)
            if clip.height > clip.width:
                score += 30
            elif clip.width > 0:
                ratio = clip.height / clip.width
                score += ratio * 20

            return score

        # Sort by score
        sorted_clips = sorted(clips, key=score_clip, reverse=True)
        return sorted_clips[0] if sorted_clips else None

    def get_keywords_summary(
        self,
        composition: BRollComposition,
    ) -> Dict[str, int]:
        """Get summary of keywords used across all segments."""
        keyword_counts: Dict[str, int] = {}

        for segment in composition.segments:
            for keyword in segment.keywords:
                keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1

        # Sort by count
        return dict(sorted(
            keyword_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        ))
