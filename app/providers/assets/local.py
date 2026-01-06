"""
Local asset provider - REQUIRED fallback.
"""
from pathlib import Path
from typing import List

from .base import BaseAssetsProvider


class LocalAssetsProvider(BaseAssetsProvider):
    """Local filesystem asset provider. Always available."""

    DEFAULT_VIDEOS_DIR = Path(__file__).parent.parent.parent / "demo_assets" / "videos"
    DEFAULT_IMAGES_DIR = Path(__file__).parent.parent.parent / "demo_assets" / "images"

    def __init__(
        self,
        videos_dir: Path | None = None,
        images_dir: Path | None = None,
    ):
        self._videos_dir = videos_dir or self.DEFAULT_VIDEOS_DIR
        self._images_dir = images_dir or self.DEFAULT_IMAGES_DIR
        self._videos_dir.mkdir(parents=True, exist_ok=True)
        self._images_dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "local"

    @property
    def is_available(self) -> bool:
        return True

    def search_videos(self, query: str, limit: int = 5) -> List[Path]:
        videos = self._find_media_files(self._videos_dir, [".mp4", ".mov", ".avi", ".webm"])
        if not videos:
            placeholder = self._create_placeholder_video()
            videos = [placeholder]
        return videos[:limit]

    def search_images(self, query: str, limit: int = 5) -> List[Path]:
        images = self._find_media_files(self._images_dir, [".jpg", ".jpeg", ".png", ".webp"])
        if not images:
            placeholder = self._create_placeholder_image()
            images = [placeholder]
        return images[:limit]

    def _find_media_files(self, directory: Path, extensions: List[str]) -> List[Path]:
        files = []
        if directory.exists():
            for ext in extensions:
                files.extend(directory.glob(f"*{ext}"))
                files.extend(directory.glob(f"*{ext.upper()}"))
        return sorted(files, key=lambda p: p.name)

    def _create_placeholder_video(self) -> Path:
        placeholder = self._videos_dir / "placeholder.mp4"
        if not placeholder.exists():
            self._generate_placeholder_video(placeholder)
        return placeholder

    def _create_placeholder_image(self) -> Path:
        placeholder = self._images_dir / "placeholder.png"
        if not placeholder.exists():
            self._generate_placeholder_image(placeholder)
        return placeholder

    def _generate_placeholder_video(self, output_path: Path) -> None:
        import subprocess
        import shutil

        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            cmd = [
                ffmpeg_path,
                "-y",
                "-f", "lavfi",
                "-i", "color=c=black:s=1080x1920:d=3:r=30",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                str(output_path),
            ]
            subprocess.run(cmd, capture_output=True, check=True)
        else:
            self._generate_minimal_mp4(output_path)

    def _generate_minimal_mp4(self, output_path: Path) -> None:
        mp4_header = bytes([
            0x00, 0x00, 0x00, 0x1C, 0x66, 0x74, 0x79, 0x70,
            0x69, 0x73, 0x6F, 0x6D, 0x00, 0x00, 0x02, 0x00,
            0x69, 0x73, 0x6F, 0x6D, 0x69, 0x73, 0x6F, 0x32,
            0x6D, 0x70, 0x34, 0x31,
            0x00, 0x00, 0x00, 0x08, 0x66, 0x72, 0x65, 0x65,
            0x00, 0x00, 0x00, 0x00, 0x6D, 0x64, 0x61, 0x74,
        ])
        with open(output_path, "wb") as f:
            f.write(mp4_header)

    def _generate_placeholder_image(self, output_path: Path) -> None:
        import struct
        import zlib

        width, height = 1080, 1920

        def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
            chunk = chunk_type + data
            crc = zlib.crc32(chunk) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + chunk + struct.pack(">I", crc)

        signature = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        ihdr = png_chunk(b"IHDR", ihdr_data)

        raw_data = b""
        for _ in range(height):
            raw_data += b"\x00" + b"\x1a\x1a\x1a" * width

        compressed = zlib.compress(raw_data, 9)
        idat = png_chunk(b"IDAT", compressed)
        iend = png_chunk(b"IEND", b"")

        with open(output_path, "wb") as f:
            f.write(signature + ihdr + idat + iend)
