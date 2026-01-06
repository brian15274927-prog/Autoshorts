"""
Working example: Direct rendering without Celery.
Run this script to test the video rendering engine.
"""
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

sys.path.insert(0, str(Path(__file__).parent))

from app.rendering import (
    VideoRenderEngine,
    RenderJob,
    VideoScript,
    SceneData,
    SceneType,
    AudioTimestamps,
    WordTimestamp,
    SubtitleStyle,
    RenderProgress,
)


def create_test_data():
    """Create sample data for testing."""

    script = VideoScript(
        script_id="test_001",
        title="AI Video Demo",
        total_duration=15.0,
        scenes=[
            SceneData(
                scene_id="scene_1",
                scene_type=SceneType.VIDEO,
                background_path="/path/to/background1.mp4",
                start_time=0.0,
                end_time=7.0,
                text="Welcome to our AI video platform.",
                transition_in="crossfade",
                transition_duration=0.5,
            ),
            SceneData(
                scene_id="scene_2",
                scene_type=SceneType.VIDEO,
                background_path="/path/to/background2.mp4",
                start_time=7.0,
                end_time=15.0,
                text="Create stunning videos in minutes.",
            ),
        ],
    )

    timestamps = AudioTimestamps(
        total_duration=15.0,
        words=[
            WordTimestamp(word="Welcome", start=0.0, end=0.45),
            WordTimestamp(word="to", start=0.50, end=0.65),
            WordTimestamp(word="our", start=0.70, end=0.90),
            WordTimestamp(word="AI", start=0.95, end=1.25),
            WordTimestamp(word="video", start=1.30, end=1.70),
            WordTimestamp(word="platform.", start=1.75, end=2.40),
            WordTimestamp(word="Create", start=7.00, end=7.45),
            WordTimestamp(word="stunning", start=7.50, end=8.10),
            WordTimestamp(word="videos", start=8.15, end=8.65),
            WordTimestamp(word="in", start=8.70, end=8.85),
            WordTimestamp(word="minutes.", start=8.90, end=9.50),
        ],
    )

    job = RenderJob(
        job_id="demo_job_001",
        script=script,
        audio_path="/path/to/voice.wav",
        timestamps=timestamps,
        bgm_path="/path/to/bgm.mp3",
        output_dir="/tmp/video_output",
        output_filename="demo_video.mp4",
        generate_srt=True,
    )

    return job


def on_progress(progress: RenderProgress):
    """Progress callback."""
    bar_length = 30
    filled = int(bar_length * progress.progress / 100)
    bar = "=" * filled + "-" * (bar_length - filled)
    print(f"\r[{bar}] {progress.progress:5.1f}% | {progress.stage}: {progress.message}", end="", flush=True)
    if progress.progress >= 100:
        print()


def main():
    """Run example rendering."""
    print("=" * 60)
    print("VIDEO RENDERING ENGINE - TEST")
    print("=" * 60)

    job = create_test_data()

    print(f"\nJob ID: {job.job_id}")
    print(f"Scenes: {len(job.script.scenes)}")
    print(f"Duration: {job.script.total_duration}s")
    print(f"Words: {len(job.timestamps.words)}")
    print()

    subtitle_style = SubtitleStyle(
        font_size=70,
        color="white",
        active_color="#FFD700",
        stroke_color="black",
        stroke_width=3,
    )

    engine = VideoRenderEngine(
        width=1080,
        height=1920,
        fps=30,
        video_bitrate="8M",
        preset="medium",
        bgm_volume_db=-20.0,
        subtitle_style=subtitle_style,
        progress_callback=on_progress,
    )

    print("Starting render...")
    print("-" * 60)

    result = engine.render(job)

    print("-" * 60)

    if result.success:
        print(f"\nSUCCESS!")
        print(f"Output: {result.output_path}")
        print(f"SRT: {result.srt_path}")
        print(f"Size: {result.file_size_mb} MB")
        print(f"Time: {result.duration_seconds:.1f}s")
    else:
        print(f"\nFAILED: {result.error}")

    return result


if __name__ == "__main__":
    main()
