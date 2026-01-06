"""
Working example: Submit render job to Celery.
Requires Redis and Celery worker running.
"""
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def submit_job():
    """Submit render job to Celery worker."""
    from app.rendering.tasks import render_video_task, get_task_status

    script_json = {
        "script_id": "celery_test_001",
        "title": "Celery Render Test",
        "total_duration": 15.0,
        "scenes": [
            {
                "scene_id": "scene_1",
                "scene_type": "video",
                "background_path": "/path/to/background1.mp4",
                "start_time": 0.0,
                "end_time": 7.0,
                "text": "Welcome to our AI video platform.",
                "transition_in": "crossfade",
                "transition_duration": 0.5,
            },
            {
                "scene_id": "scene_2",
                "scene_type": "video",
                "background_path": "/path/to/background2.mp4",
                "start_time": 7.0,
                "end_time": 15.0,
                "text": "Create stunning videos in minutes.",
            },
        ],
    }

    timestamps_json = {
        "total_duration": 15.0,
        "words": [
            {"word": "Welcome", "start": 0.0, "end": 0.45},
            {"word": "to", "start": 0.50, "end": 0.65},
            {"word": "our", "start": 0.70, "end": 0.90},
            {"word": "AI", "start": 0.95, "end": 1.25},
            {"word": "video", "start": 1.30, "end": 1.70},
            {"word": "platform.", "start": 1.75, "end": 2.40},
            {"word": "Create", "start": 7.00, "end": 7.45},
            {"word": "stunning", "start": 7.50, "end": 8.10},
            {"word": "videos", "start": 8.15, "end": 8.65},
            {"word": "in", "start": 8.70, "end": 8.85},
            {"word": "minutes.", "start": 8.90, "end": 9.50},
        ],
    }

    print("Submitting render job to Celery...")

    task = render_video_task.delay(
        job_id="celery_demo_001",
        script_json=script_json,
        audio_path="/path/to/voice.wav",
        timestamps_json=timestamps_json,
        bgm_path="/path/to/bgm.mp3",
        output_dir="/tmp/video_output",
        output_filename="celery_output.mp4",
        generate_srt=True,
        video_width=1080,
        video_height=1920,
        fps=30,
        video_bitrate="8M",
        preset="medium",
        bgm_volume_db=-20.0,
        subtitle_font_size=70,
        subtitle_color="white",
        subtitle_active_color="#FFD700",
    )

    print(f"Task submitted: {task.id}")
    print("Monitoring progress...")
    print("-" * 50)

    while not task.ready():
        status = get_task_status(task.id)

        if status["status"] == "PROGRESS":
            progress = status.get("progress", {})
            pct = progress.get("progress", 0)
            stage = progress.get("stage", "unknown")
            msg = progress.get("message", "")
            print(f"[{pct:5.1f}%] {stage}: {msg}")
        else:
            print(f"Status: {status['status']}")

        time.sleep(2)

    print("-" * 50)

    if task.successful():
        result = task.result
        if result["success"]:
            print(f"SUCCESS!")
            print(f"Output: {result['output_path']}")
            print(f"SRT: {result['srt_path']}")
            print(f"Size: {result['file_size_mb']} MB")
            print(f"Time: {result['duration_seconds']:.1f}s")
        else:
            print(f"RENDER FAILED: {result['error']}")
    else:
        print(f"TASK FAILED: {task.result}")


if __name__ == "__main__":
    submit_job()
