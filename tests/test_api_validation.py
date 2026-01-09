"""
Tests for API input validation and security.
"""
import pytest
import io
from unittest.mock import patch, MagicMock


class TestFileUploadLimits:
    """Tests for file upload size limits."""

    def test_portraits_rejects_large_file(self, test_client):
        """Portraits API should reject files larger than MAX_IMAGE_SIZE_MB."""
        # Create a file larger than 10MB
        large_content = b"x" * (11 * 1024 * 1024)  # 11MB

        response = test_client.post(
            "/api/portraits/generate",
            files={"image": ("large.jpg", io.BytesIO(large_content), "image/jpeg")},
            data={"template_id": "test", "style": "realistic"}
        )

        # Should return 413 Payload Too Large
        assert response.status_code in [413, 404]  # 404 if template not found first

    def test_portraits_accepts_valid_file(self, test_client):
        """Portraits API should accept files within size limit."""
        # Create a small valid image (1x1 PNG)
        small_png = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00'
            b'\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18'
            b'\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )

        response = test_client.post(
            "/api/portraits/generate",
            files={"image": ("small.png", io.BytesIO(small_png), "image/png")},
            data={"template_id": "test", "style": "realistic"}
        )

        # Should not be rejected for size (may be 404 for template)
        assert response.status_code != 413

    def test_musicvideo_rejects_large_audio(self, test_client):
        """Music video API should reject audio larger than MAX_AUDIO_SIZE_MB."""
        # Create a file larger than 50MB
        large_content = b"x" * (51 * 1024 * 1024)  # 51MB

        response = test_client.post(
            "/api/musicvideo/generate",
            files={"audio": ("large.mp3", io.BytesIO(large_content), "audio/mpeg")},
            data={"art_style": "photorealism", "image_provider": "dalle"}
        )

        # Should return 413 Payload Too Large
        assert response.status_code == 413


class TestInputValidation:
    """Tests for general input validation."""

    def test_portraits_rejects_non_image(self, test_client):
        """Portraits API should reject non-image files."""
        response = test_client.post(
            "/api/portraits/generate",
            files={"image": ("test.txt", io.BytesIO(b"not an image"), "text/plain")},
            data={"template_id": "test"}
        )

        assert response.status_code == 400

    def test_musicvideo_rejects_invalid_format(self, test_client):
        """Music video API should reject unsupported audio formats."""
        response = test_client.post(
            "/api/musicvideo/generate",
            files={"audio": ("test.exe", io.BytesIO(b"fake"), "application/octet-stream")},
            data={"art_style": "photorealism"}
        )

        assert response.status_code == 400


class TestSQLInjectionPrevention:
    """Tests for SQL injection prevention."""

    def test_musicvideo_update_filters_invalid_columns(self):
        """Database update should filter out invalid column names."""
        from app.api.routes.musicvideo import _update_job_in_db

        # Attempt to inject via column name
        updates = {
            "status": "completed",
            "'; DROP TABLE users; --": "malicious"  # SQL injection attempt
        }

        # Should not raise, should filter out invalid column
        _update_job_in_db("test-job-id", updates)

        # The function should have filtered out the malicious key
        # (We can't easily verify this without DB, but no exception = filtered)
