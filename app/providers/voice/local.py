"""
Local voice provider - REQUIRED fallback.
"""
import struct
import tempfile
import uuid
from pathlib import Path

from .base import BaseVoiceProvider


class LocalVoiceProvider(BaseVoiceProvider):
    """Local voice provider. Generates silent or demo WAV files."""

    SAMPLE_RATE = 44100
    CHANNELS = 1
    BITS_PER_SAMPLE = 16
    WORDS_PER_SECOND = 2.5
    OUTPUT_DIR = Path(tempfile.gettempdir()) / "dake_voice"

    def __init__(self, output_dir: Path | None = None):
        self._output_dir = output_dir or self.OUTPUT_DIR
        self._output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "local"

    @property
    def is_available(self) -> bool:
        return True

    def synthesize(self, text: str, lang: str = "en") -> Path:
        duration = self._calculate_duration(text)
        output_path = self._output_dir / f"{uuid.uuid4().hex}.wav"
        self._generate_silent_wav(output_path, duration)
        return output_path

    def _calculate_duration(self, text: str) -> float:
        if not text or not text.strip():
            return 1.0
        word_count = len(text.split())
        duration = word_count / self.WORDS_PER_SECOND
        return max(1.0, min(duration, 300.0))

    def _generate_silent_wav(self, output_path: Path, duration: float) -> None:
        num_samples = int(self.SAMPLE_RATE * duration)
        bytes_per_sample = self.BITS_PER_SAMPLE // 8
        data_size = num_samples * self.CHANNELS * bytes_per_sample

        with open(output_path, "wb") as f:
            f.write(b"RIFF")
            f.write(struct.pack("<I", 36 + data_size))
            f.write(b"WAVE")

            f.write(b"fmt ")
            f.write(struct.pack("<I", 16))
            f.write(struct.pack("<H", 1))
            f.write(struct.pack("<H", self.CHANNELS))
            f.write(struct.pack("<I", self.SAMPLE_RATE))
            byte_rate = self.SAMPLE_RATE * self.CHANNELS * bytes_per_sample
            f.write(struct.pack("<I", byte_rate))
            block_align = self.CHANNELS * bytes_per_sample
            f.write(struct.pack("<H", block_align))
            f.write(struct.pack("<H", self.BITS_PER_SAMPLE))

            f.write(b"data")
            f.write(struct.pack("<I", data_size))
            silence = b"\x00" * data_size
            f.write(silence)
