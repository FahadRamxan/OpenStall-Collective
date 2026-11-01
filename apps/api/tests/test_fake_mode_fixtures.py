"""The shared test setup in conftest.py: fake mode, no developer .env, and fresh fakes in every test."""

import os
import threading
import time
from pathlib import Path

import pytest

from openstall_api import adapters
from openstall_api.adapters import get_registry, reset_app_state
from openstall_api.settings import IGNORE_DOTENV, get_settings

AMINA = "whatsapp:+15550100001"
ROOT_CONFTEST = Path(__file__).resolve().parents[3] / "conftest.py"


def test_tests_run_in_fake_mode_and_ignore_the_developers_env_file(settings):
    assert os.environ["OPENSTALL_MODE"] == "fake"
    assert os.environ[IGNORE_DOTENV] == "1"
    assert settings.OPENSTALL_MODE == "fake"


def test_the_fakes_are_the_ones_the_app_uses(fakes):
    registry = get_registry()

    assert fakes.llm is registry.llm
    assert fakes.speech_to_text is registry.speech_to_text
    assert fakes.embedder is registry.embedder
    assert fakes.messenger is registry.messenger
    assert fakes.payment_gateway is registry.payment_gateway
    assert fakes.image_search is registry.image_search


def test_a_test_sees_what_the_app_did_with_a_fake(fakes):
    get_registry().messenger.send(AMINA, "Hello from the app")

    assert [message.text for message in fakes.messenger.calls] == ["Hello from the app"]


def test_fakes_follow_the_app_after_use_settings(fakes, use_settings):
    use_settings(WEB_BASE_URL="http://localhost:3999")
    get_registry().messenger.send(AMINA, "Sent after the switch")

    assert [message.text for message in fakes.messenger.calls] == ["Sent after the switch"]


def test_reset_app_state_forgets_recorded_calls_and_settings(use_settings, monkeypatch: pytest.MonkeyPatch):
    use_settings(OPENSTALL_MODE="sandbox")
    old = get_registry()

    monkeypatch.setenv("OPENSTALL_MODE", "fake")
    reset_app_state()

    assert get_registry() is not old
    assert get_settings().OPENSTALL_MODE == "fake"


def test_use_settings_switches_the_whole_app(use_settings):
    use_settings(OPENSTALL_MODE="sandbox")

    assert get_settings().OPENSTALL_MODE == "sandbox"
    assert get_registry().settings.OPENSTALL_MODE == "sandbox"


def test_every_test_starts_with_fresh_fakes_and_fake_mode(pytester: pytest.Pytester):
    """Run two tests in their own session, in order: what the first does must not reach the second."""
    pytester.makeconftest(ROOT_CONFTEST.read_text(encoding="utf-8"))
    pytester.makepyfile(
        test_order="""
        from openstall_api.adapters import get_registry

        def test_one_records_a_message_and_switches_to_sandbox(use_settings):
            get_registry().messenger.send("whatsapp:+15550100001", "left behind?")
            use_settings(OPENSTALL_MODE="sandbox")

        def test_two_sees_none_of_it(fakes, settings):
            assert settings.OPENSTALL_MODE == "fake"
            assert fakes.messenger.calls == []
        """
    )

    result = pytester.runpytest_inprocess("-q", "-p", "no:cacheprovider")

    result.assert_outcomes(passed=2)


def test_live_tests_are_skipped_unless_asked_for(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENSTALL_LIVE_TESTS", raising=False)
    pytester.makeconftest(ROOT_CONFTEST.read_text(encoding="utf-8"))
    pytester.makepyfile(
        test_live="""
        import pytest

        @pytest.mark.live
        def test_calls_a_real_sandbox():
            raise AssertionError("must not run without OPENSTALL_LIVE_TESTS=1")
        """
    )

    result = pytester.runpytest_inprocess("-q", "-p", "no:cacheprovider")

    result.assert_outcomes(skipped=1)


def test_concurrent_first_calls_share_one_registry(monkeypatch: pytest.MonkeyPatch):
    class SlowRegistry(adapters.AdapterRegistry):
        def __init__(self, *args, **kwargs):
            time.sleep(0.05)  # widen the window in which overlapping first calls could each build one
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(adapters, "AdapterRegistry", SlowRegistry)
    reset_app_state()
    seen = []
    threads = [threading.Thread(target=lambda: seen.append(get_registry())) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(seen) == 8
    assert len({id(registry) for registry in seen}) == 1
