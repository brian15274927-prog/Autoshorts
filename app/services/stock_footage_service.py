"""
Stock Footage Service - Pexels & Pixabay API Integration.
Searches and downloads royalty-free stock videos for faceless content.
"""
import os
import asyncio
import logging
import httpx
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
import aiofiles

logger = logging.getLogger(__name__)

# Output directory for downloaded footage
FOOTAGE_DIR = Path(__file__).parent.parent.parent / "data" / "footage"
FOOTAGE_DIR.mkdir(parents=True, exist_ok=True)


class VideoSource(str, Enum):
    """Video source providers."""
    PEXELS = "pexels"
    PIXABAY = "pixabay"


class VideoOrientation(str, Enum):
    """Video orientation filter."""
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    SQUARE = "square"


@dataclass
class StockVideo:
    """Stock video metadata."""
    id: str
    source: VideoSource
    url: str
    preview_url: str
    duration: float
    width: int
    height: int
    tags: List[str]
    author: str
    download_url: str


@dataclass
class DownloadedFootage:
    """Downloaded footage information."""
    local_path: str
    video: StockVideo
    file_size: int


class StockFootageService:
    """
    Stock Footage Service for searching and downloading royalty-free videos.
    Supports Pexels and Pixabay APIs.
    """

    PEXELS_BASE_URL = "https://api.pexels.com/videos"
    PIXABAY_BASE_URL = "https://pixabay.com/api/videos"

    def __init__(
        self,
        pexels_api_key: Optional[str] = None,
        pixabay_api_key: Optional[str] = None
    ):
        # Stock footage is disabled - use AI generation instead (DALL-E)
        self.pexels_api_key = pexels_api_key or ""
        self.pixabay_api_key = pixabay_api_key or ""

        # Check for placeholder values
        if self.pexels_api_key.startswith("PASTE_"):
            self.pexels_api_key = ""
        if self.pixabay_api_key.startswith("PASTE_"):
            self.pixabay_api_key = ""

        if not self.pexels_api_key and not self.pixabay_api_key:
            logger.info("Stock footage disabled - using AI generation (DALL-E)")

        self.client = httpx.AsyncClient(timeout=30.0)

    async def search(
        self,
        query: str,
        source: VideoSource = VideoSource.PEXELS,
        orientation: VideoOrientation = VideoOrientation.PORTRAIT,
        min_duration: int = 5,
        max_duration: int = 30,
        per_page: int = 10
    ) -> List[StockVideo]:
        """
        Search for stock videos.

        Args:
            query: Search query
            source: Video source (pexels or pixabay)
            orientation: Video orientation filter
            min_duration: Minimum duration in seconds
            max_duration: Maximum duration in seconds
            per_page: Number of results

        Returns:
            List of StockVideo objects
        """
        if source == VideoSource.PEXELS:
            return await self._search_pexels(query, orientation, min_duration, max_duration, per_page)
        else:
            return await self._search_pixabay(query, orientation, min_duration, max_duration, per_page)

    async def search_all_sources(
        self,
        query: str,
        orientation: VideoOrientation = VideoOrientation.PORTRAIT,
        min_duration: int = 5,
        max_duration: int = 30,
        per_page: int = 5
    ) -> List[StockVideo]:
        """Search all available sources and combine results."""
        tasks = []

        if self.pexels_api_key:
            tasks.append(self._search_pexels(query, orientation, min_duration, max_duration, per_page))

        if self.pixabay_api_key:
            tasks.append(self._search_pixabay(query, orientation, min_duration, max_duration, per_page))

        if not tasks:
            logger.warning("No API keys configured for stock footage search")
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)

        videos = []
        for result in results:
            if isinstance(result, list):
                videos.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"Search error: {result}")

        return videos

    async def _search_pexels(
        self,
        query: str,
        orientation: VideoOrientation,
        min_duration: int,
        max_duration: int,
        per_page: int
    ) -> List[StockVideo]:
        """Search Pexels API."""
        if not self.pexels_api_key:
            logger.warning("Pexels API key not configured")
            return []

        headers = {"Authorization": self.pexels_api_key}

        params = {
            "query": query,
            "orientation": orientation.value,
            "per_page": per_page,
            "size": "medium"
        }

        try:
            response = await self.client.get(
                f"{self.PEXELS_BASE_URL}/search",
                headers=headers,
                params=params
            )

            if response.status_code != 200:
                logger.error(f"Pexels API error: {response.status_code}")
                return []

            data = response.json()
            videos = []

            for video in data.get("videos", []):
                duration = video.get("duration", 0)

                # Filter by duration
                if not (min_duration <= duration <= max_duration):
                    continue

                # Get best quality video file
                video_files = video.get("video_files", [])
                if not video_files:
                    continue

                # Prefer HD quality
                best_file = max(video_files, key=lambda x: x.get("height", 0))

                videos.append(StockVideo(
                    id=f"pexels_{video['id']}",
                    source=VideoSource.PEXELS,
                    url=video.get("url", ""),
                    preview_url=video.get("video_pictures", [{}])[0].get("picture", ""),
                    duration=duration,
                    width=best_file.get("width", 1920),
                    height=best_file.get("height", 1080),
                    tags=query.split(),
                    author=video.get("user", {}).get("name", "Unknown"),
                    download_url=best_file.get("link", "")
                ))

            return videos

        except Exception as e:
            logger.error(f"Pexels search failed: {e}")
            return []

    async def _search_pixabay(
        self,
        query: str,
        orientation: VideoOrientation,
        min_duration: int,
        max_duration: int,
        per_page: int
    ) -> List[StockVideo]:
        """Search Pixabay API."""
        if not self.pixabay_api_key:
            logger.warning("Pixabay API key not configured")
            return []

        # Map orientation
        video_type = "all"
        if orientation == VideoOrientation.PORTRAIT:
            # Pixabay doesn't have direct portrait filter, we'll filter results
            pass

        params = {
            "key": self.pixabay_api_key,
            "q": query,
            "video_type": video_type,
            "per_page": per_page * 2,  # Get more to filter
            "safesearch": "true"
        }

        try:
            response = await self.client.get(
                self.PIXABAY_BASE_URL,
                params=params
            )

            if response.status_code != 200:
                logger.error(f"Pixabay API error: {response.status_code}")
                return []

            data = response.json()
            videos = []

            for hit in data.get("hits", []):
                duration = hit.get("duration", 0)

                # Filter by duration
                if not (min_duration <= duration <= max_duration):
                    continue

                # Get video dimensions
                videos_data = hit.get("videos", {})
                large = videos_data.get("large", {})
                medium = videos_data.get("medium", {})

                # Use large if available, else medium
                video_data = large if large.get("url") else medium
                if not video_data.get("url"):
                    continue

                width = video_data.get("width", 1920)
                height = video_data.get("height", 1080)

                # Filter by orientation
                is_portrait = height > width
                is_landscape = width > height

                if orientation == VideoOrientation.PORTRAIT and not is_portrait:
                    continue
                elif orientation == VideoOrientation.LANDSCAPE and not is_landscape:
                    continue

                videos.append(StockVideo(
                    id=f"pixabay_{hit['id']}",
                    source=VideoSource.PIXABAY,
                    url=hit.get("pageURL", ""),
                    preview_url=videos_data.get("tiny", {}).get("url", ""),
                    duration=duration,
                    width=width,
                    height=height,
                    tags=hit.get("tags", "").split(", "),
                    author=hit.get("user", "Unknown"),
                    download_url=video_data.get("url", "")
                ))

                if len(videos) >= per_page:
                    break

            return videos

        except Exception as e:
            logger.error(f"Pixabay search failed: {e}")
            return []

    async def download(
        self,
        video: StockVideo,
        output_dir: Optional[str] = None
    ) -> DownloadedFootage:
        """
        Download a stock video.

        Args:
            video: StockVideo to download
            output_dir: Optional output directory

        Returns:
            DownloadedFootage with local path
        """
        if output_dir is None:
            output_dir = str(FOOTAGE_DIR)

        os.makedirs(output_dir, exist_ok=True)

        filename = f"{video.id}.mp4"
        output_path = os.path.join(output_dir, filename)

        # Check if already downloaded
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            return DownloadedFootage(
                local_path=output_path,
                video=video,
                file_size=file_size
            )

        # Download video
        try:
            async with self.client.stream("GET", video.download_url) as response:
                if response.status_code != 200:
                    raise Exception(f"Download failed: {response.status_code}")

                async with aiofiles.open(output_path, 'wb') as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        await f.write(chunk)

            file_size = os.path.getsize(output_path)

            return DownloadedFootage(
                local_path=output_path,
                video=video,
                file_size=file_size
            )

        except Exception as e:
            logger.error(f"Failed to download video {video.id}: {e}")
            raise

    async def download_for_keywords(
        self,
        keywords: List[str],
        output_dir: Optional[str] = None,
        videos_per_keyword: int = 2,
        orientation: VideoOrientation = VideoOrientation.PORTRAIT
    ) -> List[DownloadedFootage]:
        """
        Download videos matching multiple keywords.

        Args:
            keywords: List of search keywords
            output_dir: Output directory
            videos_per_keyword: Number of videos to download per keyword
            orientation: Video orientation

        Returns:
            List of DownloadedFootage
        """
        if output_dir is None:
            import uuid
            output_dir = str(FOOTAGE_DIR / str(uuid.uuid4()))

        os.makedirs(output_dir, exist_ok=True)

        downloaded = []
        used_ids = set()

        for keyword in keywords:
            # Search all sources
            videos = await self.search_all_sources(
                query=keyword,
                orientation=orientation,
                per_page=videos_per_keyword * 2
            )

            # Download unique videos
            count = 0
            for video in videos:
                if video.id in used_ids:
                    continue

                try:
                    footage = await self.download(video, output_dir)
                    downloaded.append(footage)
                    used_ids.add(video.id)
                    count += 1

                    if count >= videos_per_keyword:
                        break

                except Exception as e:
                    logger.error(f"Failed to download video for '{keyword}': {e}")

        return downloaded

    async def get_footage_for_segments(
        self,
        segments: List[Dict[str, Any]],
        output_dir: Optional[str] = None,
        orientation: VideoOrientation = VideoOrientation.PORTRAIT
    ) -> Dict[int, List[DownloadedFootage]]:
        """
        Get footage for script segments based on their visual keywords.

        Args:
            segments: List of segments with 'visual_keywords' key
            output_dir: Output directory
            orientation: Video orientation

        Returns:
            Dict mapping segment index to list of downloaded footage
        """
        if output_dir is None:
            import uuid
            output_dir = str(FOOTAGE_DIR / str(uuid.uuid4()))

        os.makedirs(output_dir, exist_ok=True)

        result = {}
        used_ids = set()

        for i, segment in enumerate(segments):
            keywords = segment.get("visual_keywords", [])
            if not keywords:
                continue

            segment_footage = []

            for keyword in keywords[:3]:  # Limit to 3 keywords per segment
                videos = await self.search_all_sources(
                    query=keyword,
                    orientation=orientation,
                    per_page=3
                )

                for video in videos:
                    if video.id in used_ids:
                        continue

                    try:
                        footage = await self.download(video, output_dir)
                        segment_footage.append(footage)
                        used_ids.add(video.id)
                        break  # One video per keyword is enough

                    except Exception:
                        continue

            result[i] = segment_footage

        return result

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    @staticmethod
    def get_orientation_for_format(format: str) -> VideoOrientation:
        """Get orientation based on video format."""
        if format == "9:16":
            return VideoOrientation.PORTRAIT
        elif format == "16:9":
            return VideoOrientation.LANDSCAPE
        else:
            return VideoOrientation.SQUARE
