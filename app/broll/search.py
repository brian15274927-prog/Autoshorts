"""
B-Roll Video Search - Pexels & Pixabay Integration
Adapted from MoneyPrinterTurbo's video_search.py
"""
import os
import re
import json
import httpx
import random
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


@dataclass
class VideoClip:
    """Represents a B-Roll video clip."""
    id: str
    url: str
    preview_url: str
    width: int
    height: int
    duration: float
    source: str  # 'pexels' or 'pixabay'
    keywords: List[str]
    local_path: Optional[str] = None


class BRollSearch:
    """
    Search and download B-Roll footage from Pexels and Pixabay.
    """

    PEXELS_API_URL = "https://api.pexels.com/videos/search"
    PIXABAY_API_URL = "https://pixabay.com/api/videos/"

    def __init__(
        self,
        pexels_api_key: Optional[str] = None,
        pixabay_api_key: Optional[str] = None,
        download_dir: Optional[Path] = None,
    ):
        self.pexels_api_key = pexels_api_key or os.getenv("PEXELS_API_KEY", "")
        self.pixabay_api_key = pixabay_api_key or os.getenv("PIXABAY_API_KEY", "")
        self.download_dir = download_dir or Path("data/broll")
        self.download_dir.mkdir(parents=True, exist_ok=True)

        # Minimum video dimensions for quality
        self.min_width = 1080
        self.min_height = 1920  # Vertical format

    async def search_pexels(
        self,
        query: str,
        orientation: str = "portrait",
        per_page: int = 10,
        page: int = 1,
    ) -> List[VideoClip]:
        """Search Pexels for B-Roll videos."""
        if not self.pexels_api_key:
            logger.warning("Pexels API key not configured")
            return []

        params = {
            "query": query,
            "orientation": orientation,
            "per_page": per_page,
            "page": page,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    self.PEXELS_API_URL,
                    params=params,
                    headers={"Authorization": self.pexels_api_key},
                )
                response.raise_for_status()
                data = response.json()

            clips = []
            for video in data.get("videos", []):
                # Find best quality video file
                video_files = video.get("video_files", [])
                best_file = self._get_best_video_file(video_files, orientation)

                if best_file:
                    clip = VideoClip(
                        id=f"pexels_{video['id']}",
                        url=best_file["link"],
                        preview_url=video.get("image", ""),
                        width=best_file.get("width", 0),
                        height=best_file.get("height", 0),
                        duration=video.get("duration", 0),
                        source="pexels",
                        keywords=query.split(),
                    )
                    clips.append(clip)

            logger.info(f"Pexels: Found {len(clips)} clips for '{query}'")
            return clips

        except Exception as e:
            logger.error(f"Pexels search failed: {e}")
            return []

    async def search_pixabay(
        self,
        query: str,
        video_type: str = "all",
        per_page: int = 10,
        page: int = 1,
    ) -> List[VideoClip]:
        """Search Pixabay for B-Roll videos."""
        if not self.pixabay_api_key:
            logger.warning("Pixabay API key not configured")
            return []

        params = {
            "key": self.pixabay_api_key,
            "q": query,
            "video_type": video_type,
            "per_page": per_page,
            "page": page,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.PIXABAY_API_URL, params=params)
                response.raise_for_status()
                data = response.json()

            clips = []
            for hit in data.get("hits", []):
                videos = hit.get("videos", {})
                # Prefer large or medium quality
                video_data = videos.get("large") or videos.get("medium") or {}

                if video_data:
                    clip = VideoClip(
                        id=f"pixabay_{hit['id']}",
                        url=video_data.get("url", ""),
                        preview_url=hit.get("userImageURL", ""),
                        width=video_data.get("width", 0),
                        height=video_data.get("height", 0),
                        duration=hit.get("duration", 0),
                        source="pixabay",
                        keywords=hit.get("tags", "").split(", "),
                    )
                    clips.append(clip)

            logger.info(f"Pixabay: Found {len(clips)} clips for '{query}'")
            return clips

        except Exception as e:
            logger.error(f"Pixabay search failed: {e}")
            return []

    async def search_all(
        self,
        query: str,
        orientation: str = "portrait",
        max_results: int = 20,
    ) -> List[VideoClip]:
        """Search all sources for B-Roll videos."""
        clips = []

        # Search Pexels
        pexels_clips = await self.search_pexels(
            query, orientation=orientation, per_page=max_results
        )
        clips.extend(pexels_clips)

        # Search Pixabay
        pixabay_clips = await self.search_pixabay(query, per_page=max_results)
        clips.extend(pixabay_clips)

        # Shuffle for variety
        random.shuffle(clips)

        return clips[:max_results]

    async def download_clip(self, clip: VideoClip) -> Optional[str]:
        """Download a video clip to local storage."""
        try:
            filename = f"{clip.id}.mp4"
            filepath = self.download_dir / filename

            if filepath.exists():
                clip.local_path = str(filepath)
                return str(filepath)

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(clip.url, follow_redirects=True)
                response.raise_for_status()

                with open(filepath, "wb") as f:
                    f.write(response.content)

            clip.local_path = str(filepath)
            logger.info(f"Downloaded: {filename}")
            return str(filepath)

        except Exception as e:
            logger.error(f"Download failed for {clip.id}: {e}")
            return None

    def _get_best_video_file(
        self, video_files: List[Dict], orientation: str
    ) -> Optional[Dict]:
        """Select the best quality video file for the given orientation."""
        if not video_files:
            return None

        # Filter by orientation preference
        if orientation == "portrait":
            # Prefer vertical videos (height > width)
            vertical = [v for v in video_files if v.get("height", 0) > v.get("width", 0)]
            if vertical:
                video_files = vertical

        # Sort by quality (width * height)
        sorted_files = sorted(
            video_files,
            key=lambda v: v.get("width", 0) * v.get("height", 0),
            reverse=True,
        )

        # Return best quality that's not too large
        for vf in sorted_files:
            width = vf.get("width", 0)
            height = vf.get("height", 0)
            # Skip very large files (>4K)
            if width <= 3840 and height <= 2160:
                return vf

        return sorted_files[0] if sorted_files else None

    @staticmethod
    def extract_keywords_from_text(text: str) -> List[str]:
        """Extract search keywords from transcript text."""
        # Remove common words
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "shall",
            "can", "need", "dare", "ought", "used", "to", "of", "in",
            "for", "on", "with", "at", "by", "from", "as", "into",
            "through", "during", "before", "after", "above", "below",
            "between", "under", "again", "further", "then", "once",
            "here", "there", "when", "where", "why", "how", "all",
            "each", "few", "more", "most", "other", "some", "such",
            "no", "nor", "not", "only", "own", "same", "so", "than",
            "too", "very", "just", "and", "but", "if", "or", "because",
            "until", "while", "this", "that", "these", "those", "i",
            "you", "he", "she", "it", "we", "they", "what", "which",
            "who", "whom", "its", "his", "her", "their", "my", "your",
            # Russian stop words
            "и", "в", "на", "с", "к", "у", "о", "а", "но", "да", "не",
            "что", "это", "как", "он", "она", "они", "мы", "вы", "я",
            "его", "её", "их", "мой", "твой", "наш", "ваш", "свой",
            "который", "какой", "такой", "этот", "тот", "весь", "сам",
            "один", "другой", "всё", "так", "же", "ещё", "уже", "ли",
            "бы", "для", "от", "до", "по", "за", "из", "над", "под",
        }

        # Clean and split text
        words = re.findall(r"\b[a-zA-Zа-яА-ЯёЁ]{3,}\b", text.lower())

        # Filter stop words and get unique
        keywords = list(set(w for w in words if w not in stop_words))

        # Return top keywords by length (longer = more specific)
        keywords.sort(key=len, reverse=True)
        return keywords[:10]
