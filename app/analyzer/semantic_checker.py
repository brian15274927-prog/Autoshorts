"""
Semantic Checker - Transcription and text analysis for candidate segments.
Uses whisper for ASR and rule-based analysis for content quality.
"""
import os
import re
import logging
import tempfile
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Set

logger = logging.getLogger(__name__)

FFMPEG_DIR = Path(__file__).parent.parent.parent / "tools" / "ffmpeg-master-latest-win64-gpl" / "bin"
if FFMPEG_DIR.exists():
    os.environ["PATH"] = str(FFMPEG_DIR) + os.pathsep + os.environ.get("PATH", "")


# Hook phrases that indicate engaging content
HOOK_PHRASES_RU = {
    "секрет", "важно", "внимание", "факт", "правда", "ошибка",
    "никогда", "всегда", "лучший", "худший", "топ", "главное",
    "почему", "как", "что если", "представьте", "знаете ли",
    "оказывается", "на самом деле", "мало кто знает", "многие думают",
    "первое", "второе", "третье", "во-первых", "во-вторых",
    "проблема", "решение", "совет", "лайфхак", "трюк",
    "история", "случай", "пример", "доказательство",
}

HOOK_PHRASES_EN = {
    "secret", "important", "attention", "fact", "truth", "mistake",
    "never", "always", "best", "worst", "top", "main",
    "why", "how", "what if", "imagine", "did you know",
    "turns out", "actually", "few people know", "many think",
    "first", "second", "third", "firstly", "secondly",
    "problem", "solution", "tip", "hack", "trick",
    "story", "case", "example", "proof",
}

# Garbage phrases to filter out
GARBAGE_PHRASES = {
    "подписывайтесь", "ставьте лайк", "subscribe", "like and subscribe",
    "не забудьте", "don't forget", "ссылка в описании", "link in description",
    "спасибо за просмотр", "thanks for watching", "до встречи", "see you",
    "в комментариях", "in the comments", "поддержите канал", "support the channel",
}


@dataclass
class SemanticScore:
    """Semantic analysis score for a segment."""
    segment_start: float
    segment_end: float
    text: str
    language: str
    hook_score: float  # 0-1, presence of hook phrases
    content_score: float  # 0-1, useful content indicators
    emotion_score: float  # 0-1, emotional language
    structure_score: float  # 0-1, clear structure
    garbage_penalty: float  # 0-1, penalty for garbage content

    @property
    def total_score(self) -> float:
        """Combined semantic score."""
        base = (
            self.hook_score * 0.25 +
            self.content_score * 0.30 +
            self.emotion_score * 0.20 +
            self.structure_score * 0.25
        )
        return max(0, base - self.garbage_penalty)

    @property
    def is_quality_content(self) -> bool:
        return self.total_score > 0.35 and self.garbage_penalty < 0.3


class SemanticChecker:
    """
    Checks semantic quality of audio segments.
    Transcribes with whisper and analyzes text content.
    """

    def __init__(
        self,
        whisper_model: str = "base",
        language: Optional[str] = None,
    ):
        self.whisper_model = whisper_model
        self.language = language
        self._model = None

    def _get_whisper(self):
        """Lazy load whisper model."""
        if self._model is None:
            try:
                import whisper
                self._model = whisper.load_model(self.whisper_model)
                logger.info(f"Whisper model loaded: {self.whisper_model}")
            except Exception as e:
                logger.error(f"Failed to load whisper: {e}")
                raise
        return self._model

    def _extract_segment(self, audio_path: str, start: float, end: float, output: str) -> bool:
        """Extract audio segment."""
        ffmpeg = str(FFMPEG_DIR / "ffmpeg.exe") if FFMPEG_DIR.exists() else "ffmpeg"
        cmd = [ffmpeg, "-y", "-i", audio_path, "-ss", str(start), "-to", str(end),
               "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", output]
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
            return Path(output).exists()
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning(f"FFmpeg extraction failed: {e}")
            return False

    def _transcribe(self, audio_path: str) -> dict:
        """Transcribe audio segment."""
        model = self._get_whisper()
        options = {"word_timestamps": True, "verbose": False}
        if self.language:
            options["language"] = self.language
        return model.transcribe(audio_path, **options)

    def _count_hooks(self, text: str, language: str) -> int:
        """Count hook phrases in text."""
        text_lower = text.lower()
        hooks = HOOK_PHRASES_RU if language == "ru" else HOOK_PHRASES_EN
        return sum(1 for phrase in hooks if phrase in text_lower)

    def _count_garbage(self, text: str) -> int:
        """Count garbage phrases in text."""
        text_lower = text.lower()
        return sum(1 for phrase in GARBAGE_PHRASES if phrase in text_lower)

    def _analyze_structure(self, text: str) -> float:
        """Analyze text structure (lists, clear statements)."""
        score = 0.0

        # Check for numbered lists
        if re.search(r'(первое|второе|третье|first|second|third|\d+\.)', text.lower()):
            score += 0.3

        # Check for clear statements
        if re.search(r'(это|значит|поэтому|потому что|because|therefore|means)', text.lower()):
            score += 0.2

        # Check sentence count (good content has multiple sentences)
        sentences = len(re.findall(r'[.!?]+', text))
        if sentences >= 2:
            score += 0.2
        if sentences >= 4:
            score += 0.1

        # Check for questions (engaging)
        if '?' in text:
            score += 0.2

        return min(1.0, score)

    def _analyze_emotion(self, text: str) -> float:
        """Analyze emotional language."""
        emotion_markers = [
            r'!+', r'\?!', r'[A-ZА-Я]{3,}',  # Exclamations, caps
            r'(wow|amazing|incredible|невероятно|потрясающе|офигеть)',
            r'(важно|критично|срочно|important|critical|urgent)',
        ]

        score = 0.0
        for pattern in emotion_markers:
            if re.search(pattern, text, re.IGNORECASE):
                score += 0.2

        return min(1.0, score)

    def _analyze_content(self, text: str) -> float:
        """Analyze content usefulness."""
        content_markers = [
            r'(совет|tip|advice|рекомендация)',
            r'(способ|method|way|путь)',
            r'(шаг|step|этап)',
            r'(пример|example|случай|case)',
            r'(результат|result|итог)',
            r'(причина|reason|потому)',
            r'(вывод|conclusion|итог)',
        ]

        score = 0.0
        for pattern in content_markers:
            if re.search(pattern, text, re.IGNORECASE):
                score += 0.15

        # Longer content tends to have more value
        words = len(text.split())
        if words > 20:
            score += 0.1
        if words > 50:
            score += 0.1

        return min(1.0, score)

    def check_segment(
        self,
        audio_path: str,
        start: float,
        end: float,
    ) -> Optional[SemanticScore]:
        """Check semantic quality of a segment."""

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            if not self._extract_segment(audio_path, start, end, tmp_path):
                return None

            result = self._transcribe(tmp_path)
            text = result.get("text", "").strip()
            language = result.get("language", "en")

            if not text or len(text) < 10:
                return None

            # Analyze
            hook_count = self._count_hooks(text, language)
            garbage_count = self._count_garbage(text)

            hook_score = min(1.0, hook_count * 0.25)
            content_score = self._analyze_content(text)
            emotion_score = self._analyze_emotion(text)
            structure_score = self._analyze_structure(text)
            garbage_penalty = min(1.0, garbage_count * 0.4)

            return SemanticScore(
                segment_start=start,
                segment_end=end,
                text=text,
                language=language,
                hook_score=hook_score,
                content_score=content_score,
                emotion_score=emotion_score,
                structure_score=structure_score,
                garbage_penalty=garbage_penalty,
            )

        except Exception as e:
            logger.warning(f"Semantic check failed: {e}")
            return None

        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # Ignore cleanup errors

    def check_segments(
        self,
        audio_path: str,
        segments: List[tuple],
    ) -> List[SemanticScore]:
        """Check multiple segments."""
        results = []

        for start, end in segments:
            score = self.check_segment(audio_path, start, end)
            if score:
                results.append(score)

        results.sort(key=lambda x: x.total_score, reverse=True)

        quality_count = sum(1 for r in results if r.is_quality_content)
        logger.info(f"Semantic check: {len(results)} segments, {quality_count} quality")

        return results


def check_semantic_quality(
    audio_path: str,
    segments: List[tuple],
    **kwargs
) -> List[SemanticScore]:
    """Convenience function."""
    checker = SemanticChecker(**kwargs)
    return checker.check_segments(audio_path, segments)
