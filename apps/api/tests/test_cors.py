"""CORS: the web app at WEB_BASE_URL may call the API from a browser; other sites may not."""

from fastapi.testclient import TestClient

from openstall_api.main import app
from openstall_api.settings import get_settings

# No `with` block: that would run the app's lifespan, and the MCP session manager can only start once per process.
client = TestClient(app)

OTHER_SITE = "https://not-openstall.example"


def web_app() -> str:
    return get_settings().WEB_BASE_URL


def test_web_app_may_read_api_responses():
    response = client.get("/health", headers={"Origin": web_app()})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == web_app()


def test_preflight_from_web_app_is_allowed():
    response = client.options(
        "/health",
        headers={
            "Origin": web_app(),
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == web_app()
    assert "POST" in response.headers["access-control-allow-methods"]


def test_other_sites_are_refused():
    response = client.get("/health", headers={"Origin": OTHER_SITE})
    assert "access-control-allow-origin" not in response.headers

    preflight = client.options("/health", headers={"Origin": OTHER_SITE, "Access-Control-Request-Method": "GET"})
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers


def test_web_base_url_defaults_to_the_local_web_app(use_settings):
    assert use_settings().WEB_BASE_URL == "http://localhost:3000"


def test_web_base_url_drops_a_trailing_slash(use_settings):
    # Browsers send the Origin header without one, so a trailing slash would never match.
    assert use_settings(WEB_BASE_URL="https://web.example/").WEB_BASE_URL == "https://web.example"
