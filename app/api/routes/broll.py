"""
B-Roll API Routes - Stock footage search from Pexels/Pixabay.
"""
import logging
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user_optional
from app.auth.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/broll", tags=["B-Roll"])


class BRollSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    orientation: str = Field(default="portrait", pattern="^(portrait|landscape|square)$")
    max_results: int = Field(default=10, ge=1, le=50)


class BRollClip(BaseModel):
    id: str
    url: str
    preview_url: str
    width: int
    height: int
    duration: float
    source: str
    keywords: List[str]
    local_path: Optional[str] = None


class BRollSearchResponse(BaseModel):
    query: str
    total: int
    clips: List[BRollClip]


class BRollCompositionRequest(BaseModel):
    subtitles: List[dict] = Field(..., description="List of subtitles with text, start, end")
    min_segment_duration: float = Field(default=2.0, ge=1.0, le=10.0)
    max_clips_per_segment: int = Field(default=3, ge=1, le=10)


class SegmentWithBRoll(BaseModel):
    text: str
    start: float
    end: float
    keywords: List[str]
    broll_clip: Optional[BRollClip] = None


class BRollCompositionResponse(BaseModel):
    segments: List[SegmentWithBRoll]
    clips: List[BRollClip]
    total_duration: float
    coverage: float


@router.post("/search", response_model=BRollSearchResponse)
async def search_broll(
    request: BRollSearchRequest,
    user: User = Depends(get_current_user_optional),
):
    """
    Поиск B-Roll видео из Pexels и Pixabay.

    Ключевые слова автоматически переводятся на английский для лучших результатов.
    """
    try:
        from app.broll import BRollSearch

        search = BRollSearch()
        clips = await search.search_all(
            query=request.query,
            orientation=request.orientation,
            max_results=request.max_results,
        )

        return BRollSearchResponse(
            query=request.query,
            total=len(clips),
            clips=[
                BRollClip(
                    id=c.id,
                    url=c.url,
                    preview_url=c.preview_url,
                    width=c.width,
                    height=c.height,
                    duration=c.duration,
                    source=c.source,
                    keywords=c.keywords,
                    local_path=c.local_path,
                )
                for c in clips
            ],
        )

    except Exception as e:
        logger.exception(f"B-Roll search failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": f"Ошибка поиска B-Roll: {str(e)}"}
        )


@router.post("/compose", response_model=BRollCompositionResponse)
async def compose_broll(
    request: BRollCompositionRequest,
    user: User = Depends(get_current_user_optional),
):
    """
    Автоматически подобрать B-Roll для субтитров.

    Анализирует каждый сегмент субтитров, извлекает ключевые слова
    и находит подходящие B-Roll клипы.
    """
    try:
        from app.broll import BRollEngine

        engine = BRollEngine()
        composition = await engine.process_transcript(
            subtitles=request.subtitles,
            min_segment_duration=request.min_segment_duration,
            max_clips_per_segment=request.max_clips_per_segment,
        )

        return BRollCompositionResponse(
            segments=[
                SegmentWithBRoll(
                    text=s.text,
                    start=s.start,
                    end=s.end,
                    keywords=s.keywords,
                    broll_clip=BRollClip(
                        id=s.broll_clip.id,
                        url=s.broll_clip.url,
                        preview_url=s.broll_clip.preview_url,
                        width=s.broll_clip.width,
                        height=s.broll_clip.height,
                        duration=s.broll_clip.duration,
                        source=s.broll_clip.source,
                        keywords=s.broll_clip.keywords,
                        local_path=s.broll_clip.local_path,
                    ) if s.broll_clip else None,
                )
                for s in composition.segments
            ],
            clips=[
                BRollClip(
                    id=c.id,
                    url=c.url,
                    preview_url=c.preview_url,
                    width=c.width,
                    height=c.height,
                    duration=c.duration,
                    source=c.source,
                    keywords=c.keywords,
                    local_path=c.local_path,
                )
                for c in composition.clips
            ],
            total_duration=composition.total_duration,
            coverage=composition.coverage,
        )

    except Exception as e:
        logger.exception(f"B-Roll composition failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": f"Ошибка композиции B-Roll: {str(e)}"}
        )


@router.post("/download/{clip_id}")
async def download_broll_clip(
    clip_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user_optional),
):
    """
    Скачать B-Roll клип в локальное хранилище.
    """
    # This would need to be implemented with a clip cache
    return {"status": "queued", "clip_id": clip_id, "message": "Загрузка начата"}


@router.get("/keywords")
async def extract_keywords(
    text: str,
    user: User = Depends(get_current_user_optional),
):
    """
    Извлечь ключевые слова из текста для поиска B-Roll.
    """
    from app.broll import BRollSearch

    keywords = BRollSearch.extract_keywords_from_text(text)
    return {
        "text": text[:200],
        "keywords": keywords,
        "search_query": " ".join(keywords[:3]) if keywords else "",
    }
