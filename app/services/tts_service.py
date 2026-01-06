"""
TTS Service - Text-to-Speech using edge-tts.
Fast and free TTS with professional voice quality.
"""
import os
import sys
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import subprocess
import json

# CRITICAL: Fix Windows asyncio for subprocess support
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logger = logging.getLogger(__name__)

# Output directory for generated audio
TTS_OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "tts"
TTS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class TTSWord:
    """Word timing information from TTS."""
    word: str
    start: float  # seconds
    end: float    # seconds


@dataclass
class TTSResult:
    """Result from TTS generation."""
    audio_path: str
    duration: float
    words: List[TTSWord]
    srt_path: Optional[str] = None


class VoicePreset:
    """Voice presets for different languages and styles."""

    # Russian voices
    RU_MALE_DMITRY = "ru-RU-DmitryNeural"
    RU_FEMALE_SVETLANA = "ru-RU-SvetlanaNeural"
    RU_FEMALE_DARIYA = "ru-RU-DariyaNeural"

    # English voices
    EN_MALE_GUY = "en-US-GuyNeural"
    EN_FEMALE_JENNY = "en-US-JennyNeural"
    EN_MALE_DAVIS = "en-US-DavisNeural"
    EN_FEMALE_ARIA = "en-US-AriaNeural"

    # Voice characteristics
    PRESETS = {
        "ru_narrator": RU_MALE_DMITRY,
        "ru_friendly": RU_FEMALE_SVETLANA,
        "ru_professional": RU_FEMALE_DARIYA,
        "en_narrator": EN_MALE_GUY,
        "en_friendly": EN_FEMALE_JENNY,
        "en_professional": EN_MALE_DAVIS,
        "en_energetic": EN_FEMALE_ARIA,
    }


class TTSService:
    """
    Text-to-Speech Service using edge-tts.
    Provides fast, free, and high-quality voice synthesis.
    """

    def __init__(
        self,
        voice: str = VoicePreset.RU_MALE_DMITRY,
        rate: str = "+0%",
        pitch: str = "+0Hz",
        volume: str = "+0%"
    ):
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.volume = volume

    async def generate_audio(
        self,
        text: str,
        output_path: Optional[str] = None,
        voice: Optional[str] = None,
        rate: Optional[str] = None
    ) -> TTSResult:
        """
        Generate audio from text using edge-tts.

        Args:
            text: Text to synthesize
            output_path: Optional output file path
            voice: Override default voice
            rate: Override default rate (e.g., "+10%" for faster)

        Returns:
            TTSResult with audio path, duration, and word timings
        """
        if output_path is None:
            import uuid
            output_path = str(TTS_OUTPUT_DIR / f"{uuid.uuid4()}.mp3")

        voice = voice or self.voice
        rate = rate or self.rate

        # Use Python API directly (more reliable on Windows)
        return await self._generate_with_api(text, output_path, voice, rate)

    async def _generate_with_api(
        self,
        text: str,
        output_path: str,
        voice: str,
        rate: str
    ) -> TTSResult:
        """Generate audio using edge-tts Python API."""
        try:
            import edge_tts
            import aiofiles

            communicate = edge_tts.Communicate(text, voice, rate=rate)

            srt_path = output_path.replace('.mp3', '.srt')
            words = []
            word_timings = []

            # Stream audio and collect word timings in one pass
            async with aiofiles.open(output_path, 'wb') as audio_file:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        await audio_file.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        word_timings.append({
                            "text": chunk["text"],
                            "offset": chunk["offset"] / 10000000,  # Convert to seconds
                            "duration": chunk["duration"] / 10000000
                        })

            # Create word list
            for timing in word_timings:
                words.append(TTSWord(
                    word=timing["text"],
                    start=timing["offset"],
                    end=timing["offset"] + timing["duration"]
                ))

            # Generate SRT
            self._generate_srt(words, srt_path)

            duration = self._get_audio_duration(output_path)

            return TTSResult(
                audio_path=output_path,
                duration=duration,
                words=words,
                srt_path=srt_path
            )

        except ImportError:
            logger.error("edge-tts not installed. Install with: pip install edge-tts")
            raise RuntimeError("edge-tts is required for TTS functionality")

    def _parse_srt(self, srt_path: str) -> List[TTSWord]:
        """Parse SRT file to extract word timings."""
        words = []

        if not os.path.exists(srt_path):
            return words

        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        import re

        # SRT format: index, timestamp, text, blank line
        pattern = r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.+?)(?=\n\n|\n$|$)'
        matches = re.findall(pattern, content, re.DOTALL)

        for match in matches:
            start = self._srt_time_to_seconds(match[1])
            end = self._srt_time_to_seconds(match[2])
            text = match[3].strip()

            # Split into words if needed
            for word in text.split():
                word_duration = (end - start) / len(text.split())
                words.append(TTSWord(
                    word=word,
                    start=start,
                    end=start + word_duration
                ))
                start += word_duration

        return words

    def _srt_time_to_seconds(self, time_str: str) -> float:
        """Convert SRT timestamp to seconds."""
        time_str = time_str.replace(',', '.')
        parts = time_str.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds

    def _generate_srt(self, words: List[TTSWord], output_path: str):
        """Generate SRT file from word timings."""
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, word in enumerate(words, 1):
                start = self._seconds_to_srt_time(word.start)
                end = self._seconds_to_srt_time(word.end)
                f.write(f"{i}\n{start} --> {end}\n{word.word}\n\n")

    def _seconds_to_srt_time(self, seconds: float) -> str:
        """Convert seconds to SRT timestamp format."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}".replace('.', ',')

    def _get_audio_duration(self, audio_path: str) -> float:
        """Get audio duration using ffprobe."""
        try:
            # Get ffprobe path from imageio-ffmpeg
            try:
                import imageio_ffmpeg
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
                ffprobe_path = ffmpeg_path.replace("ffmpeg-win-x86_64", "ffprobe-win-x86_64").replace("ffmpeg", "ffprobe")
                if not os.path.exists(ffprobe_path):
                    # Try same directory
                    ffprobe_path = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe.exe")
                    if not os.path.exists(ffprobe_path):
                        ffprobe_path = "ffprobe"
            except ImportError:
                ffprobe_path = "ffprobe"

            cmd = [
                ffprobe_path, "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "json",
                audio_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return float(data["format"]["duration"])
        except Exception as e:
            logger.warning(f"Could not get audio duration: {e}")

        # Fallback: estimate from file size (rough approximation for mp3)
        try:
            file_size = os.path.getsize(audio_path)
            # Average bitrate ~128kbps = 16KB/s
            return file_size / 16000
        except:
            return 0.0

    async def generate_segments_audio(
        self,
        segments: List[Dict[str, Any]],
        output_dir: Optional[str] = None
    ) -> List[TTSResult]:
        """
        Generate audio for multiple script segments.

        Args:
            segments: List of segments with 'text' key
            output_dir: Directory for output files

        Returns:
            List of TTSResult for each segment
        """
        if output_dir is None:
            import uuid
            output_dir = str(TTS_OUTPUT_DIR / str(uuid.uuid4()))

        os.makedirs(output_dir, exist_ok=True)

        results = []

        for i, segment in enumerate(segments):
            text = segment.get("text", "")
            if not text.strip():
                continue

            output_path = os.path.join(output_dir, f"segment_{i:03d}.mp3")

            # Adjust voice based on emotion
            emotion = segment.get("emotion", "neutral")
            rate = self._get_rate_for_emotion(emotion)

            result = await self.generate_audio(text, output_path, rate=rate)
            results.append(result)

        return results

    def _get_rate_for_emotion(self, emotion: str) -> str:
        """Get speaking rate based on emotion."""
        rates = {
            "excited": "+15%",
            "calm": "-10%",
            "serious": "-5%",
            "funny": "+10%",
            "inspirational": "+5%",
            "neutral": "+0%",
            "curious": "+5%",
            "motivational": "+10%",
            "friendly": "+5%",
        }
        return rates.get(emotion, "+0%")

    async def concatenate_audio(
        self,
        audio_files: List[str],
        output_path: str,
        crossfade_ms: int = 0
    ) -> str:
        """
        Concatenate multiple audio files into one.

        Args:
            audio_files: List of audio file paths
            output_path: Output file path
            crossfade_ms: Crossfade duration in milliseconds

        Returns:
            Path to concatenated audio file
        """
        if not audio_files:
            raise ValueError("No audio files to concatenate")

        # Create file list for ffmpeg
        list_file = output_path.replace('.mp3', '_list.txt')
        with open(list_file, 'w', encoding='utf-8') as f:
            for audio_file in audio_files:
                f.write(f"file '{audio_file}'\n")

        # Get FFmpeg path
        ffmpeg_path = "ffmpeg"
        local_paths = [
            r"C:\dake\tools\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe",
            r"C:\ffmpeg\bin\ffmpeg.exe",
        ]
        for path in local_paths:
            if os.path.exists(path):
                ffmpeg_path = path
                break

        cmd = [
            ffmpeg_path, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output_path
        ]

        # Use synchronous subprocess.run to avoid Windows asyncio issues
        import subprocess
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        # Clean up list file
        os.remove(list_file)

        return output_path

    @staticmethod
    def get_available_voices(language: str = "ru") -> List[Dict[str, str]]:
        """Get available voices for a language."""
        voices = {
            "ru": [
                {"id": VoicePreset.RU_MALE_DMITRY, "name": "Дмитрий", "gender": "male", "style": "narrator"},
                {"id": VoicePreset.RU_FEMALE_SVETLANA, "name": "Светлана", "gender": "female", "style": "friendly"},
                {"id": VoicePreset.RU_FEMALE_DARIYA, "name": "Дарья", "gender": "female", "style": "professional"},
            ],
            "en": [
                {"id": VoicePreset.EN_MALE_GUY, "name": "Guy", "gender": "male", "style": "narrator"},
                {"id": VoicePreset.EN_FEMALE_JENNY, "name": "Jenny", "gender": "female", "style": "friendly"},
                {"id": VoicePreset.EN_MALE_DAVIS, "name": "Davis", "gender": "male", "style": "professional"},
                {"id": VoicePreset.EN_FEMALE_ARIA, "name": "Aria", "gender": "female", "style": "energetic"},
            ]
        }
        return voices.get(language, voices["en"])
