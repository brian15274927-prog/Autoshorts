"""
Full Pipeline Test - Tests complete video generation without API keys.
Uses fallback mechanisms to validate the entire pipeline works.
"""
import sys
import asyncio
import os
import logging
import time

# CRITICAL: Windows asyncio fix MUST be first
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    # Fix Windows console encoding for emojis
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, r"C:\dake")


async def test_full_pipeline():
    """Test the complete faceless video generation pipeline."""
    print("\n" + "="*60)
    print("FULL PIPELINE TEST - Faceless Video Generation")
    print("="*60 + "\n")

    from app.services.faceless_engine import FacelessEngine, JobStatus
    from app.services.llm_service import ScriptStyle

    # Initialize engine
    print("[1/6] Initializing FacelessEngine...")
    engine = FacelessEngine()
    print("      OK - Engine initialized\n")

    # Create test video
    topic = "История Чингисхана"
    duration = 60

    print(f"[2/6] Starting video generation...")
    print(f"      Topic: {topic}")
    print(f"      Duration: {duration}s")
    print(f"      Style: viral")
    print(f"      Format: 9:16 (1080x1920)")
    print("")

    # Start generation
    job_id = await engine.create_faceless_video(
        topic=topic,
        style=ScriptStyle.VIRAL,
        language="ru",
        duration=duration,
        format="9:16",
        subtitle_style="hormozi",
        background_music=False  # Skip music for test
    )

    print(f"      Job ID: {job_id}")
    print("")

    # Monitor progress
    print("[3/6] Monitoring progress...")
    start_time = time.time()
    last_status = None
    last_progress = -1

    while True:
        job = engine.get_job(job_id)

        if job is None:
            print("      ERROR: Job not found!")
            break

        # Only print on change
        if job.status != last_status or int(job.progress) != last_progress:
            elapsed = time.time() - start_time
            print(f"      [{elapsed:6.1f}s] {job.progress:3.0f}% - {job.status.value}: {job.progress_message}")
            last_status = job.status
            last_progress = int(job.progress)

        if job.status == JobStatus.COMPLETED:
            print("")
            print("[4/6] Generation COMPLETED!")
            break
        elif job.status == JobStatus.FAILED:
            print("")
            print(f"[4/6] Generation FAILED: {job.error}")
            return False

        await asyncio.sleep(1)

    # Verify output
    print("")
    print("[5/6] Verifying output...")
    job = engine.get_job(job_id)

    if job.output_path and os.path.exists(job.output_path):
        file_size = os.path.getsize(job.output_path)
        print(f"      Output file: {job.output_path}")
        print(f"      File size: {file_size:,} bytes ({file_size/1024/1024:.2f} MB)")

        # Get video duration using ffprobe
        from app.services.faceless_engine import FFPROBE_PATH
        import subprocess
        import json

        cmd = [
            FFPROBE_PATH, "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "json",
            job.output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            video_duration = float(data["format"]["duration"])
            print(f"      Video duration: {video_duration:.1f}s")

            if abs(video_duration - duration) < 5:  # Allow 5s tolerance
                print(f"      Duration check: PASS (target: {duration}s)")
            else:
                print(f"      Duration check: WARNING (target: {duration}s, actual: {video_duration:.1f}s)")
    else:
        print(f"      ERROR: Output file not found!")
        return False

    # Summary
    print("")
    print("[6/6] Test Summary")
    print("-" * 40)

    script_segments = len(job.script.get("segments", [])) if job.script else 0
    print(f"      Script segments: {script_segments}")
    print(f"      Total script duration: {job.script.get('total_duration', 0):.1f}s" if job.script else "")
    print(f"      Audio duration: {job.audio_duration:.1f}s" if job.audio_duration else "")
    print(f"      Images generated: {len(job.image_paths)}")
    print(f"      Clips animated: {len(job.clip_paths)}")
    print(f"      Final video: {'OK' if job.output_path else 'MISSING'}")

    total_time = time.time() - start_time
    print("")
    print(f"      Total time: {total_time:.1f}s ({total_time/60:.1f} min)")
    print("")
    print("="*60)
    print("TEST PASSED - Full pipeline working!")
    print("="*60)

    return True


if __name__ == "__main__":
    try:
        result = asyncio.run(test_full_pipeline())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nTest failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
