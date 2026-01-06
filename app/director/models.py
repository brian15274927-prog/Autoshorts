"""
Director Models - Data structures for AI clip decisions.
"""
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class ClipStyle(str, Enum):
    """Suggested visual styles for clips."""
    DRAMATIC = "dramatic"
    FUNNY = "funny"
    EDUCATIONAL = "educational"
    MOTIVATIONAL = "motivational"
    STORYTELLING = "storytelling"
    CONTROVERSIAL = "controversial"
    EMOTIONAL = "emotional"
    ACTION = "action"
    DEFAULT = "default"


@dataclass
class ClipDecision:
    """A single clip decision from Director."""
    clip_id: str
    start: float  # Start time in seconds
    end: float    # End time in seconds
    duration: float
    reason: str   # Why this clip was selected
    score: float  # Relevance/virality score 0-1
    suggested_style: ClipStyle
    title: str    # Suggested title for the clip
    text_preview: str  # Preview of the text content
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "clip_id": self.clip_id,
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "reason": self.reason,
            "score": self.score,
            "suggested_style": self.suggested_style.value,
            "title": self.title,
            "text_preview": self.text_preview,
            "keywords": self.keywords,
        }


@dataclass
class DirectorResult:
    """Result from Director analysis."""
    success: bool
    clips: List[ClipDecision]
    total_duration: float
    source_title: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "clips": [c.to_dict() for c in self.clips],
            "total_duration": self.total_duration,
            "source_title": self.source_title,
            "error": self.error,
        }
