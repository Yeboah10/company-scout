import os
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("TAVILY_API_KEY", "test-key")
os.environ.setdefault("AUTH_PASSWORD", "test-password")

from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def authed_client(client):
    """A client with a valid session cookie, bypassing the login wall."""
    from backend.services.auth import issue
    token = issue("test@example.com")
    client.cookies.set("scout_session", token)
    return client
