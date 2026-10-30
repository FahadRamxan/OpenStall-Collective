"""CORS: the web app at WEB_BASE_URL may call the API from a browser; other sites may not."""

import importlib

import dotenv
import pytest
from fastapi.testclient import TestClient

from openstall_api import settings
from openstall_api.main import app

# No `with` block: that would run the app's lifespan, and the MCP session manager can only start once per process.
client = TestClient(app)

OTHER_SITE = "https://not-openstall.example"


def test_web_app_may_read_api_responses():
    response = client.get("/health", headers={"Origin": settings.WEB_BASE_URL})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == settings.WEB_BASE_URL


def test_preflight_from_web_app_is_allowed():
    response = client.options(
        "/health",
        headers={
            "Origin": settings.WEB_BASE_URL,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == settings.WEB_BASE_URL
    assert "POST" in response.headers["access-control-allow-methods"]


def test_other_sites_are_refused():
    response = client.get("/health", headers={"Origin": OTHER_SITE})
    assert "access-control-allow-origin" not in response.headers

    preflight = client.options("/health", headers={"Origin": OTHER_SITE, "Access-Control-Request-Method": "GET"})
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers


@pytest.fixture
def reload_settings(monkeypatch):
    """Re-read settings from a controlled environment, then restore the real ones."""
    # Ignore a developer's .env, so the test sees only the environment set here.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)

    def reload(**env: str | None):
        for name, value in env.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        return importlib.reload(settings)

    yield reload
    monkeypatch.undo()
    importlib.reload(settings)


def test_web_base_url_defaults_to_the_local_web_app(reload_settings):
    assert reload_settings(WEB_BASE_URL=None).WEB_BASE_URL == "http://localhost:3000"


def test_web_base_url_drops_a_trailing_slash(reload_settings):
    # Browsers send the Origin header without one, so a trailing slash would never match.
    assert reload_settings(WEB_BASE_URL="https://web.example/").WEB_BASE_URL == "https://web.example"
