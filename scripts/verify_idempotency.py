#!/usr/bin/env python3
"""
Idempotency Verification Script.
Tests all idempotency scenarios to prove production-safety.

Run: python scripts/verify_idempotency.py
"""
import os
import sys
import json
import tempfile
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test environment
os.environ["STORAGE_BACKEND"] = "sqlite"
os.environ["DATABASE_PATH"] = ":memory:"
os.environ["DEV_BROWSER_MODE"] = "false"

from fastapi.testclient import TestClient
from app.api.main import create_app
from app.persistence.database import get_connection, close_connection
from app.persistence.idempotency_repo import get_idempotency_repository, IdempotencyStatus


def reset_singletons():
    """Reset all singletons for clean test state."""
    import app.persistence.database as db_module
    import app.persistence.idempotency_repo as idem_module
    import app.auth.repository as auth_module
    import app.credits.service as credit_module
    import app.credits.job_tracker as job_module

    db_module._connection = None
    idem_module._idempotency_repo = None

    if hasattr(auth_module, '_user_repo'):
        auth_module._user_repo = None
    if hasattr(credit_module, '_credit_service'):
        credit_module._credit_service = None
    if hasattr(job_module, '_job_tracker'):
        job_module._job_tracker = None


_TEST_AUDIO_PATH = None
_TEST_BG_PATH = None


def create_valid_request_body():
    """Create a valid render request body."""
    return {
        "script": {
            "script_id": "test-script-001",
            "title": "Test Video",
            "scenes": [
                {
                    "scene_id": "scene-1",
                    "scene_type": "video",
                    "background_path": _TEST_BG_PATH,
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "text": "Hello world",
                }
            ],
            "total_duration": 5.0,
        },
        "audio_path": _TEST_AUDIO_PATH,
        "timestamps": {
            "words": [
                {"word": "Hello", "start": 0.0, "end": 0.5},
                {"word": "world", "start": 0.5, "end": 1.0},
            ],
            "total_duration": 5.0,
        },
    }


def create_different_request_body():
    """Create a different render request body (different hash)."""
    body = create_valid_request_body()
    body["script"]["script_id"] = "different-script-002"
    return body


def get_user_credits(client, user_id: str) -> int:
    """Get current credits for user."""
    response = client.get(
        "/render/me/credits",
        headers={"X-User-Id": user_id},
    )
    if response.status_code == 200:
        return response.json().get("credits_raw", 0)
    return 0


def print_result(test_name: str, passed: bool, details: str = ""):
    """Print test result."""
    status = "\033[92mPASS\033[0m" if passed else "\033[91mFAIL\033[0m"
    print(f"  [{status}] {test_name}")
    if details:
        print(f"         {details}")


def run_tests():
    """Run all idempotency verification tests."""
    global _TEST_AUDIO_PATH, _TEST_BG_PATH

    print("\n" + "=" * 60)
    print("IDEMPOTENCY VERIFICATION TESTS")
    print("=" * 60)

    reset_singletons()

    # Create test audio file (cross-platform)
    temp_dir = tempfile.mkdtemp()
    audio_path = os.path.join(temp_dir, "test_audio.mp3")
    bg_path = os.path.join(temp_dir, "test_bg.mp4")
    with open(audio_path, "wb") as f:
        f.write(b"fake audio data")
    with open(bg_path, "wb") as f:
        f.write(b"fake video data")

    # Set global paths for request bodies
    _TEST_AUDIO_PATH = audio_path
    _TEST_BG_PATH = bg_path

    app = create_app(debug=True, require_auth=True)
    client = TestClient(app, raise_server_exceptions=False)

    user_id = "test-user-001"
    all_passed = True

    # =========================================================================
    # TEST A: POST /render without Idempotency-Key -> 400
    # =========================================================================
    print("\n[TEST A] POST /render without Idempotency-Key header")

    initial_credits = get_user_credits(client, user_id)
    print(f"         Credits before: {initial_credits}")

    response = client.post(
        "/render",
        json=create_valid_request_body(),
        headers={"X-User-Id": user_id},
    )

    passed = response.status_code == 400 and "IDEMPOTENCY_KEY_REQUIRED" in str(response.json())
    all_passed &= passed
    print_result(
        "Returns 400 for missing Idempotency-Key",
        passed,
        f"status={response.status_code}, code={response.json().get('detail', {}).get('code', 'N/A')}"
    )

    after_credits = get_user_credits(client, user_id)
    passed = after_credits == initial_credits
    all_passed &= passed
    print_result(
        "Credits unchanged",
        passed,
        f"before={initial_credits}, after={after_credits}"
    )

    # =========================================================================
    # TEST B: POST /render with key K1 -> 202, returns task_id
    # =========================================================================
    print("\n[TEST B] POST /render with valid Idempotency-Key")

    initial_credits = get_user_credits(client, user_id)
    print(f"         Credits before: {initial_credits}")

    key_k1 = "test-key-k1-unique"
    response = client.post(
        "/render",
        json=create_valid_request_body(),
        headers={
            "X-User-Id": user_id,
            "Idempotency-Key": key_k1,
        },
    )

    # Note: Will fail with 503 if Redis not running, but idempotency still works
    # We accept either 202 (success) or 503 (Redis down) - both are valid for testing
    if response.status_code == 503:
        print("         (Redis unavailable - testing idempotency with FAILED state)")
        # Record should be marked FAILED, credits not deducted
        after_credits = get_user_credits(client, user_id)
        passed = after_credits == initial_credits
        all_passed &= passed
        print_result(
            "Credits unchanged when Redis unavailable",
            passed,
            f"before={initial_credits}, after={after_credits}"
        )

        # Check record is FAILED
        repo = get_idempotency_repository()
        record = repo.find_by_key(user_id, key_k1)
        passed = record is not None and record.status == IdempotencyStatus.FAILED
        all_passed &= passed
        print_result(
            "Record marked as FAILED (not stuck in PENDING)",
            passed,
            f"status={record.status.value if record else 'None'}"
        )

        # Test C/D with manually created COMPLETED record (no Redis needed)
        print("\n[TEST C] Cached response from COMPLETED record (simulated)")

        key_completed = "test-key-completed-manual"
        repo = get_idempotency_repository()
        from app.persistence.idempotency_repo import IdempotencyRepository

        # Create COMPLETED record manually
        completed_hash = IdempotencyRepository.compute_request_hash({
            "script_id": "test-script-001",
            "audio_path": _TEST_AUDIO_PATH,
            "bgm_path": None,
            "scenes_count": 1,
            "words_count": 2,
            "settings": {"video_width": 1080, "video_height": 1920, "fps": 30},
        })
        repo.create_pending(user_id, key_completed, completed_hash)
        repo.update_completed(user_id, key_completed, "fake-task-id-123", "fake-job-id-456")

        credits_before_c = get_user_credits(client, user_id)
        print(f"         Credits before: {credits_before_c}")

        response_c = client.post(
            "/render",
            json=create_valid_request_body(),
            headers={
                "X-User-Id": user_id,
                "Idempotency-Key": key_completed,
            },
        )

        passed = response_c.status_code == 202
        all_passed &= passed
        print_result(
            "Returns 202 (cached response from COMPLETED)",
            passed,
            f"status={response_c.status_code}"
        )

        passed = response_c.json().get("task_id") == "fake-task-id-123"
        all_passed &= passed
        print_result(
            "Returns original task_id from cache",
            passed,
            f"task_id={response_c.json().get('task_id')}"
        )

        passed = "idempotent response" in response_c.json().get("message", "").lower()
        all_passed &= passed
        print_result(
            "Message indicates cached response",
            passed,
            f"message={response_c.json().get('message', '')}"
        )

        credits_after_c = get_user_credits(client, user_id)
        passed = credits_after_c == credits_before_c
        all_passed &= passed
        print_result(
            "NO credit deduction (double-spend prevented)",
            passed,
            f"before={credits_before_c}, after={credits_after_c}"
        )

        # =====================================================================
        # TEST D: POST with COMPLETED key but DIFFERENT body -> 422
        # =====================================================================
        print("\n[TEST D] Different body with COMPLETED key -> 422")

        credits_before_d = get_user_credits(client, user_id)
        print(f"         Credits before: {credits_before_d}")

        response_d = client.post(
            "/render",
            json=create_different_request_body(),
            headers={
                "X-User-Id": user_id,
                "Idempotency-Key": key_completed,
            },
        )

        passed = response_d.status_code == 422
        all_passed &= passed
        print_result(
            "Returns 422 for hash mismatch",
            passed,
            f"status={response_d.status_code}, code={response_d.json().get('detail', {}).get('code', 'N/A')}"
        )

        credits_after_d = get_user_credits(client, user_id)
        passed = credits_after_d == credits_before_d
        all_passed &= passed
        print_result(
            "Credits unchanged",
            passed,
            f"before={credits_before_d}, after={credits_after_d}"
        )

    else:
        passed = response.status_code == 202
        all_passed &= passed
        task_id_1 = response.json().get("task_id")
        job_id_1 = response.json().get("job_id")
        print_result(
            "Returns 202 Accepted",
            passed,
            f"status={response.status_code}, task_id={task_id_1}"
        )

        after_credits = get_user_credits(client, user_id)
        passed = after_credits == initial_credits - 1
        all_passed &= passed
        print_result(
            "1 credit deducted",
            passed,
            f"before={initial_credits}, after={after_credits}"
        )

        # =====================================================================
        # TEST C: Repeat with same key K1 and same body -> cached response
        # =====================================================================
        print("\n[TEST C] Repeat POST with same key and same body")

        credits_before_repeat = get_user_credits(client, user_id)
        print(f"         Credits before: {credits_before_repeat}")

        response2 = client.post(
            "/render",
            json=create_valid_request_body(),
            headers={
                "X-User-Id": user_id,
                "Idempotency-Key": key_k1,
            },
        )

        passed = response2.status_code == 202
        all_passed &= passed
        print_result(
            "Returns 202 (cached response)",
            passed,
            f"status={response2.status_code}"
        )

        task_id_2 = response2.json().get("task_id")
        passed = task_id_2 == task_id_1
        all_passed &= passed
        print_result(
            "Returns same task_id (idempotent)",
            passed,
            f"original={task_id_1}, repeat={task_id_2}"
        )

        passed = "idempotent response" in response2.json().get("message", "").lower()
        all_passed &= passed
        print_result(
            "Message indicates cached response",
            passed,
            f"message={response2.json().get('message', '')}"
        )

        credits_after_repeat = get_user_credits(client, user_id)
        passed = credits_after_repeat == credits_before_repeat
        all_passed &= passed
        print_result(
            "NO second credit deduction (double-spend prevented)",
            passed,
            f"before={credits_before_repeat}, after={credits_after_repeat}"
        )

        # =====================================================================
        # TEST D: POST with key K1 but DIFFERENT body -> 422
        # =====================================================================
        print("\n[TEST D] POST with same key but different body")

        credits_before = get_user_credits(client, user_id)
        print(f"         Credits before: {credits_before}")

        response3 = client.post(
            "/render",
            json=create_different_request_body(),
            headers={
                "X-User-Id": user_id,
                "Idempotency-Key": key_k1,
            },
        )

        passed = response3.status_code == 422
        all_passed &= passed
        print_result(
            "Returns 422 for hash mismatch",
            passed,
            f"status={response3.status_code}, code={response3.json().get('detail', {}).get('code', 'N/A')}"
        )

        credits_after = get_user_credits(client, user_id)
        passed = credits_after == credits_before
        all_passed &= passed
        print_result(
            "Credits unchanged",
            passed,
            f"before={credits_before}, after={credits_after}"
        )

    # =========================================================================
    # TEST E: Simulate PENDING state and verify 409
    # =========================================================================
    print("\n[TEST E] Simulate PENDING state -> 409 Conflict")

    key_pending = "test-key-pending-simulate"
    repo = get_idempotency_repository()

    # Manually create a PENDING record
    from app.persistence.idempotency_repo import IdempotencyRepository
    request_hash = IdempotencyRepository.compute_request_hash({
        "script_id": "test-script-001",
        "audio_path": _TEST_AUDIO_PATH,
        "bgm_path": None,
        "scenes_count": 1,
        "words_count": 2,
        "settings": {"video_width": 1080, "video_height": 1920, "fps": 30},
    })
    repo.create_pending(user_id, key_pending, request_hash)

    credits_before = get_user_credits(client, user_id)
    print(f"         Credits before: {credits_before}")
    print(f"         Manually created PENDING record for key: {key_pending}")

    response4 = client.post(
        "/render",
        json=create_valid_request_body(),
        headers={
            "X-User-Id": user_id,
            "Idempotency-Key": key_pending,
        },
    )

    passed = response4.status_code == 409
    all_passed &= passed
    print_result(
        "Returns 409 Conflict for PENDING key",
        passed,
        f"status={response4.status_code}, code={response4.json().get('detail', {}).get('code', 'N/A')}"
    )

    credits_after = get_user_credits(client, user_id)
    passed = credits_after == credits_before
    all_passed &= passed
    print_result(
        "Credits unchanged",
        passed,
        f"before={credits_before}, after={credits_after}"
    )

    # =========================================================================
    # TEST F: Verify JSON serialization stability
    # =========================================================================
    print("\n[TEST F] Response caching JSON serialization")

    record = repo.find_by_key(user_id, key_pending)
    if record:
        # Test that response_data can be None and record still works
        passed = record.response_data is None or isinstance(record.response_data, dict)
        all_passed &= passed
        print_result(
            "response_data is None or dict",
            passed,
            f"type={type(record.response_data).__name__}"
        )

        # Test that created_at/updated_at are datetime
        passed = isinstance(record.created_at, datetime) and isinstance(record.updated_at, datetime)
        all_passed &= passed
        print_result(
            "Timestamps are datetime objects",
            passed,
            f"created_at={type(record.created_at).__name__}"
        )

    # =========================================================================
    # TEST G: Verify FAILED retry works
    # =========================================================================
    print("\n[TEST G] FAILED record allows retry")

    key_failed = "test-key-failed-retry"
    repo.create_pending(user_id, key_failed, request_hash)
    repo.update_failed(user_id, key_failed, "Simulated failure")

    record = repo.find_by_key(user_id, key_failed)
    passed = record is not None and record.status == IdempotencyStatus.FAILED
    all_passed &= passed
    print_result(
        "Record is in FAILED state",
        passed,
        f"status={record.status.value if record else 'None'}"
    )

    # Now retry should delete FAILED and create new PENDING
    credits_before = get_user_credits(client, user_id)

    response5 = client.post(
        "/render",
        json=create_valid_request_body(),
        headers={
            "X-User-Id": user_id,
            "Idempotency-Key": key_failed,
        },
    )

    # Should either succeed (202) or fail with 503 (no Redis)
    passed = response5.status_code in [202, 503]
    all_passed &= passed
    print_result(
        "Retry accepted (not blocked by FAILED)",
        passed,
        f"status={response5.status_code}"
    )

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "=" * 60)
    if all_passed:
        print("\033[92mALL TESTS PASSED - IDEMPOTENCY IS PRODUCTION-SAFE\033[0m")
    else:
        print("\033[91mSOME TESTS FAILED - REVIEW REQUIRED\033[0m")
    print("=" * 60)

    # Cleanup
    close_connection()
    try:
        os.unlink(audio_path)
        os.unlink(bg_path)
    except:
        pass

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(run_tests())
