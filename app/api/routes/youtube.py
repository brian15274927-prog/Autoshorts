"""
YouTube Processing API Routes with AI Analyzer.
"""
import uuid
import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends, BackgroundTasks
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user_optional
from app.auth.models import User
from app.persistence.clips_repo import get_clips_repository, ClipRecord, Subtitle

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/youtube", tags=["YouTube"])


class YouTubeProcessRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL")
    min_duration: float = Field(default=5.0, ge=3.0, le=30.0)
    max_duration: float = Field(default=60.0, ge=10.0, le=120.0)
    language: Optional[str] = None
    whisper_model: str = "base"
    enable_broll: bool = Field(default=False, description="Включить автоматический подбор B-Roll")
    broll_orientation: str = Field(default="portrait", description="Ориентация B-Roll видео")


class YouTubeJobResponse(BaseModel):
    job_id: str
    status: str
    message: str


class ClipInfo(BaseModel):
    clip_id: str
    start: float
    end: float
    duration: float
    text: str
    score: float
    hook_phrase: Optional[str] = None


class BRollInfo(BaseModel):
    clip_id: str
    preview_url: str
    source: str
    duration: float


class YouTubeProcessResult(BaseModel):
    job_id: str
    status: str
    progress: float = 0.0
    stage: str = ""
    video_id: Optional[str] = None
    title: Optional[str] = None
    channel: Optional[str] = None
    duration: Optional[float] = None
    clips: List[ClipInfo] = []
    batch_id: Optional[str] = None
    editor_url: Optional[str] = None
    broll_clips: List[BRollInfo] = []
    broll_coverage: float = 0.0
    error: Optional[str] = None


_youtube_jobs = {}


def process_youtube_with_ai(job_id, url, min_duration, max_duration, language, whisper_model, enable_broll=False, broll_orientation="portrait"):
    global _youtube_jobs
    import asyncio

    def update_progress(stage, progress):
        _youtube_jobs[job_id]["stage"] = stage
        _youtube_jobs[job_id]["progress"] = progress
        msgs = {"init": "Инициализация...", "speech_map": "Анализ речи...",
                "emotion_scan": "Анализ эмоций...", "semantic_check": "Семантика...",
                "decision": "Выбор клипов...", "broll": "Подбор B-Roll...", "complete": "Готово"}
        _youtube_jobs[job_id]["message"] = msgs.get(stage, stage)

    try:
        _youtube_jobs[job_id]["status"] = "downloading"
        _youtube_jobs[job_id]["message"] = "Загрузка..."

        from app.youtube import download_youtube_video
        video_info = download_youtube_video(url)

        _youtube_jobs[job_id]["video_id"] = video_info.video_id
        _youtube_jobs[job_id]["title"] = video_info.title
        _youtube_jobs[job_id]["channel"] = video_info.channel
        _youtube_jobs[job_id]["duration"] = video_info.duration

        _youtube_jobs[job_id]["status"] = "analyzing"
        _youtube_jobs[job_id]["message"] = "AI-анализ..."

        from app.analyzer import AudioAnalyzer
        analyzer = AudioAnalyzer(whisper_model=whisper_model, language=language,
                                  min_clip_duration=min_duration, max_clip_duration=max_duration)
        result = analyzer.analyze(video_info.audio_path, progress_callback=update_progress)

        clips_info = [ClipInfo(clip_id=c.clip_id, start=c.start, end=c.end,
                               duration=c.duration, text=c.text[:200] if c.text else "",
                               score=c.score, hook_phrase=c.hook_phrase).model_dump()
                      for c in result.clips]
        _youtube_jobs[job_id]["clips"] = clips_info

        batch_id = f"yt_{video_info.video_id}_{uuid.uuid4().hex[:8]}"
        repo = get_clips_repository()

        # Process B-Roll if enabled
        broll_clips = []
        broll_coverage = 0.0
        if enable_broll:
            try:
                update_progress("broll", 0.8)
                from app.broll import BRollEngine

                # Build subtitles for B-Roll matching
                all_subtitles = []
                for clip in result.clips:
                    words = (clip.text or "").split()
                    wd = clip.duration / max(len(words), 1)
                    for j in range(0, len(words), 5):
                        chunk = words[j:j+5]
                        all_subtitles.append({
                            "text": " ".join(chunk),
                            "start": clip.start + j * wd,
                            "end": clip.start + (j + len(chunk)) * wd,
                        })

                engine = BRollEngine()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    composition = loop.run_until_complete(
                        engine.process_transcript(all_subtitles, min_segment_duration=2.0)
                    )
                    broll_coverage = composition.coverage
                    broll_clips = [
                        BRollInfo(
                            clip_id=c.id,
                            preview_url=c.preview_url,
                            source=c.source,
                            duration=c.duration,
                        ).model_dump()
                        for c in composition.clips
                    ]
                finally:
                    loop.close()

                _youtube_jobs[job_id]["broll_clips"] = broll_clips
                _youtube_jobs[job_id]["broll_coverage"] = broll_coverage
                logger.info(f"B-Roll: found {len(broll_clips)} clips, coverage {broll_coverage:.1%}")

            except Exception as broll_error:
                logger.warning(f"B-Roll processing failed: {broll_error}")
                # Don't fail the whole job, just skip B-Roll

        for i, clip in enumerate(result.clips):
            clip_id = f"{batch_id}_clip_{i:02d}"
            subtitles = []
            words = (clip.text or "").split()
            for j in range(0, len(words), 5):
                chunk = words[j:j+5]
                wd = clip.duration / max(len(words), 1)
                subtitles.append(Subtitle(id=f"{clip_id}_sub_{len(subtitles)}",
                                          start=clip.start + j*wd,
                                          end=clip.start + (j+len(chunk))*wd,
                                          text=" ".join(chunk)))
            repo.create_clip(ClipRecord(clip_id=clip_id, batch_id=batch_id, clip_index=i,
                                        duration=clip.duration, video_url=video_info.video_path,
                                        subtitles=subtitles, status="ready"))

        _youtube_jobs[job_id]["batch_id"] = batch_id
        _youtube_jobs[job_id]["editor_url"] = f"/app/editor/{batch_id}"
        _youtube_jobs[job_id]["status"] = "completed"
        _youtube_jobs[job_id]["progress"] = 1.0

        msg = f"Найдено {len(result.clips)} клипов"
        if enable_broll and broll_clips:
            msg += f" + {len(broll_clips)} B-Roll"
        _youtube_jobs[job_id]["message"] = msg

    except Exception as e:
        logger.exception(f"AI failed: {job_id}")
        _youtube_jobs[job_id]["status"] = "failed"
        _youtube_jobs[job_id]["error"] = str(e)
        _youtube_jobs[job_id]["message"] = f"Ошибка: {e}"


@router.post("/process", response_model=YouTubeJobResponse)
async def process_youtube_url(request: YouTubeProcessRequest, background_tasks: BackgroundTasks,
                              user: User = Depends(get_current_user_optional)):
    from app.youtube.downloader import extract_video_id
    if not extract_video_id(request.url):
        raise HTTPException(status_code=400, detail={"error": "Неверная ссылка"})

    job_id = f"ytjob_{uuid.uuid4().hex[:12]}"
    _youtube_jobs[job_id] = {"job_id": job_id, "status": "pending", "stage": "", "progress": 0,
                            "message": "В очереди...", "url": request.url, "video_id": None,
                            "title": None, "channel": None, "duration": None, "clips": [],
                            "batch_id": None, "editor_url": None, "broll_clips": [],
                            "broll_coverage": 0.0, "error": None}

    background_tasks.add_task(process_youtube_with_ai, job_id, request.url, request.min_duration,
                              request.max_duration, request.language, request.whisper_model,
                              request.enable_broll, request.broll_orientation)
    msg = "AI-анализ начат"
    if request.enable_broll:
        msg += " (с B-Roll)"
    return YouTubeJobResponse(job_id=job_id, status="pending", message=msg)


@router.get("/jobs/{job_id}", response_model=YouTubeProcessResult)
async def get_job_status(job_id: str, user: User = Depends(get_current_user_optional)):
    if job_id not in _youtube_jobs:
        raise HTTPException(status_code=404, detail={"error": "Не найдено"})
    j = _youtube_jobs[job_id]
    return YouTubeProcessResult(
        job_id=j["job_id"],
        status=j["status"],
        progress=j.get("progress", 0),
        stage=j.get("stage", ""),
        video_id=j.get("video_id"),
        title=j.get("title"),
        channel=j.get("channel"),
        duration=j.get("duration"),
        clips=[ClipInfo(**c) for c in j.get("clips", [])],
        batch_id=j.get("batch_id"),
        editor_url=j.get("editor_url"),
        broll_clips=[BRollInfo(**b) for b in j.get("broll_clips", [])],
        broll_coverage=j.get("broll_coverage", 0.0),
        error=j.get("error"),
    )


@router.post("/analyze")
async def analyze_sync(request: YouTubeProcessRequest, user: User = Depends(get_current_user_optional)):
    from app.youtube.downloader import extract_video_id
    if not extract_video_id(request.url):
        raise HTTPException(status_code=400, detail={"error": "Неверная ссылка"})

    from app.youtube import download_youtube_video
    video_info = download_youtube_video(request.url)

    from app.analyzer import AudioAnalyzer
    analyzer = AudioAnalyzer(whisper_model=request.whisper_model, language=request.language,
                              min_clip_duration=request.min_duration, max_clip_duration=request.max_duration)
    result = analyzer.analyze(video_info.audio_path)

    batch_id = f"yt_{video_info.video_id}_{uuid.uuid4().hex[:8]}"
    repo = get_clips_repository()

    for i, clip in enumerate(result.clips):
        clip_id = f"{batch_id}_clip_{i:02d}"
        subtitles = []
        words = (clip.text or "").split()
        for j in range(0, len(words), 5):
            chunk = words[j:j+5]
            wd = clip.duration / max(len(words), 1)
            subtitles.append(Subtitle(id=f"{clip_id}_sub_{len(subtitles)}",
                                      start=clip.start + j*wd, end=clip.start + (j+len(chunk))*wd,
                                      text=" ".join(chunk)))
        repo.create_clip(ClipRecord(clip_id=clip_id, batch_id=batch_id, clip_index=i,
                                    duration=clip.duration, video_url=video_info.video_path,
                                    subtitles=subtitles, status="ready"))

    return {"status": "completed", "video_id": video_info.video_id, "title": video_info.title,
            "clips_count": len(result.clips), "processing_time": result.processing_time,
            "batch_id": batch_id, "editor_url": f"/app/editor/{batch_id}",
            "clips": [c.to_dict() for c in result.clips]}
