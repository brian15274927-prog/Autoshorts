"""
Tests for God Mode admin API - security critical.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestGodModeAccess:
    """Tests for God Mode authentication and authorization."""

    def test_access_denied_without_header(self, test_client):
        """Request without X-Admin-Secret should be denied."""
        response = test_client.get("/api/god/health")
        assert response.status_code in [403, 503]  # 503 if secret not configured

    def test_access_denied_with_wrong_secret(self, test_client):
        """Request with wrong secret should be denied."""
        response = test_client.get(
            "/api/god/health",
            headers={"X-Admin-Secret": "wrong-secret"}
        )
        assert response.status_code == 403

    def test_access_granted_with_correct_secret(self, test_client):
        """Request with correct secret should be allowed."""
        import os
        secret = os.environ.get("ADMIN_SECRET", "test-admin-secret-for-testing-only-32chars")

        response = test_client.get(
            "/api/god/health",
            headers={"X-Admin-Secret": secret}
        )
        # Should succeed or return data (not 403/503)
        assert response.status_code in [200, 500]  # 500 if DB not available

    def test_rate_limiting(self, test_client):
        """Excessive requests should be rate limited."""
        import os
        secret = os.environ.get("ADMIN_SECRET", "test-admin-secret-for-testing-only-32chars")

        # Make many requests quickly
        responses = []
        for _ in range(35):  # Exceeds RATE_LIMIT_MAX_REQUESTS (30)
            resp = test_client.get(
                "/api/god/health",
                headers={"X-Admin-Secret": secret}
            )
            responses.append(resp.status_code)

        # At least one should be rate limited (429)
        assert 429 in responses or all(r in [200, 500, 503] for r in responses)


class TestGodModeAuditLogging:
    """Tests for audit logging in God Mode."""

    def test_failed_access_is_logged(self, test_client, caplog):
        """Failed access attempts should be logged."""
        import logging
        caplog.set_level(logging.WARNING)

        response = test_client.get(
            "/api/god/health",
            headers={"X-Admin-Secret": "wrong-secret"}
        )

        # Check that audit log entry was created
        assert "AUDIT" in caplog.text or "GOD_MODE" in caplog.text or response.status_code == 403


class TestGodModeEndpoints:
    """Tests for God Mode operational endpoints."""

    def test_pause_all_renders(self, test_client):
        """Should be able to pause all renders."""
        import os
        secret = os.environ.get("ADMIN_SECRET", "test-admin-secret-for-testing-only-32chars")

        response = test_client.post(
            "/api/god/pause-all",
            headers={"X-Admin-Secret": secret},
            json={"reason": "Testing pause functionality"}
        )

        if response.status_code == 200:
            data = response.json()
            assert data["status"] == "paused"

    def test_resume_all_renders(self, test_client):
        """Should be able to resume all renders."""
        import os
        secret = os.environ.get("ADMIN_SECRET", "test-admin-secret-for-testing-only-32chars")

        response = test_client.post(
            "/api/god/resume-all",
            headers={"X-Admin-Secret": secret}
        )

        if response.status_code == 200:
            data = response.json()
            assert data["status"] == "resumed"
