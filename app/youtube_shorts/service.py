"""
YouTube Shorts Service - Core logic for analyzing videos and creating shorts.

Uses Director AI engine for intelligent clip selection.
Windows-compatible with absolute FFmpeg paths and synchronous subprocess.
"""
import os
import json
import uuid
import subprocess
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from app.director import DirectorEngine, ClipDecision, DirectorResult

logger = logging.getLogger(__name__)

# ============================================================
# ABSOLUTE PATHS FOR WINDOWS COMPATIBILITY
# ============================================================

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
SHORTS_DIR = DATA_DIR / "shorts"

# FFmpeg paths - ABSOLUTE
FFMPEG_PATH = r"C:\dake\tools\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe"
FFPROBE_PATH = r"C:\dake\tools\ffmpeg-master-latest-win64-gpl\bin\ffprobe.exe"

# Fallback paths
if not os.path.exists(FFMPEG_PATH):
    fallback_paths = [
        r"C:\Users\user\AppData\Local\Programs\Python\Python313\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]
    for path in fallback_paths:
        if os.path.exists(path):
            FFMPEG_PATH = path
            FFPROBE_PATH = path.replace("ffmpeg.exe", "ffprobe.exe")
            break
    else:
        FFMPEG_PATH = "ffmpeg"
        FFPROBE_PATH = "ffprobe"

# FFmpeg directory for yt-dlp
FFMPEG_DIR = os.path.dirname(FFMPEG_PATH) if os.path.exists(FFMPEG_PATH) else None

# Add to PATH
if FFMPEG_DIR:
    os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

logger.info(f"YouTube Shorts Service using FFmpeg: {FFMPEG_PATH}")


@dataclass
class WordTimestamp:
    """Word with timestamp information."""
    word: str
    start: float
    end: float


@dataclass
class ShortClip:
    """Represents a potential short clip segment."""
    clip_id: str
    start: float
    end: float
    duration: float
    text_preview: str
    words: List[Dict[str, Any]]
    score: float = 0.0


class YouTubeShortsService:
    """
    Service for analyzing YouTube videos and creating shorts.

    Windows-compatible with:
    - Absolute FFmpeg/FFprobe paths
    - Synchronous subprocess calls (no asyncio issues)
    - yt-dlp with proper ffmpeg_location and SSL bypass
    """

    def __init__(self):
        SHORTS_DIR.mkdir(parents=True, exist_ok=True)
        self.director = DirectorEngine()
        self.ffmpeg_path = FFMPEG_PATH
        self.ffprobe_path = FFPROBE_PATH
        self.ffmpeg_dir = FFMPEG_DIR
        logger.info("YouTubeShortsService initialized with Director AI")

    async def download_youtube_video(self, youtube_url: str, job_id: str) -> Dict[str, Any]:
        """
        Download YouTube video and extract audio.

        Uses yt-dlp with:
        - Absolute ffmpeg_location
        - SSL certificate bypass
        - Node.js runtime support (if available)
        """
        output_dir = SHORTS_DIR / job_id
        output_dir.mkdir(parents=True, exist_ok=True)

        video_path = output_dir / "video.mp4"
        audio_path = output_dir / "audio.wav"

        logger.info(f"Downloading video from {youtube_url}")

        try:
            # Build yt-dlp command with all necessary options
            cmd = [
                "yt-dlp",
                "--no-check-certificate",  # Bypass SSL errors
                "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
                "--merge-output-format", "mp4",
                "-o", str(video_path),
            ]

            # Add FFmpeg location if available
            if self.ffmpeg_dir and os.path.exists(self.ffmpeg_dir):
                cmd.extend(["--ffmpeg-location", self.ffmpeg_dir])

            # Try to add Node.js runtime (for some extractors)
            try:
                node_check = subprocess.run(
                    ["node", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if node_check.returncode == 0:
                    # Node.js available, but yt-dlp doesn't need explicit flag
                    logger.info(f"Node.js available: {node_check.stdout.strip()}")
            except Exception:
                logger.warning("Node.js not found in PATH - some features may be limited")

            cmd.append(youtube_url)

            logger.info(f"Running yt-dlp command...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                logger.warning(f"First download attempt failed: {result.stderr[:200]}")
                # Try simpler format
                cmd = [
                    "yt-dlp",
                    "--no-check-certificate",
                    "-f", "best[height<=720]",
                    "-o", str(video_path),
                ]
                if self.ffmpeg_dir:
                    cmd.extend(["--ffmpeg-location", self.ffmpeg_dir])
                cmd.append(youtube_url)

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300
                )

            if not video_path.exists():
                error_msg = result.stderr[:500] if result.stderr else "Unknown error"
                raise Exception(f"Video download failed: {error_msg}")

            # Extract audio using absolute FFmpeg path
            logger.info("Extracting audio...")
            audio_cmd = [
                self.ffmpeg_path, "-y",
                "-i", str(video_path),
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                str(audio_path)
            ]

            result = subprocess.run(
                audio_cmd,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode != 0:
                logger.warning(f"Audio extraction warning: {result.stderr[:200]}")

            # Get video duration using absolute FFprobe path
            duration = self._get_video_duration(str(video_path))

            return {
                "job_id": job_id,
                "video_path": str(video_path),
                "audio_path": str(audio_path) if audio_path.exists() else None,
                "duration": duration
            }

        except subprocess.TimeoutExpired:
            logger.error("Download timed out")
            raise Exception("Video download timed out after 5 minutes")
        except Exception as e:
            logger.error(f"Download failed: {e}")
            raise

    def _get_video_duration(self, video_path: str) -> float:
        """Get video duration using FFprobe."""
        try:
            probe_cmd = [
                self.ffprobe_path, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                video_path
            ]
            result = subprocess.run(
                probe_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                data = json.loads(result.stdout)
                return float(data.get("format", {}).get("duration", 0))
        except Exception as e:
            logger.error(f"Could not get duration: {e}")
        return 0

    async def transcribe_audio(self, audio_path: str, job_id: str) -> List[WordTimestamp]:
        """Transcribe audio and get word-level timestamps using Whisper."""
        logger.info(f"Transcribing audio: {audio_path}")

        output_dir = SHORTS_DIR / job_id

        try:
            # Use whisper CLI for transcription with word timestamps
            cmd = [
                "whisper",
                audio_path,
                "--model", "base",
                "--output_format", "json",
                "--word_timestamps", "True",
                "--output_dir", str(output_dir)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )

            # Find the JSON output file
            json_files = list(output_dir.glob("*.json"))
            if not json_files:
                # Fallback: create simple timestamps from segments
                return await self._fallback_transcription(audio_path, job_id)

            with open(json_files[0], "r", encoding="utf-8") as f:
                data = json.load(f)

            words = []
            for segment in data.get("segments", []):
                for word_data in segment.get("words", []):
                    words.append(WordTimestamp(
                        word=word_data.get("word", "").strip(),
                        start=word_data.get("start", 0),
                        end=word_data.get("end", 0)
                    ))

            # If no word-level timestamps, create from segments
            if not words:
                for segment in data.get("segments", []):
                    text = segment.get("text", "").strip()
                    start = segment.get("start", 0)
                    end = segment.get("end", 0)

                    # Split segment into words
                    segment_words = text.split()
                    if segment_words:
                        word_duration = (end - start) / len(segment_words)
                        for i, word in enumerate(segment_words):
                            words.append(WordTimestamp(
                                word=word,
                                start=start + i * word_duration,
                                end=start + (i + 1) * word_duration
                            ))

            # Save words to file
            words_path = output_dir / "words.json"
            with open(words_path, "w", encoding="utf-8") as f:
                json.dump([asdict(w) for w in words], f, indent=2)

            return words

        except subprocess.TimeoutExpired:
            logger.error("Transcription timed out")
            return await self._fallback_transcription(audio_path, job_id)
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return await self._fallback_transcription(audio_path, job_id)

    async def _fallback_transcription(self, audio_path: str, job_id: str) -> List[WordTimestamp]:
        """Fallback transcription method using faster-whisper or basic approach."""
        logger.info("Using fallback transcription method")

        try:
            # Try faster-whisper
            from faster_whisper import WhisperModel

            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, info = model.transcribe(audio_path, word_timestamps=True)

            words = []
            for segment in segments:
                if hasattr(segment, 'words') and segment.words:
                    for word in segment.words:
                        words.append(WordTimestamp(
                            word=word.word.strip(),
                            start=word.start,
                            end=word.end
                        ))
                else:
                    # Split segment text into words
                    text = segment.text.strip()
                    segment_words = text.split()
                    if segment_words:
                        word_duration = (segment.end - segment.start) / len(segment_words)
                        for i, w in enumerate(segment_words):
                            words.append(WordTimestamp(
                                word=w,
                                start=segment.start + i * word_duration,
                                end=segment.start + (i + 1) * word_duration
                            ))

            return words

        except ImportError:
            logger.warning("faster-whisper not available, returning empty timestamps")
            return []
        except Exception as e:
            logger.error(f"Fallback transcription also failed: {e}")
            return []

    def find_short_clips(
        self,
        words: List[WordTimestamp],
        video_duration: float,
        source_title: Optional[str] = None,
        min_duration: float = 15.0,
        max_duration: float = 60.0,
        target_duration: float = 30.0
    ) -> List[ShortClip]:
        """
        Find potential short clip segments using Director AI.

        Director analyzes the transcript and makes intelligent decisions
        about which moments are most engaging for short-form content.
        """
        if not words:
            # Create a default clip for the whole video
            return [ShortClip(
                clip_id=str(uuid.uuid4()),
                start=0,
                end=min(video_duration, max_duration),
                duration=min(video_duration, max_duration),
                text_preview="[No transcription available]",
                words=[],
                score=0.5
            )]

        # Convert words to segments for Director
        # Group words into ~5 second segments
        segments = []
        current_segment = {"start": 0, "end": 0, "text": ""}
        segment_words = []

        for word in words:
            if not current_segment["text"]:
                current_segment["start"] = word.start

            current_segment["end"] = word.end
            current_segment["text"] += " " + word.word
            segment_words.append(asdict(word))

            # Create new segment every ~5 seconds or at sentence end
            duration = current_segment["end"] - current_segment["start"]
            is_sentence_end = any(p in word.word for p in ['.', '!', '?'])

            if duration >= 5.0 or (is_sentence_end and duration >= 2.0):
                current_segment["text"] = current_segment["text"].strip()
                current_segment["words"] = segment_words
                segments.append(current_segment)
                current_segment = {"start": 0, "end": 0, "text": ""}
                segment_words = []

        # Add remaining segment
        if current_segment["text"].strip():
            current_segment["text"] = current_segment["text"].strip()
            current_segment["words"] = segment_words
            segments.append(current_segment)

        # Use Director AI to analyze and find best clips
        logger.info(f"Director analyzing {len(segments)} segments...")
        result: DirectorResult = self.director.analyze(
            transcript_segments=segments,
            total_duration=video_duration,
            source_title=source_title
        )

        # Convert Director decisions to ShortClip objects
        clips = []
        for decision in result.clips:
            # Find words in this clip's time range
            clip_words = []
            for word in words:
                if word.start >= decision.start and word.end <= decision.end:
                    clip_words.append(asdict(word))

            clips.append(ShortClip(
                clip_id=decision.clip_id,
                start=decision.start,
                end=decision.end,
                duration=decision.duration,
                text_preview=decision.text_preview or decision.title,
                words=clip_words,
                score=decision.score
            ))

        logger.info(f"Director found {len(clips)} clips")

        # Sort by score
        clips.sort(key=lambda c: c.score, reverse=True)

        return clips[:10]  # Return top 10 clips

    async def create_clip_video(
        self,
        job_id: str,
        clip: ShortClip,
        video_path: str
    ) -> str:
        """Extract clip from original video using absolute FFmpeg path."""
        output_dir = SHORTS_DIR / job_id / "clips"
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / f"{clip.clip_id}.mp4"

        # Extract clip using absolute FFmpeg path
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", video_path,
            "-ss", str(clip.start),
            "-t", str(clip.duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            str(output_path)
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )

        if not output_path.exists():
            error_msg = result.stderr[:200] if result.stderr else "Unknown error"
            raise Exception(f"Clip extraction failed: {error_msg}")

        return str(output_path)

    async def analyze_youtube_url(
        self,
        youtube_url: str,
        max_clips: int = 5,
        min_duration: float = 15.0,
        max_duration: float = 60.0,
        goal: str = "viral"
    ) -> Dict[str, Any]:
        """
        Full analysis pipeline for a YouTube URL.

        Args:
            youtube_url: YouTube video URL
            max_clips: Maximum number of clips to return
            min_duration: Minimum clip duration in seconds
            max_duration: Maximum clip duration in seconds
            goal: Analysis goal (viral, educational, etc.)
        """
        job_id = str(uuid.uuid4())

        # Download video
        download_result = await self.download_youtube_video(youtube_url, job_id)

        # Transcribe
        words = await self.transcribe_audio(download_result["audio_path"], job_id)

        # Find clips with specified parameters
        clips = self.find_short_clips(
            words,
            download_result["duration"],
            source_title=goal,  # Use goal as source title hint
            min_duration=min_duration,
            max_duration=max_duration
        )

        # Limit to max_clips
        clips = clips[:max_clips]

        # Save analysis result
        result = {
            "job_id": job_id,
            "youtube_url": youtube_url,
            "video_duration": download_result["duration"],
            "video_path": download_result["video_path"],
            "clips": [asdict(c) for c in clips]
        }

        result_path = SHORTS_DIR / job_id / "analysis.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        return result

    def get_analysis(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get analysis result by job ID."""
        result_path = SHORTS_DIR / job_id / "analysis.json"
        if result_path.exists():
            with open(result_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
