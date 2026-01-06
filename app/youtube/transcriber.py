"""
Audio Transcription using openai-whisper.
"""
import os
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# FFmpeg path configuration
FFMPEG_DIR = Path(__file__).parent.parent.parent / "tools" / "ffmpeg-master-latest-win64-gpl" / "bin"
FFMPEG_PATH = FFMPEG_DIR / "ffmpeg.exe"

# Add ffmpeg to PATH if it exists
if FFMPEG_DIR.exists():
    os.environ["PATH"] = str(FFMPEG_DIR) + os.pathsep + os.environ.get("PATH", "")


@dataclass
class Word:
    """Single word with timing."""
    word: str
    start: float
    end: float
    confidence: float = 1.0


@dataclass
class Segment:
    """Transcript segment."""
    id: int
    start: float
    end: float
    text: str
    words: List[Word] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class Transcript:
    """Full transcript with segments and words."""
    language: str
    duration: float
    segments: List[Segment]
    words: List[Word]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "language": self.language,
            "duration": self.duration,
            "segments": [
                {
                    "id": s.id,
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "words": [
                        {"word": w.word, "start": w.start, "end": w.end}
                        for w in s.words
                    ],
                }
                for s in self.segments
            ],
            "words": [
                {"word": w.word, "start": w.start, "end": w.end}
                for w in self.words
            ],
        }


class Transcriber:
    """Transcribes audio using openai-whisper."""

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
    ):
        """
        Initialize transcriber.

        Args:
            model_size: Whisper model size (tiny, base, small, medium, large)
            device: Device to use (cpu, cuda, auto)
        """
        self.model_size = model_size
        self.device = device
        self._model = None

    def _get_model(self):
        """Lazy load the model."""
        if self._model is None:
            try:
                import whisper
            except ImportError:
                raise ImportError(
                    "openai-whisper not installed. Run: pip install openai-whisper"
                )

            logger.info(f"Loading Whisper model: {self.model_size}")

            # Determine device
            device = self.device
            if device == "auto":
                try:
                    import torch
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except ImportError:
                    device = "cpu"

            self._model = whisper.load_model(self.model_size, device=device)
            logger.info(f"Model loaded: device={device}")

        return self._model

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ) -> Transcript:
        """
        Transcribe audio file.

        Args:
            audio_path: Path to audio file
            language: Optional language code (e.g., 'ru', 'en')

        Returns:
            Transcript with segments and word-level timing
        """
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        model = self._get_model()

        logger.info(f"Transcribing: {audio_path}")

        # Transcribe with word timestamps
        options = {
            "word_timestamps": True,
            "verbose": False,
        }
        if language:
            options["language"] = language

        result = model.transcribe(audio_path, **options)

        segments = []
        all_words = []

        for i, seg in enumerate(result.get("segments", [])):
            words = []

            # Extract words if available
            seg_words = seg.get("words", [])
            for w in seg_words:
                word = Word(
                    word=w.get("word", "").strip(),
                    start=w.get("start", 0),
                    end=w.get("end", 0),
                    confidence=w.get("probability", 1.0),
                )
                words.append(word)
                all_words.append(word)

            segment = Segment(
                id=i,
                start=seg.get("start", 0),
                end=seg.get("end", 0),
                text=seg.get("text", "").strip(),
                words=words,
                confidence=seg.get("avg_logprob", 0) if seg.get("avg_logprob") else 1.0,
            )
            segments.append(segment)

        duration = segments[-1].end if segments else 0
        detected_language = result.get("language", "unknown")

        logger.info(
            f"Transcription complete: {len(segments)} segments, "
            f"{len(all_words)} words, language={detected_language}"
        )

        return Transcript(
            language=detected_language,
            duration=duration,
            segments=segments,
            words=all_words,
        )


def transcribe_audio(
    audio_path: str,
    model_size: str = "base",
    language: Optional[str] = None,
) -> Transcript:
    """
    Transcribe audio file.

    Args:
        audio_path: Path to audio file
        model_size: Whisper model size
        language: Optional language code

    Returns:
        Transcript with segments and words
    """
    transcriber = Transcriber(model_size=model_size)
    return transcriber.transcribe(audio_path, language=language)
