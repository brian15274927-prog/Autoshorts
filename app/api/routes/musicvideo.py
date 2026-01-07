"""
Music Video Generator API Routes.

Endpoints for creating AI-generated music videos from uploaded audio.
"""

import os
import uuid
import shutil
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends, Query
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

from app.auth.dependencies import get_current_user_optional
from app.auth.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/musicvideo", tags=["musicvideo"])

# Directories
MUSICVIDEO_DIR = Path(r"C:\dake\data\musicvideo")
UPLOAD_DIR = MUSICVIDEO_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job storage (will be replaced with DB)
active_jobs = {}


class MusicVideoJob(BaseModel):
    """Job data model."""
    job_id: str
    user_id: Optional[str] = None
    audio_name: str
    art_style: str
    image_provider: str
    status: str = "queued"
    progress: int = 0
    output_path: Optional[str] = None
    thumbnail: Optional[str] = None
    error: Optional[str] = None
    created_at: str = ""


def get_style_theme(art_style: str) -> str:
    """Generate a theme based on art style."""
    style_themes = {
        "photorealism": "Cinematic, dramatic lighting, professional photography, epic scenes",
        "anime": "Anime style, vibrant colors, dynamic poses, Japanese animation aesthetic",
        "watercolor": "Soft watercolor painting, flowing colors, artistic brushstrokes",
        "expressionism": "Abstract expressionism, bold colors, emotional intensity, artistic",
        "ghibli": "Studio Ghibli inspired, magical, whimsical, beautiful nature scenes",
        "comic": "Comic book style, bold outlines, dynamic action, vibrant panels",
        "pixel": "Pixel art, retro gaming aesthetic, 8-bit style, nostalgic",
        "creepy": "Dark and moody, gothic atmosphere, mysterious shadows, dramatic"
    }
    return style_themes.get(art_style, "Artistic, visually stunning, creative imagery")


@router.post("/generate")
async def generate_music_video(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    art_style: str = Form("photorealism"),
    image_provider: str = Form("dalle"),
    user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Generate a music video from uploaded audio.

    Theme is auto-generated based on the selected art style.
    """
    # Validate file type
    allowed_types = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac'}
    file_ext = Path(audio.filename).suffix.lower()

    if file_ext not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format: {file_ext}. Allowed: {', '.join(allowed_types)}"
        )

    # Generate job ID
    job_id = str(uuid.uuid4())
    user_id = user.user_id if user else None

    # Save uploaded audio
    audio_path = UPLOAD_DIR / f"{job_id}{file_ext}"
    try:
        with open(audio_path, "wb") as f:
            content = await audio.read()
            f.write(content)
        logger.info(f"[MUSICVIDEO] Audio saved: {audio_path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save audio: {e}")

    # Auto-generate theme from style
    theme = get_style_theme(art_style)

    # Initialize job
    job = MusicVideoJob(
        job_id=job_id,
        user_id=user_id,
        audio_name=audio.filename,
        art_style=art_style,
        image_provider=image_provider,
        status="queued",
        progress=0,
        created_at=datetime.utcnow().isoformat()
    )
    active_jobs[job_id] = job.dict()

    # Save to persistence
    _save_job_to_db(job)

    # Start background generation
    background_tasks.add_task(
        _run_generation,
        job_id=job_id,
        audio_path=str(audio_path),
        theme=theme,
        art_style=art_style,
        image_provider=image_provider,
        user_id=user_id
    )

    return JSONResponse({
        "job_id": job_id,
        "status": "queued",
        "message": "Music video generation started"
    })


def _save_job_to_db(job: MusicVideoJob):
    """Save job to SQLite database."""
    try:
        import sqlite3
        db_path = Path(r"C:\dake\data\musicvideo.db")
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Create table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS musicvideo_jobs (
                job_id TEXT PRIMARY KEY,
                user_id TEXT,
                audio_name TEXT,
                art_style TEXT,
                image_provider TEXT,
                status TEXT,
                progress INTEGER,
                output_path TEXT,
                thumbnail TEXT,
                error TEXT,
                created_at TEXT
            )
        """)

        # Insert or update
        cursor.execute("""
            INSERT OR REPLACE INTO musicvideo_jobs
            (job_id, user_id, audio_name, art_style, image_provider, status, progress, output_path, thumbnail, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job.job_id, job.user_id, job.audio_name, job.art_style, job.image_provider,
            job.status, job.progress, job.output_path, job.thumbnail, job.error, job.created_at
        ))

        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[MUSICVIDEO] DB save error: {e}")


def _update_job_in_db(job_id: str, updates: dict):
    """Update job in database."""
    try:
        import sqlite3
        db_path = Path(r"C:\dake\data\musicvideo.db")
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [job_id]

        cursor.execute(f"UPDATE musicvideo_jobs SET {set_clause} WHERE job_id = ?", values)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[MUSICVIDEO] DB update error: {e}")


def _get_jobs_from_db(user_id: Optional[str] = None, limit: int = 20) -> List[dict]:
    """Get recent jobs from database."""
    try:
        import sqlite3
        db_path = Path(r"C:\dake\data\musicvideo.db")
        if not db_path.exists():
            return []

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if user_id:
            cursor.execute(
                "SELECT * FROM musicvideo_jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            )
        else:
            cursor.execute(
                "SELECT * FROM musicvideo_jobs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"[MUSICVIDEO] DB read error: {e}")
        return []


async def _run_generation(
    job_id: str,
    audio_path: str,
    theme: str,
    art_style: str,
    image_provider: str,
    user_id: Optional[str] = None
):
    """Background task for music video generation."""
    from app.services.musicvideo_service import MusicVideoService

    def progress_callback(progress: int, status: str = None):
        if job_id in active_jobs:
            active_jobs[job_id]["progress"] = progress
            if status:
                active_jobs[job_id]["status"] = status
            _update_job_in_db(job_id, {"progress": progress, "status": status or active_jobs[job_id]["status"]})

    try:
        service = MusicVideoService()

        result = await service.generate_music_video(
            audio_path=audio_path,
            theme=theme,
            lyrics=None,
            art_style=art_style,
            language="en",
            image_provider=image_provider,
            progress_callback=progress_callback
        )

        await service.close()

        if result.status == "completed" and result.output_path:
            # Generate thumbnail from first frame
            thumbnail = None
            try:
                thumbnail = _generate_thumbnail(result.output_path, job_id)
            except:
                pass

            updates = {
                "status": "completed",
                "progress": 100,
                "output_path": result.output_path,
                "thumbnail": thumbnail
            }
            active_jobs[job_id].update(updates)
            _update_job_in_db(job_id, updates)
        else:
            updates = {
                "status": "failed",
                "error": result.error or "Unknown error"
            }
            active_jobs[job_id].update(updates)
            _update_job_in_db(job_id, updates)

    except Exception as e:
        logger.error(f"[MUSICVIDEO] Generation failed: {e}")
        updates = {"status": "failed", "error": str(e)}
        active_jobs[job_id].update(updates)
        _update_job_in_db(job_id, updates)


def _generate_thumbnail(video_path: str, job_id: str) -> Optional[str]:
    """Generate thumbnail from video."""
    import subprocess

    thumbnail_path = MUSICVIDEO_DIR / f"{job_id}_thumb.jpg"
    ffmpeg_path = r"C:\dake\tools\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe"

    if not os.path.exists(ffmpeg_path):
        ffmpeg_path = "ffmpeg"

    try:
        subprocess.run([
            ffmpeg_path, "-y", "-i", video_path,
            "-ss", "00:00:01", "-vframes", "1",
            "-vf", "scale=120:-1",
            str(thumbnail_path)
        ], capture_output=True, timeout=30)

        if thumbnail_path.exists():
            return f"/musicvideo_files/{job_id}_thumb.jpg"
    except:
        pass

    return None


@router.get("/status/{job_id}")
async def get_status(job_id: str):
    """Get the status of a music video generation job."""
    # Check in-memory first
    if job_id in active_jobs:
        job = active_jobs[job_id]
        return JSONResponse({
            "job_id": job_id,
            "status": job["status"],
            "progress": job["progress"],
            "output_url": f"/api/musicvideo/download/{job_id}" if job.get("output_path") else None,
            "error": job.get("error")
        })

    # Check database
    jobs = _get_jobs_from_db(limit=1000)
    for job in jobs:
        if job["job_id"] == job_id:
            return JSONResponse({
                "job_id": job_id,
                "status": job["status"],
                "progress": job["progress"],
                "output_url": f"/api/musicvideo/download/{job_id}" if job.get("output_path") else None,
                "error": job.get("error")
            })

    raise HTTPException(status_code=404, detail="Job not found")


@router.get("/recent")
async def get_recent_videos(
    limit: int = Query(20, ge=1, le=100),
    user: Optional[User] = Depends(get_current_user_optional)
):
    """Get recent music videos for the current user."""
    user_id = user.user_id if user else None
    jobs = _get_jobs_from_db(user_id=user_id, limit=limit)
    return jobs


@router.get("/download/{job_id}")
async def download_video(job_id: str):
    """Download the generated music video."""
    output_path = None

    # Check in-memory
    if job_id in active_jobs:
        job = active_jobs[job_id]
        if job["status"] != "completed":
            raise HTTPException(status_code=400, detail="Video not ready yet")
        output_path = job.get("output_path")

    # Check database
    if not output_path:
        jobs = _get_jobs_from_db(limit=1000)
        for job in jobs:
            if job["job_id"] == job_id:
                if job["status"] != "completed":
                    raise HTTPException(status_code=400, detail="Video not ready yet")
                output_path = job.get("output_path")
                break

    if not output_path or not os.path.exists(output_path):
        raise HTTPException(status_code=404, detail="Video file not found")

    return FileResponse(
        path=output_path,
        media_type="video/mp4",
        filename=f"music_video_{job_id[:8]}.mp4"
    )


@router.get("/stream/{job_id}")
async def stream_video(job_id: str):
    """Stream the generated music video for preview."""
    output_path = None

    # Check in-memory
    if job_id in active_jobs:
        job = active_jobs[job_id]
        if job["status"] != "completed":
            raise HTTPException(status_code=400, detail="Video not ready yet")
        output_path = job.get("output_path")

    # Check database
    if not output_path:
        jobs = _get_jobs_from_db(limit=1000)
        for job in jobs:
            if job["job_id"] == job_id:
                if job["status"] != "completed":
                    raise HTTPException(status_code=400, detail="Video not ready yet")
                output_path = job.get("output_path")
                break

    if not output_path or not os.path.exists(output_path):
        raise HTTPException(status_code=404, detail="Video file not found")

    return FileResponse(
        path=output_path,
        media_type="video/mp4",
        headers={"Accept-Ranges": "bytes"}
    )


@router.delete("/job/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and its files."""
    # Remove from memory
    if job_id in active_jobs:
        job = active_jobs[job_id]
        if job.get("output_path") and os.path.exists(job["output_path"]):
            os.remove(job["output_path"])
        del active_jobs[job_id]

    # Remove from database
    try:
        import sqlite3
        db_path = Path(r"C:\dake\data\musicvideo.db")
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Get output path before delete
            cursor.execute("SELECT output_path, thumbnail FROM musicvideo_jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                if row[0] and os.path.exists(row[0]):
                    os.remove(row[0])
                if row[1]:
                    thumb_path = MUSICVIDEO_DIR / Path(row[1]).name
                    if thumb_path.exists():
                        thumb_path.unlink()

            cursor.execute("DELETE FROM musicvideo_jobs WHERE job_id = ?", (job_id,))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"[MUSICVIDEO] Delete error: {e}")

    # Remove uploaded audio
    for ext in ['.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac']:
        audio_file = UPLOAD_DIR / f"{job_id}{ext}"
        if audio_file.exists():
            audio_file.unlink()

    # Remove job directory
    job_dir = MUSICVIDEO_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)

    return JSONResponse({"message": "Job deleted successfully"})
