"""
Pytest configuration and fixtures for Autoshorts tests.
"""
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# Set test environment before importing app modules
os.environ["STORAGE_BACKEND"] = "memory"
os.environ["ADMIN_SECRET"] = "test-admin-secret-for-testing-only-32chars"
os.environ["DEBUG"] = "true"


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_openai_key(monkeypatch):
    """Mock OpenAI API key."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-for-testing")


@pytest.fixture
def sample_script():
    """Sample video script for testing."""
    return {
        "title": "Test Video",
        "segments": [
            {
                "text": "This is segment one.",
                "duration": 5.0,
                "visual_keywords": ["nature", "forest"]
            },
            {
                "text": "This is segment two.",
                "duration": 5.0,
                "visual_keywords": ["ocean", "waves"]
            }
        ]
    }


@pytest.fixture
def mock_user():
    """Create a mock user for testing."""
    from app.auth.models import User, Plan
    return User(
        user_id="test-user-123",
        email="test@example.com",
        credits=100,
        plan=Plan.FREE
    )


@pytest.fixture
def mock_unlimited_user():
    """Create a mock user with unlimited credits."""
    from app.auth.models import User, Plan
    return User(
        user_id="test-unlimited-user",
        email="unlimited@example.com",
        credits=0,  # Doesn't matter for unlimited
        plan=Plan.ENTERPRISE
    )


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx client for async HTTP tests."""
    client = AsyncMock()
    client.post = AsyncMock()
    client.get = AsyncMock()
    return client


# FastAPI test client fixture
@pytest.fixture
def test_client():
    """Create a test client for API testing."""
    from fastapi.testclient import TestClient
    from app.api.main import app
    return TestClient(app)


@pytest.fixture
def async_test_client():
    """Create an async test client for API testing."""
    import httpx
    from app.api.main import app
    return httpx.AsyncClient(app=app, base_url="http://test")
