"""
Clips Repository.
Stores clip metadata and subtitles for the editor.
"""
import json
import sqlite3
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime


@dataclass
class Subtitle:
    """Single subtitle entry."""
    id: str
    start: float
    end: float
    text: str


@dataclass
class ClipRecord:
    """Clip record with metadata."""
    clip_id: str
    batch_id: str
    clip_index: int
    duration: float
    video_url: Optional[str] = None
    srt_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    video_filename: Optional[str] = None  # Revideo rendered video filename
    subtitles: List[Subtitle] = field(default_factory=list)
    status: str = "ready"
    style_preset: str = "clean"
    font_size: str = "M"
    position: str = "center"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SQLiteClipsRepository:
    """SQLite-based clips repository."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            data_dir = Path(__file__).parent.parent.parent / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "app.db")

        self.db_path = db_path
        self._init_tables()

    def _init_tables(self):
        """Initialize database tables."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Clips table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clips (
                    clip_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    clip_index INTEGER NOT NULL,
                    duration REAL NOT NULL,
                    video_url TEXT,
                    srt_url TEXT,
                    thumbnail_url TEXT,
                    video_filename TEXT,
                    status TEXT DEFAULT 'ready',
                    style_preset TEXT DEFAULT 'clean',
                    font_size TEXT DEFAULT 'M',
                    position TEXT DEFAULT 'center',
                    created_at TEXT,
                    updated_at TEXT
                )
            """)

            # Add video_filename column if not exists (migration)
            try:
                cursor.execute("ALTER TABLE clips ADD COLUMN video_filename TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Subtitles table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subtitles (
                    id TEXT PRIMARY KEY,
                    clip_id TEXT NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    text TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    FOREIGN KEY (clip_id) REFERENCES clips(clip_id) ON DELETE CASCADE
                )
            """)

            # Index on batch_id
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_clips_batch_id ON clips(batch_id)
            """)

            # Index on clip_id for subtitles
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_subtitles_clip_id ON subtitles(clip_id)
            """)

            conn.commit()
        finally:
            conn.close()

    def create_clip(self, clip: ClipRecord) -> ClipRecord:
        """Create a new clip record."""
        now = datetime.utcnow().isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO clips (
                    clip_id, batch_id, clip_index, duration,
                    video_url, srt_url, thumbnail_url, video_filename, status,
                    style_preset, font_size, position,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                clip.clip_id, clip.batch_id, clip.clip_index, clip.duration,
                clip.video_url, clip.srt_url, clip.thumbnail_url, clip.video_filename, clip.status,
                clip.style_preset, clip.font_size, clip.position,
                now, now
            ))

            # Insert subtitles
            for i, sub in enumerate(clip.subtitles):
                cursor.execute("""
                    INSERT INTO subtitles (id, clip_id, start_time, end_time, text, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (sub.id, clip.clip_id, sub.start, sub.end, sub.text, i))

            conn.commit()
            clip.created_at = datetime.fromisoformat(now)
            clip.updated_at = datetime.fromisoformat(now)
            return clip
        finally:
            conn.close()

    def get_clip(self, clip_id: str) -> Optional[ClipRecord]:
        """Get a clip by ID."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT clip_id, batch_id, clip_index, duration,
                       video_url, srt_url, thumbnail_url, video_filename, status,
                       style_preset, font_size, position,
                       created_at, updated_at
                FROM clips WHERE clip_id = ?
            """, (clip_id,))

            row = cursor.fetchone()
            if not row:
                return None

            # Get subtitles
            cursor.execute("""
                SELECT id, start_time, end_time, text
                FROM subtitles
                WHERE clip_id = ?
                ORDER BY sort_order
            """, (clip_id,))

            subtitles = [
                Subtitle(id=r[0], start=r[1], end=r[2], text=r[3])
                for r in cursor.fetchall()
            ]

            return ClipRecord(
                clip_id=row[0],
                batch_id=row[1],
                clip_index=row[2],
                duration=row[3],
                video_url=row[4],
                srt_url=row[5],
                thumbnail_url=row[6],
                video_filename=row[7],
                status=row[8],
                style_preset=row[9],
                font_size=row[10],
                position=row[11],
                subtitles=subtitles,
                created_at=datetime.fromisoformat(row[12]) if row[12] else None,
                updated_at=datetime.fromisoformat(row[13]) if row[13] else None,
            )
        finally:
            conn.close()

    def get_clips_by_batch(self, batch_id: str) -> List[ClipRecord]:
        """Get all clips for a batch."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT clip_id, batch_id, clip_index, duration,
                       video_url, srt_url, thumbnail_url, video_filename, status,
                       style_preset, font_size, position,
                       created_at, updated_at
                FROM clips
                WHERE batch_id = ?
                ORDER BY clip_index
            """, (batch_id,))

            clips = []
            for row in cursor.fetchall():
                # Get subtitle count only (not full subtitles for list view)
                cursor.execute("""
                    SELECT COUNT(*) FROM subtitles WHERE clip_id = ?
                """, (row[0],))
                subtitle_count = cursor.fetchone()[0]

                clips.append(ClipRecord(
                    clip_id=row[0],
                    batch_id=row[1],
                    clip_index=row[2],
                    duration=row[3],
                    video_url=row[4],
                    srt_url=row[5],
                    thumbnail_url=row[6],
                    video_filename=row[7],
                    status=row[8],
                    style_preset=row[9],
                    font_size=row[10],
                    position=row[11],
                    subtitles=[Subtitle(id="", start=0, end=0, text="")] * subtitle_count,  # Placeholder for count
                    created_at=datetime.fromisoformat(row[12]) if row[12] else None,
                    updated_at=datetime.fromisoformat(row[13]) if row[13] else None,
                ))

            return clips
        finally:
            conn.close()

    def update_subtitles(self, clip_id: str, subtitles: List[Subtitle]) -> bool:
        """Update subtitles for a clip."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Delete existing subtitles
            cursor.execute("DELETE FROM subtitles WHERE clip_id = ?", (clip_id,))

            # Insert new subtitles
            for i, sub in enumerate(subtitles):
                cursor.execute("""
                    INSERT INTO subtitles (id, clip_id, start_time, end_time, text, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (sub.id, clip_id, sub.start, sub.end, sub.text, i))

            # Update clip timestamp
            cursor.execute("""
                UPDATE clips SET updated_at = ? WHERE clip_id = ?
            """, (datetime.utcnow().isoformat(), clip_id))

            conn.commit()
            return True
        finally:
            conn.close()

    def update_clip_style(self, clip_id: str, style_preset: str, font_size: str, position: str) -> bool:
        """Update clip style settings."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE clips
                SET style_preset = ?, font_size = ?, position = ?, updated_at = ?
                WHERE clip_id = ?
            """, (style_preset, font_size, position, datetime.utcnow().isoformat(), clip_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def update_clip_status(self, clip_id: str, status: str, video_url: Optional[str] = None) -> bool:
        """Update clip status and optionally video URL."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            if video_url:
                cursor.execute("""
                    UPDATE clips
                    SET status = ?, video_url = ?, updated_at = ?
                    WHERE clip_id = ?
                """, (status, video_url, datetime.utcnow().isoformat(), clip_id))
            else:
                cursor.execute("""
                    UPDATE clips
                    SET status = ?, updated_at = ?
                    WHERE clip_id = ?
                """, (status, datetime.utcnow().isoformat(), clip_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_clip(self, clip_id: str) -> bool:
        """Delete a clip and its subtitles."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM subtitles WHERE clip_id = ?", (clip_id,))
            cursor.execute("DELETE FROM clips WHERE clip_id = ?", (clip_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def update_clip_video_url(self, clip_id: str, video_url: str) -> bool:
        """Update clip video URL."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE clips
                SET video_url = ?, updated_at = ?
                WHERE clip_id = ?
            """, (video_url, datetime.utcnow().isoformat(), clip_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def update_clip_video_filename(self, clip_id: str, video_filename: str) -> bool:
        """Update clip video filename (Revideo output)."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE clips
                SET video_filename = ?, updated_at = ?
                WHERE clip_id = ?
            """, (video_filename, datetime.utcnow().isoformat(), clip_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def get_clips_repository() -> SQLiteClipsRepository:
    """Get singleton clips repository."""
    return SQLiteClipsRepository()
