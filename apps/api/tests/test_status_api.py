"""GET /api/status: the mode, the app version and each adapter's state, and never a secret."""

from importlib.metadata import version

import pytest
from fastapi.testclient import TestClient

from openstall_api import __version__
from openstall_api.main import app
from openstall_api.settings import get_settings

# No `with` block: that would run the app's lifespan, and the MCP session manager can only start once per process.
client = TestClient(app)

ALL_ADAPTERS = ["llm", "speech_to_text", "embedder", "messenger", "payment_gateway", "image_search"]

# A made-up value for every setting that is secret or names an account. None may ever appear in the response.
MADE_UP_SECRETS = {
    "PAYPAL_CLIENT_ID": "made-up-paypal-client-id-3f9a",
    "PAYPAL_CLIENT_SECRET": "made-up-paypal-secret-71c2",
    "PAYPAL_WEBHOOK_ID": "made-up-webhook-id-0d4e",
    "TWILIO_ACCOUNT_SID": "ACmadeup5b8f",
    "TWILIO_AUTH_TOKEN": "made-up-twilio-token-9e1d",
    "ANTHROPIC_API_KEY": "sk-ant-made-up-4c7b",
    "OPENAI_API_KEY": "sk-made-up-openai-2a6f",
    "GOOGLE_VISION_API_KEY": "made-up-vision-key-8b3c",
    "PASSPORT_SIGNING_KEY": "bWFkZS11cC1zaWduaW5nLWtleS0xZTc=",
    "DATABASE_URL": "postgresql://openstall:made-up-db-password-6d2a@db.example:5432/openstall",
}
DATABASE_PASSWORD = "made-up-db-password-6d2a"


def get_status() -> dict:
    response = client.get("/api/status")
    assert response.status_code == 200
    return response.json()


def adapters_by_name(status: dict) -> dict[str, dict]:
    return {adapter["name"]: adapter for adapter in status["adapters"]}


def test_fake_mode_reports_every_adapter_as_fake():
    status = get_status()

    assert status["mode"] == "fake"
    assert status["version"] == __version__ == version("openstall")
    assert [adapter["name"] for adapter in status["adapters"]] == ALL_ADAPTERS
    assert {adapter["status"] for adapter in status["adapters"]} == {"fake"}
    assert all(adapter["missing_keys"] == [] for adapter in status["adapters"])


def test_each_adapter_says_what_it_is_for_and_what_the_real_service_needs():
    messenger = adapters_by_name(get_status())["messenger"]

    assert messenger["label"] == "Messenger"
    assert messenger["purpose"] == "Sends WhatsApp messages to sellers."
    assert messenger["service"] == "Twilio WhatsApp sandbox"
    assert messenger["keys"] == ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"]


def test_sandbox_mode_with_missing_keys_reports_missing_key(use_settings):
    use_settings(OPENSTALL_MODE="sandbox", TWILIO_ACCOUNT_SID="ACmadeup5b8f")

    status = get_status()

    assert status["mode"] == "sandbox"
    adapters = adapters_by_name(status)
    assert {adapter["status"] for adapter in adapters.values()} == {"missing key"}
    assert adapters["messenger"]["missing_keys"] == ["TWILIO_AUTH_TOKEN"]
    assert adapters["llm"]["missing_keys"] == ["ANTHROPIC_API_KEY"]


def test_sandbox_mode_with_a_key_but_no_real_adapter_says_not_built(use_settings):
    use_settings(OPENSTALL_MODE="sandbox", ANTHROPIC_API_KEY="sk-ant-made-up-4c7b")

    adapters = adapters_by_name(get_status())

    assert adapters["llm"]["status"] == "not built"
    assert adapters["llm"]["missing_keys"] == []
    assert adapters["messenger"]["status"] == "missing key"


@pytest.mark.parametrize("mode", ["fake", "sandbox"])
def test_status_never_contains_a_secret(use_settings, mode):
    use_settings(OPENSTALL_MODE=mode, **MADE_UP_SECRETS)

    response = client.get("/api/status")

    assert response.status_code == 200
    everything = response.text + "\n".join(f"{name}: {value}" for name, value in response.headers.items())
    for name, value in MADE_UP_SECRETS.items():
        assert value not in everything, f"the value of {name} is in /api/status"
    assert DATABASE_PASSWORD not in everything


def test_status_is_never_cached():
    assert client.get("/api/status").headers["cache-control"] == "no-store"


def test_the_web_app_may_read_the_status_from_the_browser():
    web_app = get_settings().WEB_BASE_URL

    response = client.get("/api/status", headers={"Origin": web_app})

    assert response.headers["access-control-allow-origin"] == web_app
