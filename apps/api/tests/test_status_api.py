"""GET /api/status: the mode, the app version and each adapter's state, and never a secret."""

from importlib.metadata import distribution, version

import pytest
import respx
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
PAYPAL_SANDBOX = "https://api-m.sandbox.paypal.com"


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

    # In sandbox mode the status asks PayPal for a token; PayPal refuses the made-up keys, in its own words.
    with respx.mock(base_url=PAYPAL_SANDBOX, assert_all_called=False) as paypal:
        paypal.post("/v1/oauth2/token").respond(
            401, json={"error": "invalid_client", "error_description": "Client Authentication failed"}
        )
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


# ---------- the database ----------

TABLES = [
    "chat_messages",
    "chat_sessions",
    "events",
    "offers",
    "order_parts",
    "orders",
    "passports",
    "paypal_claims",
    "processed_webhooks",
    "products",
    "quote_requests",
    "searches",
    "sellers",
]


def test_the_database_is_reported_ok_with_rows_per_table(db):
    from openstall_api.models import Seller

    db.add(Seller(id="s_amina", name="Amina"))
    db.commit()

    database = get_status()["database"]

    assert database["status"] == "ok"
    assert sorted(database["tables"]) == TABLES
    assert database["tables"]["sellers"] == 1
    assert database["tables"]["orders"] == 0
    assert database["message"] is None


def test_a_database_without_its_tables_is_reported_as_not_migrated():
    database = get_status()["database"]

    assert database["status"] == "not migrated"
    assert database["tables"] == {}
    assert "alembic upgrade head" in database["message"]


def test_an_unreachable_database_is_reported_without_its_address_or_password(use_settings):
    use_settings(DATABASE_URL="postgresql://openstall:db-pw-c41d@db.unreachable.invalid:5432/openstall")

    response = client.get("/api/status")

    assert response.status_code == 200
    database = response.json()["database"]
    assert database["status"] == "error"
    assert "could not be reached" in database["message"]
    assert "db-pw-c41d" not in response.text
    assert "unreachable.invalid" not in response.text


def test_paypal_is_the_simulated_page_in_fake_mode():
    assert get_status()["payment"] == {
        "status": "fake",
        "path": "payouts",
        "message": "Checkout runs on the simulated PayPal page. Nothing reaches PayPal.",
        "sdk": None,  # the simulated gateway uses no SDK
    }


def test_in_sandbox_mode_paypal_names_the_sdk_the_gateway_calls_it_with(use_settings):
    use_settings(OPENSTALL_MODE="sandbox")

    sdk = get_status()["payment"]["sdk"]

    installed = distribution("paypal")
    assert sdk["distribution"] == "paypal"
    assert sdk["version"] == installed.version
    assert sdk["label"] == f"APIMatic PayPal Python SDK {installed.version}"
    assert sdk["commit"] == "143e57f"  # pyproject.toml pins the SDK to this commit


def test_paypal_without_its_keys_names_them(use_settings):
    use_settings(OPENSTALL_MODE="sandbox", PAYMENT_PATH="multiparty")

    payment = get_status()["payment"]

    assert payment["status"] == "missing key"
    assert payment["path"] == "multiparty"
    assert payment["message"] == "Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET to reach the PayPal sandbox."


def test_paypal_with_its_keys_is_asked_for_a_token_and_the_token_is_kept(use_settings):
    use_settings(OPENSTALL_MODE="sandbox", PAYPAL_CLIENT_ID="made-up-id", PAYPAL_CLIENT_SECRET="made-up-secret")

    with respx.mock(base_url=PAYPAL_SANDBOX) as paypal:
        token = paypal.post("/v1/oauth2/token").respond(json={"access_token": "TOKEN", "expires_in": 32400})
        first, second = get_status()["payment"], get_status()["payment"]

    assert first["status"] == second["status"] == "token ok"
    assert token.call_count == 1


def test_paypal_refusing_the_keys_is_reported_in_its_own_words(use_settings):
    use_settings(OPENSTALL_MODE="sandbox", PAYPAL_CLIENT_ID="wrong-id", PAYPAL_CLIENT_SECRET="wrong-secret")

    with respx.mock(base_url=PAYPAL_SANDBOX) as paypal:
        paypal.post("/v1/oauth2/token").respond(
            401, json={"error": "invalid_client", "error_description": "Client Authentication failed"}
        )
        payment = get_status()["payment"]

    assert payment["status"] == "failed"
    assert payment["message"] == "PayPal gave no token: Client Authentication failed"


def test_on_render_the_status_names_the_deployed_commit(monkeypatch):
    assert get_status()["commit"] is None

    monkeypatch.setenv("RENDER_GIT_COMMIT", "8f3fec3a1b2c4d5e6f708192a3b4c5d6e7f80912")

    assert get_status()["commit"] == "8f3fec3a1b2c4d5e6f708192a3b4c5d6e7f80912"
