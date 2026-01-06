"""
YouTube Processing Module.
Downloads videos and extracts transcripts using yt-dlp and faster-whisper.
"""
from .downloader import YouTubeDownloader, download_youtube_video
from .transcriber import Transcriber, transcribe_audio
from .clip_detector import ClipDetector, detect_smart_clips

__all__ = [
    "YouTubeDownloader",
    "download_youtube_video",
    "Transcriber",
    "transcribe_audio",
    "ClipDetector",
    "detect_smart_clips",
]
