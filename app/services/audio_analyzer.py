"""
Audio Analyzer Service - Analyzes uploaded audio files for Music Video generation.

Features:
- Duration detection
- Optional: Whisper transcription for lyrics
- Optional: BPM detection for beat sync
"""

import os
import logging
import subprocess
import json
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

from app.config import config

logger = logging.getLogger(__name__)

# FFprobe path from config
FFPROBE_PATH = config.paths.ffprobe_path


@dataclass
class AudioAnalysis:
    """Result of audio analysis."""
    file_path: str
    duration_seconds: float
    format_name: str
    sample_rate: int
    channels: int
    bitrate: Optional[int]

    # Optional transcription
    transcription: Optional[str] = None
    language: Optional[str] = None

    # Optional beat analysis
    bpm: Optional[float] = None
    beat_times: Optional[list] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "duration_seconds": self.duration_seconds,
            "format_name": self.format_name,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "bitrate": self.bitrate,
            "transcription": self.transcription,
            "language": self.language,
            "bpm": self.bpm,
        }


class AudioAnalyzer:
    """
    Analyzes audio files for Music Video generation.

    Uses FFprobe for basic analysis and optionally Whisper for transcription.
    """

    SUPPORTED_FORMATS = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.wma'}
    MAX_DURATION = 300  # 5 minutes max

    def __init__(self):
        logger.info("[AUDIO_ANALYZER] Service initialized")

    def analyze(self, file_path: str) -> Optional[AudioAnalysis]:
        """
        Analyze an audio file.

        Args:
            file_path: Path to the audio file

        Returns:
            AudioAnalysis with file metadata, or None on error
        """
        if not os.path.exists(file_path):
            logger.error(f"[AUDIO_ANALYZER] File not found: {file_path}")
            return None

        # Check format
        ext = Path(file_path).suffix.lower()
        if ext not in self.SUPPORTED_FORMATS:
            logger.error(f"[AUDIO_ANALYZER] Unsupported format: {ext}")
            return None

        try:
            # Use FFprobe to get audio info
            cmd = [
                FFPROBE_PATH,
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                file_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                logger.error(f"[AUDIO_ANALYZER] FFprobe error: {result.stderr}")
                return None

            data = json.loads(result.stdout)

            # Extract format info
            format_info = data.get('format', {})
            duration = float(format_info.get('duration', 0))

            if duration > self.MAX_DURATION:
                logger.warning(f"[AUDIO_ANALYZER] Audio too long: {duration}s (max {self.MAX_DURATION}s)")
                duration = self.MAX_DURATION

            # Extract stream info (first audio stream)
            audio_stream = None
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'audio':
                    audio_stream = stream
                    break

            if not audio_stream:
                logger.error("[AUDIO_ANALYZER] No audio stream found")
                return None

            analysis = AudioAnalysis(
                file_path=file_path,
                duration_seconds=duration,
                format_name=format_info.get('format_name', 'unknown'),
                sample_rate=int(audio_stream.get('sample_rate', 44100)),
                channels=int(audio_stream.get('channels', 2)),
                bitrate=int(format_info.get('bit_rate', 0)) if format_info.get('bit_rate') else None
            )

            logger.info(f"[AUDIO_ANALYZER] Analysis complete:")
            logger.info(f"  Duration: {analysis.duration_seconds:.1f}s")
            logger.info(f"  Format: {analysis.format_name}")
            logger.info(f"  Sample rate: {analysis.sample_rate}Hz")

            return analysis

        except subprocess.TimeoutExpired:
            logger.error("[AUDIO_ANALYZER] FFprobe timeout")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"[AUDIO_ANALYZER] JSON parse error: {e}")
            return None
        except Exception as e:
            logger.error(f"[AUDIO_ANALYZER] Analysis failed: {e}")
            return None

    async def transcribe_with_whisper(
        self,
        file_path: str,
        language: str = "auto"
    ) -> Optional[str]:
        """
        Transcribe audio using OpenAI Whisper API.

        Args:
            file_path: Path to audio file
            language: Language code or "auto" for detection

        Returns:
            Transcription text or None on error
        """
        try:
            import httpx
            from app.config import config

            api_key = config.ai.openai_api_key
            if not api_key:
                logger.warning("[AUDIO_ANALYZER] No OpenAI API key for Whisper")
                return None

            async with httpx.AsyncClient(timeout=120.0) as client:
                with open(file_path, 'rb') as f:
                    files = {'file': (Path(file_path).name, f, 'audio/mpeg')}
                    data = {'model': 'whisper-1'}

                    if language != "auto":
                        data['language'] = language

                    response = await client.post(
                        'https://api.openai.com/v1/audio/transcriptions',
                        headers={'Authorization': f'Bearer {api_key}'},
                        files=files,
                        data=data
                    )

                if response.status_code != 200:
                    logger.error(f"[AUDIO_ANALYZER] Whisper API error: {response.status_code}")
                    return None

                result = response.json()
                transcription = result.get('text', '')

                logger.info(f"[AUDIO_ANALYZER] Transcription complete: {len(transcription)} chars")
                return transcription

        except Exception as e:
            logger.error(f"[AUDIO_ANALYZER] Transcription failed: {e}")
            return None

    def calculate_segment_count(self, duration_seconds: float, segment_duration: float = 5.0) -> int:
        """
        Calculate number of image segments needed.

        Args:
            duration_seconds: Total audio duration
            segment_duration: Duration per segment (default 5s)

        Returns:
            Number of segments
        """
        import math
        return max(4, math.ceil(duration_seconds / segment_duration))
