"""
SQLite Faceless Jobs Repository.
Persists faceless video generation jobs to survive restarts.
"""
import json
import logging
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any

from .database import get_connection

logger = logging.getLogger(__name__)


from enum import Enum


class PipelineCheckpoint(str, Enum):
    """
    Pipeline checkpoint stages for resume functionality.
    Each checkpoint represents a completed stage that can be skipped on resume.
    """
    NONE = "none"                      # Just created, nothing done
    SCRIPT_DONE = "script_done"        # Script generated and saved
    AUDIO_DONE = "audio_done"          # Audio generated and saved
    IMAGES_DONE = "images_done"        # All DALL-E images generated
    CLIPS_DONE = "clips_done"          # Ken Burns animation done
    RENDERED = "rendered"              # Final video rendered


@dataclass
class FacelessJobRecord:
    """Complete faceless job record for persistence."""
    job_id: str
    user_id: str
    topic: str
    status: str
    progress: float
    progress_message: str
    created_at: str
    completed_at: Optional[str] = None

    # Settings
    style: str = "viral"
    language: str = "ru"
    voice: str = "ru-RU-DmitryNeural"
    duration: int = 60
    format: str = "9:16"
    width: int = 1080
    height: int = 1920
    subtitle_style: str = "hormozi"
    art_style: str = "photorealism"

    # Generated content paths
    script_json: Optional[str] = None  # JSON serialized script
    audio_path: Optional[str] = None
    audio_duration: Optional[float] = None
    output_path: Optional[str] = None

    # Image and clip paths (JSON arrays)
    image_paths_json: Optional[str] = None
    clip_paths_json: Optional[str] = None
    visual_prompts_json: Optional[str] = None

    # Error and status details
    error: Optional[str] = None
    used_fallback_script: bool = False
    used_fallback_visuals: bool = False
    api_limit_reached: bool = False
    status_details: str = ""

    # Checkpoint for resume functionality
    checkpoint: str = "none"  # PipelineCheckpoint value


@dataclass
class VideoSegmentRecord:
    """Individual video segment for editor."""
    id: int
    job_id: str
    segment_index: int
    text: str
    duration: float
    image_path: str  # Absolute Windows path
    image_url: str   # URL for frontend
    visual_prompt: str
    emotion: str
    segment_type: str
    camera_direction: str
    lighting_mood: str


def init_faceless_jobs_schema(conn) -> None:
    """Initialize faceless_jobs and video_segments tables."""
    conn.executescript("""
        -- Faceless video generation jobs table
        CREATE TABLE IF NOT EXISTS faceless_jobs (
            job_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            progress REAL NOT NULL DEFAULT 0,
            progress_message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT,

            -- Settings
            style TEXT DEFAULT 'viral',
            language TEXT DEFAULT 'ru',
            voice TEXT DEFAULT 'ru-RU-DmitryNeural',
            duration INTEGER DEFAULT 60,
            format TEXT DEFAULT '9:16',
            width INTEGER DEFAULT 1080,
            height INTEGER DEFAULT 1920,
            subtitle_style TEXT DEFAULT 'hormozi',
            art_style TEXT DEFAULT 'photorealism',

            -- Generated content
            script_json TEXT,
            audio_path TEXT,
            audio_duration REAL,
            output_path TEXT,

            -- Arrays stored as JSON
            image_paths_json TEXT,
            clip_paths_json TEXT,
            visual_prompts_json TEXT,

            -- Status flags
            error TEXT,
            used_fallback_script INTEGER DEFAULT 0,
            used_fallback_visuals INTEGER DEFAULT 0,
            api_limit_reached INTEGER DEFAULT 0,
            status_details TEXT DEFAULT '',

            -- Checkpoint for resume functionality
            checkpoint TEXT DEFAULT 'none'
        );

        -- Indexes for efficient queries
        CREATE INDEX IF NOT EXISTS idx_faceless_jobs_user_id
            ON faceless_jobs(user_id);
        CREATE INDEX IF NOT EXISTS idx_faceless_jobs_status
            ON faceless_jobs(status);
        CREATE INDEX IF NOT EXISTS idx_faceless_jobs_created_at
            ON faceless_jobs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_faceless_jobs_user_status
            ON faceless_jobs(user_id, status);

        -- Video segments table for editor integration
        CREATE TABLE IF NOT EXISTS video_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            segment_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            duration REAL NOT NULL DEFAULT 5.0,
            image_path TEXT,
            image_url TEXT,
            visual_prompt TEXT,
            emotion TEXT DEFAULT 'neutral',
            segment_type TEXT DEFAULT 'content',
            camera_direction TEXT DEFAULT 'static',
            lighting_mood TEXT DEFAULT 'cinematic',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (job_id) REFERENCES faceless_jobs(job_id) ON DELETE CASCADE,
            UNIQUE(job_id, segment_index)
        );

        -- Index for fast segment retrieval
        CREATE INDEX IF NOT EXISTS idx_video_segments_job_id
            ON video_segments(job_id);
    """)
    logger.info("Faceless jobs and video_segments schema initialized")


class FacelessJobsRepository:
    """
    SQLite repository for faceless video generation jobs.
    Provides full CRUD operations for job persistence.
    """

    def __init__(self):
        # Ensure schema exists
        conn = get_connection()
        init_faceless_jobs_schema(conn)

    def create_job(
        self,
        job_id: str,
        user_id: str,
        topic: str,
        style: str = "viral",
        language: str = "ru",
        voice: str = "ru-RU-DmitryNeural",
        duration: int = 60,
        format: str = "9:16",
        width: int = 1080,
        height: int = 1920,
        subtitle_style: str = "hormozi",
        art_style: str = "photorealism"
    ) -> FacelessJobRecord:
        """Create a new faceless job record."""
        conn = get_connection()
        now = datetime.utcnow().isoformat()

        conn.execute("""
            INSERT INTO faceless_jobs (
                job_id, user_id, topic, status, progress, progress_message,
                created_at, style, language, voice, duration, format,
                width, height, subtitle_style, art_style
            ) VALUES (?, ?, ?, 'pending', 0, 'Initializing...', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id, user_id, topic, now, style, language, voice,
            duration, format, width, height, subtitle_style, art_style
        ))

        logger.info(f"Created faceless job: {job_id} for user {user_id}")
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Optional[FacelessJobRecord]:
        """Get a job by ID."""
        conn = get_connection()
        cursor = conn.execute(
            "SELECT * FROM faceless_jobs WHERE job_id = ?",
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
            UPDATE faceless_jobs
            SET status = ?, progress = ?, progress_message = ?
            WHERE job_id = ?
        """, (status, progress, progress_message, job_id))
        return cursor.rowcount > 0

    def update_checkpoint(self, job_id: str, checkpoint: str) -> bool:
        """
        Update job checkpoint after completing a pipeline stage.
        This enables resume functionality - on error, we can skip completed stages.
        """
        conn = get_connection()
        cursor = conn.execute("""
            UPDATE faceless_jobs
            SET checkpoint = ?
            WHERE job_id = ?
        """, (checkpoint, job_id))
        logger.info(f"[CHECKPOINT] Job {job_id} checkpoint updated to: {checkpoint}")
        return cursor.rowcount > 0

    def get_resumable_jobs(self) -> List[FacelessJobRecord]:
        """
        Get all jobs that failed but have progress that can be resumed.
        These are jobs with checkpoint != 'none' and checkpoint != 'rendered' and status = 'failed'.
        """
        conn = get_connection()
        cursor = conn.execute("""
            SELECT * FROM faceless_jobs
            WHERE status = 'failed'
              AND checkpoint NOT IN ('none', 'rendered')
            ORDER BY created_at DESC
        """)
        rows = cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def reset_job_for_resume(self, job_id: str) -> bool:
        """
        Reset a failed job's status so it can be resumed.
        Keeps the checkpoint and all generated content.
        """
        conn = get_connection()
        cursor = conn.execute("""
            UPDATE faceless_jobs
            SET status = 'pending',
                error = NULL,
                progress_message = 'Resuming from checkpoint...'
            WHERE job_id = ?
        """, (job_id,))
        logger.info(f"[RESUME] Job {job_id} reset for resume")
        return cursor.rowcount > 0

    def update_job_script(
        self,
        job_id: str,
        script: Dict[str, Any],
        used_fallback: bool = False
    ) -> bool:
        """Update job with generated script and set checkpoint."""
        conn = get_connection()
        script_json = json.dumps(script, ensure_ascii=False)
        cursor = conn.execute("""
            UPDATE faceless_jobs
            SET script_json = ?, used_fallback_script = ?, checkpoint = ?
            WHERE job_id = ?
        """, (script_json, int(used_fallback), PipelineCheckpoint.SCRIPT_DONE.value, job_id))
        logger.info(f"[CHECKPOINT] Job {job_id} script saved, checkpoint: script_done")
        return cursor.rowcount > 0

    def update_job_audio(
        self,
        job_id: str,
        audio_path: str,
        audio_duration: float
    ) -> bool:
        """Update job with generated audio and set checkpoint."""
        conn = get_connection()
        cursor = conn.execute("""
            UPDATE faceless_jobs
            SET audio_path = ?, audio_duration = ?, checkpoint = ?
            WHERE job_id = ?
        """, (audio_path, audio_duration, PipelineCheckpoint.AUDIO_DONE.value, job_id))
        logger.info(f"[CHECKPOINT] Job {job_id} audio saved, checkpoint: audio_done")
        return cursor.rowcount > 0

    def update_job_visuals(
        self,
        job_id: str,
        visual_prompts: List[str],
        image_paths: List[str],
        clip_paths: List[str] = None,
        used_fallback: bool = False,
        api_limit_reached: bool = False
    ) -> bool:
        """Update job with generated visuals and set checkpoint."""
        conn = get_connection()
        cursor = conn.execute("""
            UPDATE faceless_jobs
            SET visual_prompts_json = ?,
                image_paths_json = ?,
                clip_paths_json = ?,
                used_fallback_visuals = ?,
                api_limit_reached = ?,
                checkpoint = ?
            WHERE job_id = ?
        """, (
            json.dumps(visual_prompts, ensure_ascii=False),
            json.dumps(image_paths, ensure_ascii=False),
            json.dumps(clip_paths or [], ensure_ascii=False),
            int(used_fallback),
            int(api_limit_reached),
            PipelineCheckpoint.IMAGES_DONE.value,
            job_id
        ))
        logger.info(f"[CHECKPOINT] Job {job_id} images saved, checkpoint: images_done")
        return cursor.rowcount > 0

    def update_job_clips(self, job_id: str, clip_paths: List[str]) -> bool:
        """Update job with animated clip paths and set checkpoint."""
        conn = get_connection()
        cursor = conn.execute("""
            UPDATE faceless_jobs
            SET clip_paths_json = ?, checkpoint = ?
            WHERE job_id = ?
        """, (json.dumps(clip_paths, ensure_ascii=False), PipelineCheckpoint.CLIPS_DONE.value, job_id))
        logger.info(f"[CHECKPOINT] Job {job_id} clips saved, checkpoint: clips_done")
        return cursor.rowcount > 0

    def complete_job(
        self,
        job_id: str,
        output_path: str,
        status_details: str = ""
    ) -> bool:
        """Mark job as completed with output path and final checkpoint."""
        conn = get_connection()
        now = datetime.utcnow().isoformat()
        cursor = conn.execute("""
            UPDATE faceless_jobs
            SET status = 'completed',
                progress = 100,
                progress_message = 'Video ready!',
                completed_at = ?,
                output_path = ?,
                status_details = ?,
                checkpoint = ?
            WHERE job_id = ?
        """, (now, output_path, status_details, PipelineCheckpoint.RENDERED.value, job_id))
        logger.info(f"[CHECKPOINT] Job {job_id} completed, checkpoint: rendered")
        return cursor.rowcount > 0

    def fail_job(self, job_id: str, error: str) -> bool:
        """Mark job as failed with error message."""
        conn = get_connection()
        cursor = conn.execute("""
            UPDATE faceless_jobs
            SET status = 'failed',
                error = ?,
                progress_message = ?
            WHERE job_id = ?
        """, (error, f"Error: {error[:100]}", job_id))
        logger.error(f"Failed faceless job: {job_id} - {error}")
        return cursor.rowcount > 0

    def get_user_jobs(
        self,
        user_id: str,
        limit: int = 50,
        status_filter: Optional[str] = None
    ) -> List[FacelessJobRecord]:
        """Get jobs for a specific user."""
        conn = get_connection()

        if status_filter:
            cursor = conn.execute("""
                SELECT * FROM faceless_jobs
                WHERE user_id = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, status_filter, limit))
        else:
            cursor = conn.execute("""
                SELECT * FROM faceless_jobs
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, limit))

        rows = cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_all_jobs(self, limit: int = 100) -> List[FacelessJobRecord]:
        """Get all recent jobs (admin use)."""
        conn = get_connection()
        cursor = conn.execute("""
            SELECT * FROM faceless_jobs
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_pending_jobs(self) -> List[FacelessJobRecord]:
        """Get all pending/in-progress jobs (for recovery after restart)."""
        conn = get_connection()
        cursor = conn.execute("""
            SELECT * FROM faceless_jobs
            WHERE status NOT IN ('completed', 'failed')
            ORDER BY created_at ASC
        """)
        rows = cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def delete_job(self, job_id: str) -> bool:
        """Delete a job record."""
        conn = get_connection()
        cursor = conn.execute(
            "DELETE FROM faceless_jobs WHERE job_id = ?",
            (job_id,)
        )
        return cursor.rowcount > 0

    def count_user_jobs(self, user_id: str) -> int:
        """Count total jobs for a user."""
        conn = get_connection()
        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM faceless_jobs WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        return row["cnt"] if row else 0

    def _row_to_record(self, row) -> FacelessJobRecord:
        """Convert database row to FacelessJobRecord."""
        return FacelessJobRecord(
            job_id=row["job_id"],
            user_id=row["user_id"],
            topic=row["topic"],
            status=row["status"],
            progress=row["progress"],
            progress_message=row["progress_message"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            style=row["style"],
            language=row["language"],
            voice=row["voice"],
            duration=row["duration"],
            format=row["format"],
            width=row["width"],
            height=row["height"],
            subtitle_style=row["subtitle_style"],
            art_style=row["art_style"] if "art_style" in row.keys() else "photorealism",
            script_json=row["script_json"],
            audio_path=row["audio_path"],
            audio_duration=row["audio_duration"],
            output_path=row["output_path"],
            image_paths_json=row["image_paths_json"],
            clip_paths_json=row["clip_paths_json"],
            visual_prompts_json=row["visual_prompts_json"],
            error=row["error"],
            used_fallback_script=bool(row["used_fallback_script"]),
            used_fallback_visuals=bool(row["used_fallback_visuals"]),
            api_limit_reached=bool(row["api_limit_reached"]),
            status_details=row["status_details"] or "",
            checkpoint=row["checkpoint"] if "checkpoint" in row.keys() else "none"
        )

    # ═══════════════════════════════════════════════════════════════
    # VIDEO SEGMENTS METHODS
    # ═══════════════════════════════════════════════════════════════

    def save_segments(
        self,
        job_id: str,
        segments: List[Dict[str, Any]],
        image_paths: List[str]
    ) -> bool:
        """
        Save all video segments for a job.
        Called after generation completes to persist segment data for editor.
        """
        conn = get_connection()

        # Delete existing segments for this job (in case of re-generation)
        conn.execute("DELETE FROM video_segments WHERE job_id = ?", (job_id,))

        # Insert each segment
        for idx, segment in enumerate(segments):
            # Get image path for this segment
            image_path = image_paths[idx] if idx < len(image_paths) else ""

            # Convert Windows path to URL
            image_url = self._path_to_url(image_path, job_id)

            conn.execute("""
                INSERT INTO video_segments (
                    job_id, segment_index, text, duration, image_path, image_url,
                    visual_prompt, emotion, segment_type, camera_direction, lighting_mood
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id,
                idx,
                segment.get("text", ""),
                segment.get("duration", 5.0),
                image_path,
                image_url,
                segment.get("visual_prompt", ""),
                segment.get("emotion", "neutral"),
                segment.get("segment_type", "content"),
                segment.get("camera_direction", "static"),
                segment.get("lighting_mood", "cinematic")
            ))

        logger.info(f"Saved {len(segments)} segments for job {job_id}")
        return True

    def get_segments(self, job_id: str) -> List[VideoSegmentRecord]:
        """Get all segments for a job, ordered by segment_index."""
        conn = get_connection()
        cursor = conn.execute("""
            SELECT * FROM video_segments
            WHERE job_id = ?
            ORDER BY segment_index ASC
        """, (job_id,))
        rows = cursor.fetchall()
        return [self._row_to_segment(row) for row in rows]

    def get_segment(self, job_id: str, segment_index: int) -> Optional[VideoSegmentRecord]:
        """Get a specific segment by job_id and index."""
        conn = get_connection()
        cursor = conn.execute("""
            SELECT * FROM video_segments
            WHERE job_id = ? AND segment_index = ?
        """, (job_id, segment_index))
        row = cursor.fetchone()
        return self._row_to_segment(row) if row else None

    def update_segment(
        self,
        job_id: str,
        segment_index: int,
        text: str = None,
        duration: float = None,
        image_path: str = None,
        visual_prompt: str = None,
        emotion: str = None
    ) -> bool:
        """Update a specific segment (for editor changes)."""
        conn = get_connection()

        updates = []
        params = []

        if text is not None:
            updates.append("text = ?")
            params.append(text)
        if duration is not None:
            updates.append("duration = ?")
            params.append(duration)
        if image_path is not None:
            updates.append("image_path = ?")
            params.append(image_path)
            updates.append("image_url = ?")
            params.append(self._path_to_url(image_path, job_id))
        if visual_prompt is not None:
            updates.append("visual_prompt = ?")
            params.append(visual_prompt)
        if emotion is not None:
            updates.append("emotion = ?")
            params.append(emotion)

        if not updates:
            return False

        params.extend([job_id, segment_index])
        query = f"UPDATE video_segments SET {', '.join(updates)} WHERE job_id = ? AND segment_index = ?"

        cursor = conn.execute(query, params)
        logger.info(f"Updated segment {segment_index} for job {job_id}: {updates}")
        return cursor.rowcount > 0

    def update_segment_image(
        self,
        job_id: str,
        segment_index: int,
        image_path: str
    ) -> bool:
        """Update segment image path and URL."""
        return self.update_segment(job_id, segment_index, image_path=image_path)

    def get_job_audio_path(self, job_id: str) -> Optional[str]:
        """Get the audio path for a job."""
        job = self.get_job(job_id)
        return job.audio_path if job else None

    def get_job_output_path(self, job_id: str) -> Optional[str]:
        """Get the output video path for a job."""
        job = self.get_job(job_id)
        return job.output_path if job else None

    def _row_to_segment(self, row) -> VideoSegmentRecord:
        """Convert database row to VideoSegmentRecord."""
        return VideoSegmentRecord(
            id=row["id"],
            job_id=row["job_id"],
            segment_index=row["segment_index"],
            text=row["text"],
            duration=row["duration"],
            image_path=row["image_path"] or "",
            image_url=row["image_url"] or "",
            visual_prompt=row["visual_prompt"] or "",
            emotion=row["emotion"] or "neutral",
            segment_type=row["segment_type"] or "content",
            camera_direction=row["camera_direction"] or "static",
            lighting_mood=row["lighting_mood"] or "cinematic"
        )

    def _path_to_url(self, path: str, job_id: str) -> str:
        """Convert Windows file path to URL for frontend."""
        if not path:
            return ""

        import os
        filename = os.path.basename(path)

        # Determine correct URL based on path
        if "temp_images" in path:
            return f"/temp_images/{job_id}/{filename}"
        elif "faceless" in path:
            return f"/data/faceless/{job_id}/images/{filename}"
        else:
            # Default to temp_images
            return f"/temp_images/{job_id}/{filename}"

    def get_job_for_editor(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get complete job data formatted for the video editor.
        Includes all segments with their images and metadata.
        Falls back to reconstructing segments from script/image_paths if needed.
        """
        job = self.get_job(job_id)
        if not job:
            return None

        segments = self.get_segments(job_id)

        # Parse script JSON
        script = None
        if job.script_json:
            try:
                script = json.loads(job.script_json)
            except json.JSONDecodeError:
                pass

        # Parse image paths JSON
        image_paths = []
        if job.image_paths_json:
            try:
                image_paths = json.loads(job.image_paths_json)
            except json.JSONDecodeError:
                pass

        # Build video URL
        video_url = None
        if job.output_path and job.status == "completed":
            video_url = f"/data/faceless/{job_id}/final.mp4"

        # If no segments in DB but we have script, reconstruct them
        segment_list = []
        if segments:
            # Use segments from video_segments table
            segment_list = [
                {
                    "index": seg.segment_index,
                    "text": seg.text,
                    "duration": seg.duration,
                    "image_path": seg.image_path,
                    "image_url": seg.image_url,
                    "visual_prompt": seg.visual_prompt,
                    "emotion": seg.emotion,
                    "segment_type": seg.segment_type,
                    "camera_direction": seg.camera_direction,
                    "lighting_mood": seg.lighting_mood,
                }
                for seg in segments
            ]
        elif script and "segments" in script:
            # Reconstruct from script and image_paths
            for idx, seg in enumerate(script["segments"]):
                img_path = image_paths[idx] if idx < len(image_paths) else ""
                img_url = self._path_to_url(img_path, job_id) if img_path else ""

                segment_list.append({
                    "index": idx,
                    "text": seg.get("text", ""),
                    "duration": seg.get("duration", 5.0),
                    "image_path": img_path,
                    "image_url": img_url,
                    "visual_prompt": seg.get("visual_prompt", ""),
                    "emotion": seg.get("emotion", "neutral"),
                    "segment_type": seg.get("segment_type", "content"),
                    "camera_direction": seg.get("camera_direction", "static"),
                    "lighting_mood": seg.get("lighting_mood", "cinematic"),
                })

        return {
            "job_id": job.job_id,
            "topic": job.topic,
            "status": job.status,
            "video_url": video_url,
            "output_path": job.output_path,
            "audio_path": job.audio_path,
            "audio_duration": job.audio_duration,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "script": script,
            "settings": {
                "style": job.style,
                "language": job.language,
                "voice": job.voice,
                "duration": job.duration,
                "format": job.format,
                "width": job.width,
                "height": job.height,
                "subtitle_style": job.subtitle_style,
                "art_style": job.art_style,
            },
            "segments": segment_list,
            "segment_count": len(segment_list),
        }

    def to_api_response(self, record: FacelessJobRecord) -> Dict[str, Any]:
        """Convert record to API response format."""
        # Parse JSON fields
        script = None
        if record.script_json:
            try:
                script = json.loads(record.script_json)
            except json.JSONDecodeError:
                pass

        image_paths = []
        if record.image_paths_json:
            try:
                image_paths = json.loads(record.image_paths_json)
            except json.JSONDecodeError:
                pass

        # Build image URLs
        image_urls = []
        for path in image_paths:
            # Convert file paths to URLs
            if "temp_images" in path:
                # Extract job_id and filename
                import os
                filename = os.path.basename(path)
                image_urls.append(f"/data/temp_images/{record.job_id}/{filename}")
            elif "faceless" in path:
                import os
                filename = os.path.basename(path)
                image_urls.append(f"/data/faceless/{record.job_id}/images/{filename}")

        # Build video URL
        video_url = None
        if record.output_path and record.status == "completed":
            video_url = f"/data/faceless/{record.job_id}/final.mp4"

        return {
            "job_id": record.job_id,
            "user_id": record.user_id,
            "topic": record.topic,
            "status": record.status,
            "progress": record.progress,
            "progress_message": record.progress_message,
            "created_at": record.created_at,
            "completed_at": record.completed_at,
            "output_path": record.output_path,
            "video_url": video_url,
            "error": record.error,
            "script": script,
            "audio_duration": record.audio_duration,
            "image_urls": image_urls,
            "used_fallback_script": record.used_fallback_script,
            "used_fallback_visuals": record.used_fallback_visuals,
            "api_limit_reached": record.api_limit_reached,
            "status_details": record.status_details,
            # Settings for editor
            "settings": {
                "style": record.style,
                "language": record.language,
                "voice": record.voice,
                "duration": record.duration,
                "format": record.format,
                "subtitle_style": record.subtitle_style,
                "art_style": record.art_style,
            }
        }


# Global repository instance
_faceless_jobs_repo: Optional[FacelessJobsRepository] = None


def get_faceless_jobs_repository() -> FacelessJobsRepository:
    """Get or create the faceless jobs repository singleton."""
    global _faceless_jobs_repo
    if _faceless_jobs_repo is None:
        _faceless_jobs_repo = FacelessJobsRepository()
    return _faceless_jobs_repo
