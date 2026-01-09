"""
YouTube Video Downloader using yt-dlp.
Windows-compatible with absolute paths.
"""
import os
import re
import uuid
import logging
import tempfile
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any

from app.config import config

logger = logging.getLogger(__name__)

# ============================================================
# PATHS FROM CONFIG (auto-detected)
# ============================================================

# FFmpeg paths from config (auto-detected)
FFMPEG_PATH = config.paths.ffmpeg_path
FFPROBE_PATH = config.paths.ffprobe_path
FFMPEG_DIR = os.path.dirname(FFMPEG_PATH) if os.path.exists(FFMPEG_PATH) else None

# Add FFmpeg to PATH for yt-dlp to find it
if FFMPEG_DIR and os.path.exists(FFMPEG_DIR):
    os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

logger.info(f"YouTube Downloader using FFmpeg: {FFMPEG_PATH}")


@dataclass
class VideoInfo:
    """Downloaded video information."""
    video_id: str
    title: str
    duration: float
    video_path: str
    audio_path: str
    thumbnail_url: Optional[str] = None
    channel: Optional[str] = None
    description: Optional[str] = None
    error: Optional[str] = None  # Error message if download failed


def extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from URL."""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def get_ffmpeg_path() -> str:
    """Get ffmpeg executable path."""
    return FFMPEG_PATH


def get_ffprobe_path() -> str:
    """Get ffprobe executable path."""
    return FFPROBE_PATH


class YouTubeDownloader:
    """
    Downloads YouTube videos using yt-dlp.

    Windows-compatible with:
    - Absolute FFmpeg paths
    - Configurable SSL verification
    - Synchronous subprocess calls
    - Proper error handling
    """

    # SSL bypass can be enabled via environment variable for networks with SSL issues
    # SECURITY WARNING: Only enable if you understand the risks (MITM attacks possible)
    SKIP_SSL_VERIFY = os.getenv("YTDL_SKIP_SSL_VERIFY", "false").lower() == "true"

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir) if output_dir else Path(tempfile.gettempdir()) / "youtube_downloads"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_path = FFMPEG_PATH
        self.ffprobe_path = FFPROBE_PATH
        self.ffmpeg_dir = FFMPEG_DIR

        if self.SKIP_SSL_VERIFY:
            logger.warning("SSL verification disabled for YouTube downloads - this is a security risk!")

    def _find_node_path(self) -> Optional[str]:
        """Find Node.js executable path."""
        node_paths = [
            r"C:\Program Files\nodejs\node.exe",
            r"C:\Program Files (x86)\nodejs\node.exe",
            r"C:\nodejs\node.exe",
        ]
        for path in node_paths:
            if os.path.exists(path):
                return path
        # Try to find in PATH
        try:
            result = subprocess.run(['where', 'node'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split('\n')[0]
        except Exception:
            pass
        return None

    def download(self, url: str) -> VideoInfo:
        """
        Download YouTube video and extract audio.

        Args:
            url: YouTube video URL

        Returns:
            VideoInfo with paths to downloaded files

        Note:
            On error, returns VideoInfo with error field set instead of raising exception.
        """
        try:
            import yt_dlp
        except ImportError:
            return VideoInfo(
                video_id="",
                title="Error",
                duration=0,
                video_path="",
                audio_path="",
                error="yt-dlp not installed. Run: pip install yt-dlp"
            )

        video_id = extract_video_id(url)
        if not video_id:
            return VideoInfo(
                video_id="",
                title="Error",
                duration=0,
                video_path="",
                audio_path="",
                error=f"Invalid YouTube URL: {url}"
            )

        # Create unique folder for this download
        download_id = f"{video_id}_{uuid.uuid4().hex[:8]}"
        download_dir = self.output_dir / download_id
        download_dir.mkdir(parents=True, exist_ok=True)

        video_path = download_dir / "video.mp4"
        audio_path = download_dir / "audio.mp3"

        # ============================================================
        # YT-DLP OPTIONS WITH ABSOLUTE FFMPEG PATH
        # ============================================================

        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': False,
            'extract_flat': False,
            # Explicitly set Node.js path for JS-dependent extractors
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        }

        # SSL verification (disabled only if explicitly configured via YTDL_SKIP_SSL_VERIFY=true)
        if self.SKIP_SSL_VERIFY:
            base_opts['nocheckcertificate'] = True
            base_opts['no_check_certificates'] = True

        # Set Node.js path for yt-dlp JavaScript runtime
        node_path = self._find_node_path()
        if node_path:
            os.environ['NODE_BINARY'] = node_path
            logger.info(f"Node.js runtime: {node_path}")

        # Add FFmpeg location if available
        if self.ffmpeg_dir and os.path.exists(self.ffmpeg_dir):
            base_opts['ffmpeg_location'] = self.ffmpeg_dir

        # yt-dlp options for video
        video_opts = {
            **base_opts,
            'format': 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': str(download_dir / 'video.%(ext)s'),
            'merge_output_format': 'mp4',
        }

        # yt-dlp options for audio only
        audio_opts = {
            **base_opts,
            'format': 'bestaudio/best',
            'outtmpl': str(download_dir / 'audio.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }

        logger.info(f"Downloading video: {url}")
        logger.info(f"FFmpeg location: {self.ffmpeg_dir}")

        try:
            # Get video info first
            info_opts = {**base_opts}
            with yt_dlp.YoutubeDL(info_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                return VideoInfo(
                    video_id=video_id,
                    title="Error",
                    duration=0,
                    video_path="",
                    audio_path="",
                    error="Could not extract video information"
                )

            title = info.get('title', 'Untitled')
            duration = info.get('duration', 0)
            thumbnail = info.get('thumbnail')
            channel = info.get('channel') or info.get('uploader')
            description = info.get('description', '')[:500] if info.get('description') else ''

            # Download video
            logger.info(f"Downloading: {title}")
            with yt_dlp.YoutubeDL(video_opts) as ydl:
                ydl.download([url])

            # Find downloaded video file
            video_files = list(download_dir.glob("video.*"))
            if video_files:
                actual_video = video_files[0]
                if actual_video.suffix != '.mp4':
                    # Convert to mp4 if needed using absolute FFmpeg path
                    result = subprocess.run([
                        self.ffmpeg_path, '-y',
                        '-i', str(actual_video),
                        '-c:v', 'copy', '-c:a', 'aac',
                        str(video_path)
                    ], capture_output=True, text=True, timeout=300)

                    if result.returncode == 0:
                        actual_video.unlink()
                    else:
                        logger.error(f"FFmpeg conversion failed: {result.stderr}")
                else:
                    actual_video.rename(video_path)

            # Download audio
            logger.info(f"Extracting audio...")
            with yt_dlp.YoutubeDL(audio_opts) as ydl:
                ydl.download([url])

            # Find audio file
            audio_files = list(download_dir.glob("audio.*"))
            if audio_files:
                actual_audio = audio_files[0]
                if actual_audio != audio_path:
                    actual_audio.rename(audio_path)

            # Verify files exist
            if not video_path.exists():
                return VideoInfo(
                    video_id=video_id,
                    title=title,
                    duration=duration,
                    video_path="",
                    audio_path=str(audio_path) if audio_path.exists() else "",
                    thumbnail_url=thumbnail,
                    channel=channel,
                    description=description,
                    error="Video download completed but file not found"
                )

            logger.info(f"Download complete: {title} ({duration}s)")

            return VideoInfo(
                video_id=video_id,
                title=title,
                duration=duration,
                video_path=str(video_path),
                audio_path=str(audio_path) if audio_path.exists() else "",
                thumbnail_url=thumbnail,
                channel=channel,
                description=description,
            )

        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"Download error: {error_msg}")
            return VideoInfo(
                video_id=video_id,
                title="Download Error",
                duration=0,
                video_path="",
                audio_path="",
                error=f"Download failed: {error_msg[:200]}"
            )
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Unexpected error: {error_msg}")
            return VideoInfo(
                video_id=video_id,
                title="Error",
                duration=0,
                video_path="",
                audio_path="",
                error=f"Unexpected error: {error_msg[:200]}"
            )

    def get_video_duration(self, video_path: str) -> float:
        """Get video duration using ffprobe."""
        try:
            cmd = [
                self.ffprobe_path, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                video_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                import json
                data = json.loads(result.stdout)
                return float(data.get("format", {}).get("duration", 0))
        except Exception as e:
            logger.error(f"Could not get duration: {e}")
        return 0

    def cleanup(self, video_info: VideoInfo) -> None:
        """Remove downloaded files."""
        if not video_info.video_path:
            return
        video_dir = Path(video_info.video_path).parent
        if video_dir.exists():
            import shutil
            shutil.rmtree(video_dir, ignore_errors=True)


def download_youtube_video(url: str, output_dir: Optional[str] = None) -> VideoInfo:
    """
    Download YouTube video.

    Args:
        url: YouTube video URL
        output_dir: Optional output directory

    Returns:
        VideoInfo with paths to downloaded files (check .error field for failures)
    """
    downloader = YouTubeDownloader(output_dir)
    return downloader.download(url)
