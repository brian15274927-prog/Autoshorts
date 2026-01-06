"""
Celery tasks for video rendering.
Production-ready async task processing.
"""
import logging
import os
from typing import Any, Optional

from celery import Task, states
from celery.exceptions import SoftTimeLimitExceeded, Reject

from app.celery_app import celery_app
from .engine import VideoRenderEngine
from .subtitles import SubtitleStyle
from .models import (
    RenderJob,
    RenderResult,
    RenderProgress,
    VideoScript,
    SceneData,
    SceneType,
    AudioTimestamps,
    WordTimestamp,
)

logger = logging.getLogger(__name__)


class VideoRenderTask(Task):
    """
    Base Celery task with progress tracking and error handling.
    """

    abstract = True
    track_started = True
    acks_late = True
    reject_on_worker_lost = True

    max_retries = 2
    default_retry_delay = 60

    _engine: Optional[VideoRenderEngine] = None

    @property
    def engine(self) -> VideoRenderEngine:
        if self._engine is None:
            self._engine = VideoRenderEngine()
        return self._engine

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        job_id = kwargs.get("job_id") or (args[0] if args else "unknown")
        logger.error(f"Task {task_id} failed for job {job_id}: {exc}")
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_success(self, retval, task_id, args, kwargs):
        job_id = kwargs.get("job_id") or (args[0] if args else "unknown")
        logger.info(f"Task {task_id} completed successfully for job {job_id}")
        super().on_success(retval, task_id, args, kwargs)

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        job_id = kwargs.get("job_id") or (args[0] if args else "unknown")
        logger.warning(f"Task {task_id} retrying for job {job_id}: {exc}")
        super().on_retry(exc, task_id, args, kwargs, einfo)


def create_progress_callback(task: Task, task_id: str):
    """
    Factory for creating Celery progress callback.
    Updates task state with rendering progress.
    """
    def callback(progress: RenderProgress) -> None:
        task.update_state(
            task_id=task_id,
            state="PROGRESS",
            meta={
                "job_id": progress.job_id,
                "stage": progress.stage,
                "progress": progress.progress,
                "current_scene": progress.current_scene,
                "total_scenes": progress.total_scenes,
                "message": progress.message,
            },
        )

    return callback


def parse_script_json(script_json: dict[str, Any]) -> VideoScript:
    """
    Parse script JSON into VideoScript model.
    """
    scenes = []
    for scene_data in script_json["scenes"]:
        scene = SceneData(
            scene_id=scene_data["scene_id"],
            scene_type=SceneType(scene_data.get("scene_type", "video")),
            background_path=scene_data["background_path"],
            start_time=float(scene_data["start_time"]),
            end_time=float(scene_data["end_time"]),
            text=scene_data.get("text", ""),
            transition_in=scene_data.get("transition_in"),
            transition_duration=float(scene_data.get("transition_duration", 0.5)),
        )
        scenes.append(scene)

    return VideoScript(
        script_id=script_json["script_id"],
        title=script_json.get("title", "Untitled"),
        scenes=scenes,
        total_duration=float(script_json["total_duration"]),
    )


def parse_timestamps_json(timestamps_json: dict[str, Any]) -> AudioTimestamps:
    """
    Parse timestamps JSON into AudioTimestamps model.
    """
    words = []
    for word_data in timestamps_json["words"]:
        word = WordTimestamp(
            word=word_data["word"],
            start=float(word_data["start"]),
            end=float(word_data["end"]),
        )
        words.append(word)

    return AudioTimestamps(
        words=words,
        total_duration=float(timestamps_json["total_duration"]),
    )


@celery_app.task(
    base=VideoRenderTask,
    bind=True,
    name="rendering.render_video",
    time_limit=3600,
    soft_time_limit=3300,
)
def render_video_task(
    self,
    job_id: str,
    script_json: dict[str, Any],
    audio_path: str,
    timestamps_json: dict[str, Any],
    bgm_path: Optional[str] = None,
    output_dir: str = "/tmp/video_output",
    output_filename: str = "output.mp4",
    generate_srt: bool = True,
    video_width: int = 1080,
    video_height: int = 1920,
    fps: int = 30,
    video_bitrate: str = "8M",
    preset: str = "medium",
    bgm_volume_db: float = -20.0,
    subtitle_font_size: int = 70,
    subtitle_color: str = "white",
    subtitle_active_color: str = "#FFD700",
) -> dict[str, Any]:
    """
    Celery task for rendering video.

    Args:
        job_id: Unique job identifier
        script_json: Video script with scenes
        audio_path: Path to voice audio file
        timestamps_json: Word-level timestamps from ElevenLabs
        bgm_path: Optional path to background music
        output_dir: Directory for output files
        output_filename: Name of output video file
        generate_srt: Whether to generate SRT subtitle file
        video_width: Video width (default 1080)
        video_height: Video height (default 1920)
        fps: Frames per second (default 30)
        video_bitrate: Video bitrate (default 8M)
        preset: FFmpeg preset (default medium)
        bgm_volume_db: Background music volume in dB (default -20)
        subtitle_font_size: Subtitle font size (default 70)
        subtitle_color: Normal subtitle color (default white)
        subtitle_active_color: Active word color (default #FFD700)

    Returns:
        RenderResult as dictionary
    """
    task_id = self.request.id

    logger.info(f"Starting render task {task_id} for job {job_id}")

    try:
        self.update_state(
            state="PROGRESS",
            meta={
                "job_id": job_id,
                "stage": "parsing",
                "progress": 0,
                "message": "Parsing input data",
            },
        )

        script = parse_script_json(script_json)
        timestamps = parse_timestamps_json(timestamps_json)

        job = RenderJob(
            job_id=job_id,
            script=script,
            audio_path=audio_path,
            timestamps=timestamps,
            bgm_path=bgm_path,
            output_dir=output_dir,
            output_filename=output_filename,
            generate_srt=generate_srt,
        )

        subtitle_style = SubtitleStyle(
            font_size=subtitle_font_size,
            color=subtitle_color,
            active_color=subtitle_active_color,
        )

        progress_callback = create_progress_callback(self, task_id)

        engine = VideoRenderEngine(
            width=video_width,
            height=video_height,
            fps=fps,
            video_bitrate=video_bitrate,
            preset=preset,
            bgm_volume_db=bgm_volume_db,
            subtitle_style=subtitle_style,
            progress_callback=progress_callback,
        )

        result = engine.render(job)

        result_dict = {
            "job_id": result.job_id,
            "success": result.success,
            "output_path": result.output_path,
            "srt_path": result.srt_path,
            "duration_seconds": result.duration_seconds,
            "file_size_mb": result.file_size_mb,
            "error": result.error,
            "video_duration_seconds": result.video_duration_seconds,
            "scenes_count": result.scenes_count,
            "resolution": result.resolution,
            "fps": result.fps,
            "cost_usd": result.cost_usd,
            "cost_breakdown": result.cost_breakdown,
            "usage_metrics": result.usage_metrics,
        }

        if result.success:
            logger.info(
                f"Render completed successfully: {result.output_path}, "
                f"cost=${result.cost_usd:.6f}"
            )
        else:
            cost_str = f"${result.cost_usd:.6f}" if result.cost_usd else "N/A"
            logger.error(f"Render failed: {result.error}, partial_cost={cost_str}")

        return result_dict

    except SoftTimeLimitExceeded:
        logger.error(f"Task {task_id} exceeded soft time limit for job {job_id}")
        return {
            "job_id": job_id,
            "success": False,
            "output_path": None,
            "srt_path": None,
            "duration_seconds": 0,
            "file_size_mb": None,
            "error": "Task exceeded time limit (55 minutes)",
        }

    except FileNotFoundError as e:
        logger.error(f"File not found for job {job_id}: {e}")
        return {
            "job_id": job_id,
            "success": False,
            "output_path": None,
            "srt_path": None,
            "duration_seconds": 0,
            "file_size_mb": None,
            "error": f"File not found: {e}",
        }

    except ValueError as e:
        logger.error(f"Invalid input for job {job_id}: {e}")
        return {
            "job_id": job_id,
            "success": False,
            "output_path": None,
            "srt_path": None,
            "duration_seconds": 0,
            "file_size_mb": None,
            "error": f"Invalid input: {e}",
        }

    except Exception as e:
        logger.exception(f"Unexpected error for job {job_id}: {e}")

        if self.request.retries < self.max_retries:
            logger.info(f"Retrying task for job {job_id} (attempt {self.request.retries + 1})")
            raise self.retry(exc=e, countdown=60)

        return {
            "job_id": job_id,
            "success": False,
            "output_path": None,
            "srt_path": None,
            "duration_seconds": 0,
            "file_size_mb": None,
            "error": f"Unexpected error: {e}",
        }


@celery_app.task(name="rendering.get_task_status")
def get_task_status(task_id: str) -> dict[str, Any]:
    """
    Get status of a render task.

    Args:
        task_id: Celery task ID

    Returns:
        Task status and metadata
    """
    result = celery_app.AsyncResult(task_id)

    response = {
        "task_id": task_id,
        "status": result.status,
        "ready": result.ready(),
        "successful": result.successful() if result.ready() else None,
    }

    if result.status == "PROGRESS":
        response["progress"] = result.info
    elif result.ready():
        if result.successful():
            response["result"] = result.result
        else:
            response["error"] = str(result.result)
    elif result.status == "PENDING":
        response["message"] = "Task is pending or unknown"
    elif result.status == "STARTED":
        response["message"] = "Task has started"

    return response


@celery_app.task(name="rendering.cancel_task")
def cancel_task(task_id: str) -> dict[str, Any]:
    """
    Cancel a running or pending render task.

    Args:
        task_id: Celery task ID

    Returns:
        Cancellation result
    """
    celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")

    return {
        "task_id": task_id,
        "cancelled": True,
        "message": "Task cancellation requested",
    }


@celery_app.task(name="rendering.cleanup_old_outputs")
def cleanup_old_outputs(
    output_dir: str = "/tmp/video_output",
    max_age_hours: int = 24,
) -> dict[str, Any]:
    """
    Clean up old render outputs.

    Args:
        output_dir: Base output directory
        max_age_hours: Maximum age in hours

    Returns:
        Cleanup statistics
    """
    import shutil
    import time
    from pathlib import Path

    output_path = Path(output_dir)
    if not output_path.exists():
        return {"deleted_count": 0, "freed_bytes": 0}

    max_age_seconds = max_age_hours * 3600
    current_time = time.time()

    deleted_count = 0
    freed_bytes = 0

    for job_dir in output_path.iterdir():
        if not job_dir.is_dir():
            continue

        try:
            dir_mtime = job_dir.stat().st_mtime
            if current_time - dir_mtime > max_age_seconds:
                dir_size = sum(f.stat().st_size for f in job_dir.rglob("*") if f.is_file())
                shutil.rmtree(job_dir)
                deleted_count += 1
                freed_bytes += dir_size
                logger.info(f"Deleted old output directory: {job_dir}")
        except Exception as e:
            logger.warning(f"Failed to delete {job_dir}: {e}")

    freed_mb = round(freed_bytes / (1024 * 1024), 2)
    logger.info(f"Cleanup complete: deleted {deleted_count} directories, freed {freed_mb}MB")

    return {
        "deleted_count": deleted_count,
        "freed_bytes": freed_bytes,
        "freed_mb": freed_mb,
    }
