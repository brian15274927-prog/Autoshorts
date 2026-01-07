"""
SQLite YouTube Shorts Jobs Repository.
Persists YouTube analysis and clip generation jobs to survive restarts.
"""
import json
import logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from .database import get_connection

logger = logging.getLogger(__name__)


@dataclass
class YouTubeJobRecord:
    """Complete YouTube analysis job record for persistence."""
    job_id: str
    user_id: str
    youtube_url: str
    status: str
    progress: float
    progress_message: str
    created_at: str
    completed_at: Optional[str] = None

    # Analysis settings
    max_clips: int = 5
    min_duration: float = 15.0
    max_duration: float = 45.0
    goal: str = "viral"  # viral, educational, podcast, dramatic, funny
    output_format: str = "9:16"
    output_width: int = 1080
    output_height: int = 1920
    enable_broll: bool = False
    broll_source: str = "pexels"

    # Analysis results (JSON)
    video_duration: Optional[float] = None
    video_path: Optional[str] = None
    transcript_json: Optional[str] = None
    clips_json: Optional[str] = None
    format_settings_json: Optional[str] = None

    # Error info
    error: Optional[str] = None


@dataclass
class YouTubeClipRecord:
    """Individual YouTube clip record."""
    id: int
    job_id: str
    clip_id: str
    clip_index: int
    start: float
    end: float
    duration: float
    text_preview: str
    score: float
    ai_reasoning: str
    words_json: Optional[str] = None
    clip_video_path: Optional[str] = None
    clip_video_url: Optional[str] = None
    status: str = "pending"  # pending, created, failed
    created_at: Optional[str] = None


def init_youtube_jobs_schema(conn) -> None:
    """Initialize youtube_jobs and youtube_clips tables."""
    conn.executescript("""
        -- YouTube analysis jobs table
        CREATE TABLE IF NOT EXISTS youtube_jobs (
            job_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            youtube_url TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            progress REAL NOT NULL DEFAULT 0,
            progress_message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT,

            -- Analysis settings
            max_clips INTEGER DEFAULT 5,
            min_duration REAL DEFAULT 15.0,
            max_duration REAL DEFAULT 45.0,
            goal TEXT DEFAULT 'viral',
            output_format TEXT DEFAULT '9:16',
            output_width INTEGER DEFAULT 1080,
            output_height INTEGER DEFAULT 1920,
            enable_broll INTEGER DEFAULT 0,
            broll_source TEXT DEFAULT 'pexels',

            -- Analysis results
            video_duration REAL,
            video_path TEXT,
            transcript_json TEXT,
            clips_json TEXT,
            format_settings_json TEXT,

            -- Error info
            error TEXT
        );

        -- Indexes for efficient queries
        CREATE INDEX IF NOT EXISTS idx_youtube_jobs_user_id
            ON youtube_jobs(user_id);
        CREATE INDEX IF NOT EXISTS idx_youtube_jobs_status
            ON youtube_jobs(status);
        CREATE INDEX IF NOT EXISTS idx_youtube_jobs_created_at
            ON youtube_jobs(created_at DESC);

        -- YouTube clips table for individual clips
        CREATE TABLE IF NOT EXISTS youtube_clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            clip_id TEXT NOT NULL UNIQUE,
            clip_index INTEGER NOT NULL,
            start REAL NOT NULL,
            end_time REAL NOT NULL,
            duration REAL NOT NULL,
            text_preview TEXT,
            score REAL DEFAULT 0,
            ai_reasoning TEXT,
            words_json TEXT,
            clip_video_path TEXT,
            clip_video_url TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (job_id) REFERENCES youtube_jobs(job_id) ON DELETE CASCADE
        );

        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_youtube_clips_job_id
            ON youtube_clips(job_id);
        CREATE INDEX IF NOT EXISTS idx_youtube_clips_clip_id
            ON youtube_clips(clip_id);
    """)
    logger.info("YouTube jobs schema initialized")


class YouTubeJobsRepository:
    """
    SQLite repository for YouTube shorts analysis jobs.
    Provides full CRUD operations for job persistence.
    """

    def __init__(self):
        # Ensure schema exists
        conn = get_connection()
        init_youtube_jobs_schema(conn)

    def create_job(
        self,
        job_id: str,
        user_id: str,
        youtube_url: str,
        max_clips: int = 5,
        min_duration: float = 15.0,
        max_duration: float = 45.0,
        goal: str = "viral",
        output_format: str = "9:16",
        output_width: int = 1080,
        output_height: int = 1920,
        enable_broll: bool = False,
        broll_source: str = "pexels"
    ) -> YouTubeJobRecord:
        """Create a new YouTube analysis job record."""
        conn = get_connection()
        now = datetime.utcnow().isoformat()

        conn.execute("""
            INSERT INTO youtube_jobs (
                job_id, user_id, youtube_url, status, progress, progress_message,
                created_at, max_clips, min_duration, max_duration, goal,
                output_format, output_width, output_height, enable_broll, broll_source
            ) VALUES (?, ?, ?, 'pending', 0, 'Initializing...', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id, user_id, youtube_url, now, max_clips, min_duration, max_duration,
            goal, output_format, output_width, output_height, int(enable_broll), broll_source
        ))

        logger.info(f"Created YouTube job: {job_id} for URL {youtube_url}")
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Optional[YouTubeJobRecord]:
        """Get a job by ID."""
        conn = get_connection()
        cursor = conn.execute(
            "SELECT * FROM youtube_jobs WHERE job_id = ?",
            (job_id,)
        )
        row = cursor.fetchone()
        return self._row_to_record(row) if row else None

    def update_job_status(
        self,
        job_id: str,
        status: str,
        progress: float,
        progress_message: str
    ) -> bool:
        """Update job status and progress."""
        conn = get_connection()
        cursor = conn.execute("""
            UPDATE youtube_jobs
            SET status = ?, progress = ?, progress_message = ?
            WHERE job_id = ?
        """, (status, progress, progress_message, job_id))
        return cursor.rowcount > 0

    def update_job_processing(
        self,
        job_id: str,
        progress_message: str
    ) -> bool:
        """Update job with processing status."""
        conn = get_connection()
        cursor = conn.execute("""
            UPDATE youtube_jobs
            SET status = 'processing', progress_message = ?
            WHERE job_id = ?
        """, (progress_message, job_id))
        return cursor.rowcount > 0

    def complete_job(
        self,
        job_id: str,
        video_duration: float,
        video_path: str,
        clips: List[Dict[str, Any]],
        format_settings: Dict[str, Any] = None
    ) -> bool:
        """Mark job as completed with analysis results."""
        conn = get_connection()
        now = datetime.utcnow().isoformat()

        clips_json = json.dumps(clips, ensure_ascii=False)
        format_settings_json = json.dumps(format_settings or {}, ensure_ascii=False)

        cursor = conn.execute("""
            UPDATE youtube_jobs
            SET status = 'completed',
                progress = 100,
                progress_message = 'Analysis complete',
                completed_at = ?,
                video_duration = ?,
                video_path = ?,
                clips_json = ?,
                format_settings_json = ?
            WHERE job_id = ?
        """, (now, video_duration, video_path, clips_json, format_settings_json, job_id))

        # Save clips to youtube_clips table
        if clips:
            self._save_clips(job_id, clips)

        logger.info(f"Completed YouTube job: {job_id} with {len(clips)} clips")
        return cursor.rowcount > 0

    def fail_job(self, job_id: str, error: str) -> bool:
        """Mark job as failed with error message."""
        conn = get_connection()
        cursor = conn.execute("""
            UPDATE youtube_jobs
            SET status = 'failed',
                error = ?,
                progress_message = ?
            WHERE job_id = ?
        """, (error, f"Error: {error[:100]}", job_id))
        logger.error(f"Failed YouTube job: {job_id} - {error}")
        return cursor.rowcount > 0

    def get_user_jobs(
        self,
        user_id: str,
        limit: int = 50
    ) -> List[YouTubeJobRecord]:
        """Get jobs for a specific user."""
        conn = get_connection()
        cursor = conn.execute("""
            SELECT * FROM youtube_jobs
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit))
        rows = cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_all_jobs(self, limit: int = 100) -> List[YouTubeJobRecord]:
        """Get all recent jobs (admin use)."""
        conn = get_connection()
        cursor = conn.execute("""
            SELECT * FROM youtube_jobs
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def delete_job(self, job_id: str) -> bool:
        """Delete a job record."""
        conn = get_connection()
        # Clips will be deleted by CASCADE
        cursor = conn.execute(
            "DELETE FROM youtube_jobs WHERE job_id = ?",
            (job_id,)
        )
        return cursor.rowcount > 0

    def _row_to_record(self, row) -> YouTubeJobRecord:
        """Convert database row to YouTubeJobRecord."""
        return YouTubeJobRecord(
            job_id=row["job_id"],
            user_id=row["user_id"],
            youtube_url=row["youtube_url"],
            status=row["status"],
            progress=row["progress"],
            progress_message=row["progress_message"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            max_clips=row["max_clips"],
            min_duration=row["min_duration"],
            max_duration=row["max_duration"],
            goal=row["goal"],
            output_format=row["output_format"],
            output_width=row["output_width"],
            output_height=row["output_height"],
            enable_broll=bool(row["enable_broll"]),
            broll_source=row["broll_source"],
            video_duration=row["video_duration"],
            video_path=row["video_path"],
            transcript_json=row["transcript_json"],
            clips_json=row["clips_json"],
            format_settings_json=row["format_settings_json"],
            error=row["error"]
        )

    # ═══════════════════════════════════════════════════════════════
    # CLIPS METHODS
    # ═══════════════════════════════════════════════════════════════

    def _save_clips(self, job_id: str, clips: List[Dict[str, Any]]) -> bool:
        """Save all clips for a job."""
        conn = get_connection()

        # Delete existing clips for this job (in case of re-analysis)
        conn.execute("DELETE FROM youtube_clips WHERE job_id = ?", (job_id,))

        for idx, clip in enumerate(clips):
            words_json = json.dumps(clip.get("words", []), ensure_ascii=False) if clip.get("words") else None

            conn.execute("""
                INSERT INTO youtube_clips (
                    job_id, clip_id, clip_index, start, end_time, duration,
                    text_preview, score, ai_reasoning, words_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """, (
                job_id,
                clip.get("clip_id", f"{job_id}_{idx}"),
                idx,
                clip.get("start", 0),
                clip.get("end", 0),
                clip.get("duration", 0),
                clip.get("text_preview", ""),
                clip.get("score", 0),
                clip.get("ai_reasoning", ""),
                words_json
            ))

        logger.info(f"Saved {len(clips)} clips for job {job_id}")
        return True

    def get_clips(self, job_id: str) -> List[YouTubeClipRecord]:
        """Get all clips for a job."""
        conn = get_connection()
        cursor = conn.execute("""
            SELECT * FROM youtube_clips
            WHERE job_id = ?
            ORDER BY clip_index ASC
        """, (job_id,))
        rows = cursor.fetchall()
        return [self._row_to_clip_record(row) for row in rows]

    def get_clip(self, clip_id: str) -> Optional[YouTubeClipRecord]:
        """Get a specific clip by clip_id."""
        conn = get_connection()
        cursor = conn.execute("""
            SELECT * FROM youtube_clips WHERE clip_id = ?
        """, (clip_id,))
        row = cursor.fetchone()
        return self._row_to_clip_record(row) if row else None

    def update_clip_status(
        self,
        clip_id: str,
        status: str,
        clip_video_path: str = None,
        clip_video_url: str = None
    ) -> bool:
        """Update clip status and video path."""
        conn = get_connection()

        if clip_video_path:
            cursor = conn.execute("""
                UPDATE youtube_clips
                SET status = ?, clip_video_path = ?, clip_video_url = ?
                WHERE clip_id = ?
            """, (status, clip_video_path, clip_video_url, clip_id))
        else:
            cursor = conn.execute("""
                UPDATE youtube_clips
                SET status = ?
                WHERE clip_id = ?
            """, (status, clip_id))

        return cursor.rowcount > 0

    def _row_to_clip_record(self, row) -> YouTubeClipRecord:
        """Convert database row to YouTubeClipRecord."""
        return YouTubeClipRecord(
            id=row["id"],
            job_id=row["job_id"],
            clip_id=row["clip_id"],
            clip_index=row["clip_index"],
            start=row["start"],
            end=row["end_time"],
            duration=row["duration"],
            text_preview=row["text_preview"],
            score=row["score"],
            ai_reasoning=row["ai_reasoning"] or "",
            words_json=row["words_json"],
            clip_video_path=row["clip_video_path"],
            clip_video_url=row["clip_video_url"],
            status=row["status"],
            created_at=row["created_at"]
        )

    # ═══════════════════════════════════════════════════════════════
    # API RESPONSE METHODS
    # ═══════════════════════════════════════════════════════════════

    def get_job_status_response(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job status in API response format."""
        job = self.get_job(job_id)
        if not job:
            return None

        response = {
            "job_id": job.job_id,
            "status": job.status,
            "progress": job.progress_message
        }

        if job.status == "completed":
            # Parse clips from JSON
            clips = []
            if job.clips_json:
                try:
                    clips = json.loads(job.clips_json)
                except json.JSONDecodeError:
                    pass

            # Parse format settings
            format_settings = {}
            if job.format_settings_json:
                try:
                    format_settings = json.loads(job.format_settings_json)
                except json.JSONDecodeError:
                    pass

            response["result"] = {
                "job_id": job.job_id,
                "youtube_url": job.youtube_url,
                "video_duration": job.video_duration,
                "video_path": job.video_path,
                "clips": clips,
                "format_settings": format_settings
            }

        elif job.status == "failed":
            response["error"] = job.error

        return response

    def get_analysis_result(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get full analysis result for a completed job."""
        job = self.get_job(job_id)
        if not job or job.status != "completed":
            return None

        # Parse clips from JSON
        clips = []
        if job.clips_json:
            try:
                clips = json.loads(job.clips_json)
            except json.JSONDecodeError:
                pass

        # Parse format settings
        format_settings = {}
        if job.format_settings_json:
            try:
                format_settings = json.loads(job.format_settings_json)
            except json.JSONDecodeError:
                pass

        return {
            "job_id": job.job_id,
            "youtube_url": job.youtube_url,
            "video_duration": job.video_duration,
            "video_path": job.video_path,
            "clips": clips,
            "format_settings": format_settings
        }

    def to_api_response(self, record: YouTubeJobRecord) -> Dict[str, Any]:
        """Convert record to API response format."""
        clips = []
        if record.clips_json:
            try:
                clips = json.loads(record.clips_json)
            except json.JSONDecodeError:
                pass

        return {
            "job_id": record.job_id,
            "youtube_url": record.youtube_url,
            "status": record.status,
            "progress": record.progress,
            "progress_message": record.progress_message,
            "created_at": record.created_at,
            "completed_at": record.completed_at,
            "video_duration": record.video_duration,
            "clip_count": len(clips),
            "error": record.error,
            "settings": {
                "max_clips": record.max_clips,
                "min_duration": record.min_duration,
                "max_duration": record.max_duration,
                "goal": record.goal,
                "output_format": record.output_format,
            }
        }


# Global repository instance
_youtube_jobs_repo: Optional[YouTubeJobsRepository] = None


def get_youtube_jobs_repository() -> YouTubeJobsRepository:
    """Get or create the YouTube jobs repository singleton."""
    global _youtube_jobs_repo
    if _youtube_jobs_repo is None:
        _youtube_jobs_repo = YouTubeJobsRepository()
    return _youtube_jobs_repo
