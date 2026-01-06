"""
Intelligent Clip Detection.
Rule-based system for selecting viral-worthy clips from transcripts.
"""
import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from .transcriber import Transcript, Segment, Word

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

# Clip duration constraints
MIN_CLIP_DURATION = 5.0  # seconds
MAX_CLIP_DURATION = 60.0  # seconds
IDEAL_CLIP_DURATION = (15.0, 30.0)  # ideal range

# Garbage words/phrases to filter (Russian)
GARBAGE_PHRASES_RU = {
    # Greetings
    "привет", "здравствуйте", "добрый день", "добрый вечер", "добро пожаловать",
    "всем привет", "приветствую", "привет всем",
    # Filler words
    "ну", "вот", "как бы", "типа", "короче", "значит", "блин", "ладно",
    "так сказать", "в общем", "собственно", "на самом деле",
    # Channel promos
    "подписывайтесь", "подпишитесь", "ставьте лайк", "нажмите колокольчик",
    "ссылка в описании", "напишите в комментариях", "не забудьте подписаться",
    "поддержите канал", "донат", "спонсор",
    # Outros
    "до свидания", "пока", "до встречи", "увидимся", "всем пока",
    "спасибо за просмотр", "до новых встреч",
}

# Garbage words/phrases (English)
GARBAGE_PHRASES_EN = {
    # Greetings
    "hello", "hi", "hey", "welcome", "what's up", "hey guys", "hello everyone",
    # Filler words
    "um", "uh", "like", "you know", "basically", "actually", "literally",
    "kind of", "sort of", "i mean",
    # Channel promos
    "subscribe", "like and subscribe", "hit the bell", "link in description",
    "comment below", "don't forget to subscribe", "support the channel",
    # Outros
    "goodbye", "bye", "see you", "thanks for watching", "until next time",
}

# Hook indicators (start of engaging content)
HOOK_INDICATORS_RU = {
    "секрет", "важно", "внимание", "факт", "правда", "ошибка",
    "никогда", "всегда", "лучший", "худший", "топ", "главное",
    "проблема", "решение", "способ", "метод", "трюк", "хак",
    "почему", "как", "что если", "представьте", "знаете ли вы",
}

HOOK_INDICATORS_EN = {
    "secret", "important", "attention", "fact", "truth", "mistake",
    "never", "always", "best", "worst", "top", "main",
    "problem", "solution", "way", "method", "trick", "hack",
    "why", "how", "what if", "imagine", "did you know",
}


@dataclass
class ClipCandidate:
    """Potential clip with scoring."""
    start: float
    end: float
    text: str
    segments: List[Segment]
    words: List[Word]
    score: float = 0.0
    hook_score: float = 0.0
    content_score: float = 0.0
    timing_score: float = 0.0
    is_garbage: bool = False


@dataclass
class DetectedClip:
    """Final detected clip."""
    clip_id: str
    start: float
    end: float
    duration: float
    text: str
    words: List[dict]
    score: float
    hook_phrase: Optional[str] = None


class ClipDetector:
    """
    Intelligent clip detector using rule-based scoring.

    Scores clips based on:
    - Hook presence (engaging start)
    - Content quality (no garbage)
    - Timing (ideal duration)
    - Completeness (full sentences)
    """

    def __init__(
        self,
        min_duration: float = MIN_CLIP_DURATION,
        max_duration: float = MAX_CLIP_DURATION,
        min_score: float = 0.3,
        max_clips: int = 10,
        language: str = "ru",
    ):
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.min_score = min_score
        self.max_clips = max_clips
        self.language = language

        # Select language-specific patterns
        if language == "ru":
            self.garbage_phrases = GARBAGE_PHRASES_RU
            self.hook_indicators = HOOK_INDICATORS_RU
        else:
            self.garbage_phrases = GARBAGE_PHRASES_EN
            self.hook_indicators = HOOK_INDICATORS_EN

    def detect(self, transcript: Transcript) -> List[DetectedClip]:
        """
        Detect smart clips from transcript.

        Args:
            transcript: Full transcript with segments

        Returns:
            List of detected clips sorted by score
        """
        if not transcript.segments:
            return []

        # Set language from transcript
        if transcript.language:
            if transcript.language.startswith("ru"):
                self.garbage_phrases = GARBAGE_PHRASES_RU
                self.hook_indicators = HOOK_INDICATORS_RU
            else:
                self.garbage_phrases = GARBAGE_PHRASES_EN
                self.hook_indicators = HOOK_INDICATORS_EN

        logger.info(f"Анализ транскрипта: {len(transcript.segments)} сегментов")

        # Generate clip candidates
        candidates = self._generate_candidates(transcript)
        logger.info(f"Сгенерировано {len(candidates)} кандидатов")

        # Score candidates
        scored = self._score_candidates(candidates)
        logger.info(f"Оценено {len(scored)} кандидатов")

        # Filter by minimum score
        filtered = [c for c in scored if c.score >= self.min_score and not c.is_garbage]
        logger.info(f"Отфильтровано {len(filtered)} клипов (score >= {self.min_score})")

        # Remove overlapping clips
        non_overlapping = self._remove_overlaps(filtered)
        logger.info(f"После удаления пересечений: {len(non_overlapping)} клипов")

        # Take top N
        top_clips = sorted(non_overlapping, key=lambda x: x.score, reverse=True)[:self.max_clips]

        # Sort by time
        top_clips.sort(key=lambda x: x.start)

        # Convert to DetectedClip
        detected = []
        for i, c in enumerate(top_clips):
            clip = DetectedClip(
                clip_id=f"clip_{i:02d}",
                start=round(c.start, 2),
                end=round(c.end, 2),
                duration=round(c.end - c.start, 2),
                text=c.text,
                words=[
                    {"word": w.word, "start": round(w.start, 3), "end": round(w.end, 3)}
                    for w in c.words
                ],
                score=round(c.score, 3),
                hook_phrase=self._find_hook(c.text),
            )
            detected.append(clip)

        logger.info(f"Обнаружено {len(detected)} умных клипов")
        return detected

    def _generate_candidates(self, transcript: Transcript) -> List[ClipCandidate]:
        """Generate clip candidates using sliding window."""
        candidates = []
        segments = transcript.segments

        # Try different window sizes
        for window_size in range(1, min(len(segments) + 1, 10)):
            for i in range(len(segments) - window_size + 1):
                window_segments = segments[i:i + window_size]

                start = window_segments[0].start
                end = window_segments[-1].end
                duration = end - start

                # Skip if outside duration constraints
                if duration < self.min_duration or duration > self.max_duration:
                    continue

                # Collect text and words
                text = " ".join(s.text for s in window_segments)
                words = []
                for s in window_segments:
                    words.extend(s.words)

                candidate = ClipCandidate(
                    start=start,
                    end=end,
                    text=text,
                    segments=window_segments,
                    words=words,
                )
                candidates.append(candidate)

        return candidates

    def _score_candidates(self, candidates: List[ClipCandidate]) -> List[ClipCandidate]:
        """Score all candidates."""
        for c in candidates:
            # Check for garbage
            c.is_garbage = self._is_garbage(c.text)
            if c.is_garbage:
                c.score = 0.0
                continue

            # Calculate sub-scores
            c.hook_score = self._calculate_hook_score(c.text)
            c.content_score = self._calculate_content_score(c)
            c.timing_score = self._calculate_timing_score(c.end - c.start)

            # Weighted final score
            c.score = (
                c.hook_score * 0.35 +
                c.content_score * 0.40 +
                c.timing_score * 0.25
            )

        return candidates

    def _is_garbage(self, text: str) -> bool:
        """Check if text is garbage (promos, greetings, etc.)."""
        text_lower = text.lower()

        # Check for garbage phrases
        for phrase in self.garbage_phrases:
            if phrase in text_lower:
                # Allow if it's just a small part of longer content
                if len(text) > 100 and text_lower.count(phrase) == 1:
                    continue
                return True

        # Check for too short content
        words = text.split()
        if len(words) < 5:
            return True

        return False

    def _calculate_hook_score(self, text: str) -> float:
        """Calculate hook score (0-1) based on engaging words."""
        text_lower = text.lower()
        score = 0.0

        # Check for hook indicators
        for hook in self.hook_indicators:
            if hook in text_lower:
                score += 0.2

        # Bonus for question words at start
        first_word = text.split()[0].lower() if text else ""
        question_words = {"почему", "как", "что", "зачем", "когда", "why", "how", "what", "when"}
        if first_word in question_words:
            score += 0.3

        # Bonus for numbers (statistics, lists)
        if re.search(r'\d+', text):
            score += 0.15

        # Bonus for emotional punctuation
        if "!" in text:
            score += 0.1

        return min(score, 1.0)

    def _calculate_content_score(self, candidate: ClipCandidate) -> float:
        """Calculate content quality score."""
        text = candidate.text
        score = 0.5  # Base score

        # Longer content is generally better (up to a point)
        word_count = len(text.split())
        if 20 <= word_count <= 50:
            score += 0.2
        elif 10 <= word_count < 20:
            score += 0.1

        # Complete sentences bonus
        if text.endswith(('.', '!', '?', '。')):
            score += 0.15

        # Starts with capital letter
        if text and text[0].isupper():
            score += 0.05

        # Penalty for too many filler words
        filler_count = sum(
            1 for word in text.lower().split()
            if word in {"ну", "вот", "типа", "um", "uh", "like"}
        )
        if filler_count > 3:
            score -= 0.2

        return max(0.0, min(score, 1.0))

    def _calculate_timing_score(self, duration: float) -> float:
        """Calculate timing score based on ideal duration."""
        ideal_min, ideal_max = IDEAL_CLIP_DURATION

        if ideal_min <= duration <= ideal_max:
            return 1.0
        elif duration < ideal_min:
            # Linearly decrease below ideal
            return max(0.3, duration / ideal_min)
        else:
            # Linearly decrease above ideal
            excess = duration - ideal_max
            return max(0.3, 1.0 - (excess / (self.max_duration - ideal_max)))

    def _find_hook(self, text: str) -> Optional[str]:
        """Find the hook phrase in text."""
        text_lower = text.lower()

        for hook in self.hook_indicators:
            if hook in text_lower:
                # Extract context around hook
                idx = text_lower.find(hook)
                start = max(0, idx - 20)
                end = min(len(text), idx + len(hook) + 30)
                return text[start:end].strip()

        return None

    def _remove_overlaps(self, candidates: List[ClipCandidate]) -> List[ClipCandidate]:
        """Remove overlapping clips, keeping higher scored ones."""
        if not candidates:
            return []

        # Sort by score descending
        sorted_candidates = sorted(candidates, key=lambda x: x.score, reverse=True)
        result = []

        for candidate in sorted_candidates:
            # Check overlap with already selected clips
            overlaps = False
            for selected in result:
                # Check if clips overlap
                if not (candidate.end <= selected.start or candidate.start >= selected.end):
                    overlap_amount = min(candidate.end, selected.end) - max(candidate.start, selected.start)
                    candidate_duration = candidate.end - candidate.start
                    if overlap_amount / candidate_duration > 0.3:  # More than 30% overlap
                        overlaps = True
                        break

            if not overlaps:
                result.append(candidate)

        return result


def detect_smart_clips(
    transcript: Transcript,
    min_duration: float = MIN_CLIP_DURATION,
    max_duration: float = MAX_CLIP_DURATION,
    max_clips: int = 10,
) -> List[DetectedClip]:
    """
    Detect smart clips from transcript.

    Args:
        transcript: Full transcript
        min_duration: Minimum clip duration
        max_duration: Maximum clip duration
        max_clips: Maximum number of clips to return

    Returns:
        List of detected clips
    """
    detector = ClipDetector(
        min_duration=min_duration,
        max_duration=max_duration,
        max_clips=max_clips,
        language=transcript.language,
    )
    return detector.detect(transcript)
