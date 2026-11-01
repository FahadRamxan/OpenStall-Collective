"""Shared test setup: every test runs in fake mode, ignores the developer's .env, and gets fresh fakes.

Fixtures for tests:
- `fakes`: the fake adapters the app is using right now, to queue answers and check what was called.
- `settings`: the settings the app is using in this test.
- `use_settings(**env)`: switch the app to settings made from exactly these environment variables.

Tests marked `@pytest.mark.live` call the real sandboxes and models. They are skipped unless
OPENSTALL_LIVE_TESTS=1, and they run in sandbox mode with the developer's .env, so the keys come from there.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from openstall_agents.adapters import FakeEmbedder, FakeImageSearch, FakeLLM, FakeSpeechToText
from openstall_api.adapters import get_registry, reset_app_state
from openstall_api.db import get_engine, new_session
from openstall_api.messaging import FakeMessenger
from openstall_api.models import Base
from openstall_api.settings import IGNORE_DOTENV, Settings, get_settings
from openstall_paypal.gateway import FakeGateway

pytest_plugins = ["pytester"]


def pytest_configure(config: pytest.Config) -> None:
    # Before any test module imports the app, which reads the settings once, for CORS and the MCP host check.
    os.environ["OPENSTALL_MODE"] = "fake"
    os.environ[IGNORE_DOTENV] = "1"
    config.addinivalue_line("markers", "live: calls real services; runs only with OPENSTALL_LIVE_TESTS=1")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("OPENSTALL_LIVE_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set OPENSTALL_LIVE_TESTS=1 and the keys in .env to run it")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip)


@pytest.fixture
def test_database_url(tmp_path: Path) -> str:
    """A SQLite file of this test's own, so no test touches data/openstall.db or sees another test's rows."""
    return f"sqlite:///{(tmp_path / 'openstall-test.db').as_posix()}"


@pytest.fixture(autouse=True)
def fake_mode(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, test_database_url: str):
    """Fake mode for every test, with fresh fakes and its own database: nothing one test does reaches the next.

    Live tests get sandbox mode and the developer's .env instead (but still their own database).
    """
    if request.node.get_closest_marker("live"):
        monkeypatch.setenv("OPENSTALL_MODE", "sandbox")
        monkeypatch.delenv(IGNORE_DOTENV, raising=False)
    else:
        monkeypatch.setenv("OPENSTALL_MODE", "fake")
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    reset_app_state()
    yield
    reset_app_state()


@pytest.fixture
def db() -> Iterator[Session]:
    """A session on this test's own database, with every table created."""
    Base.metadata.create_all(get_engine())
    with new_session() as session:
        yield session


class Fakes:
    """The fake adapters the app is using right now.

    Each one is looked up when it is used, so after use_settings() a test still sees the fakes the app now uses.
    """

    @property
    def llm(self) -> FakeLLM:
        return get_registry().get("llm")

    @property
    def speech_to_text(self) -> FakeSpeechToText:
        return get_registry().get("speech_to_text")

    @property
    def embedder(self) -> FakeEmbedder:
        return get_registry().get("embedder")

    @property
    def messenger(self) -> FakeMessenger:
        return get_registry().get("messenger")

    @property
    def payment_gateway(self) -> FakeGateway:
        return get_registry().get("payment_gateway")

    @property
    def image_search(self) -> FakeImageSearch:
        return get_registry().get("image_search")


@pytest.fixture
def fakes() -> Fakes:
    """The same fake objects the app uses in this test, whether it reaches them through FastAPI or directly."""
    return Fakes()


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def use_settings(monkeypatch: pytest.MonkeyPatch, test_database_url: str):
    """Switch the app to settings from only the given environment variables, for example
    use_settings(OPENSTALL_MODE="sandbox", ANTHROPIC_API_KEY="made-up"). Anything not given takes its default,
    except DATABASE_URL, which stays on the test's own database unless given."""

    def switch(**env: str) -> Settings:
        for name in Settings.model_fields:
            monkeypatch.delenv(name, raising=False)
        env.setdefault("DATABASE_URL", test_database_url)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        reset_app_state()
        return get_settings()

    return switch
