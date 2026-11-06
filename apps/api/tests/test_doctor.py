"""The PayPal doctor (prompt 53): GET /api/paypal/doctor and scripts/doctor.py say whether this setup is ready to hold
a buyer's money and pay makers, check by check, with the PayPal products table, and never show a key."""

import importlib.util
import json
from pathlib import Path

import respx
from fastapi.testclient import TestClient

from openstall_api.main import app
from openstall_api.webhooks import SUBSCRIBED_EVENTS
from openstall_paypal.products import PRODUCTS

# No `with` block: that would run the app's lifespan, and the MCP session manager can only start once per process.
client = TestClient(app)

PAYPAL_SANDBOX = "https://api-m.sandbox.paypal.com"
KEYS = {"PAYPAL_CLIENT_ID": "made-up-doctor-id-5d1e", "PAYPAL_CLIENT_SECRET": "made-up-doctor-secret-8c3a"}
PAYEES = {
    "PAYPAL_SANDBOX_PAYEE_PRIYA": "priya-made-up@personal.example.com",
    "PAYPAL_SANDBOX_PAYEE_LUCIA": "lucia-made-up@personal.example.com",
    "PAYPAL_SANDBOX_PAYEE_NOOR": "noor-made-up@personal.example.com",
}
WEBHOOK_ID = "WH-MADE-UP-7K2"
HOOK_URL = "https://openstall.example/api/webhooks/paypal"


def doctor() -> dict:
    response = client.get("/api/paypal/doctor")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def statuses(report: dict) -> dict[str, tuple[str, str]]:
    return {check["name"]: (check["status"], check["detail"]) for check in report["checks"]}


def test_in_test_mode_nothing_reaches_paypal_and_the_sdk_is_cross_checked():
    with respx.mock(assert_all_called=False) as anything:  # nothing may be sent anywhere
        report = doctor()
    assert not anything.calls

    assert (report["mode"], report["healthy"]) == ("fake", True)
    checks = statuses(report)
    assert checks["Where the money goes"] == (
        "ok",
        "Test mode: a simulated PayPal. Nothing reaches PayPal and no money moves.",
    )
    assert checks["PayPal keys and token"][0] == checks["PayPal webhook"][0] == "skip"
    assert checks["Makers' payout accounts"][0] == "ok"
    cross = [name for name in checks if name.startswith("APIMatic cross-check: ")]
    assert len(cross) == 4 and {checks[name][0] for name in cross} == {"ok"}


def test_the_products_table_comes_with_the_report():
    products = doctor()["products"]

    assert [product["key"] for product in products] == [product.key for product in PRODUCTS]
    by_key = {product["key"]: product for product in products}
    assert (by_key["orders"]["state"], by_key["orders"]["state_words"]) == ("proven", "Proven on the sandbox")
    assert by_key["hyperwallet"]["state_words"] == "Simulated"
    assert by_key["disputes"]["state_words"] == "Not built yet"
    assert by_key["tracking"]["calls"] == ["POST /v2/checkout/orders/{id}/track"]


def test_sandbox_mode_without_keys_fails_and_names_them(use_settings):
    use_settings(OPENSTALL_MODE="sandbox")

    report = doctor()

    assert report["healthy"] is False
    assert statuses(report)["PayPal keys and token"] == (
        "fail",
        "Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env.",
    )
    assert statuses(report)["PayPal webhook"][0] == "warn"  # no PAYPAL_WEBHOOK_ID either


def test_sandbox_mode_reads_the_webhook_back_and_finds_it_complete(use_settings):
    use_settings(
        OPENSTALL_MODE="sandbox",
        PAYPAL_WEBHOOK_ID=WEBHOOK_ID,
        PUBLIC_BASE_URL="https://openstall.example",
        **KEYS,
        **PAYEES,
    )
    with respx.mock(base_url=PAYPAL_SANDBOX) as paypal:
        paypal.post("/v1/oauth2/token").respond(json={"access_token": "TOKEN", "expires_in": 32400})
        hook = paypal.get(f"/v1/notifications/webhooks/{WEBHOOK_ID}").respond(
            json={"id": WEBHOOK_ID, "url": HOOK_URL, "event_types": [{"name": name} for name in SUBSCRIBED_EVENTS]}
        )
        report = doctor()

    assert hook.called
    assert report["healthy"] is True
    checks = statuses(report)
    assert checks["Where the money goes"] == ("ok", f"PayPal's sandbox ({PAYPAL_SANDBOX}): no real money moves.")
    assert checks["PayPal keys and token"] == ("ok", "PayPal gave a token for the app's client id.")
    assert checks["PayPal webhook"] == (
        "ok",
        f"Webhook {WEBHOOK_ID} sends every event OpenStall needs (9) to {HOOK_URL}.",
    )
    assert checks["Makers' payout accounts"][0] == "ok"


def test_a_webhook_missing_events_or_pointing_elsewhere_is_a_warning(use_settings):
    use_settings(OPENSTALL_MODE="sandbox", PAYPAL_WEBHOOK_ID=WEBHOOK_ID, PUBLIC_BASE_URL="https://openstall.example", **KEYS)
    with respx.mock(base_url=PAYPAL_SANDBOX) as paypal:
        paypal.post("/v1/oauth2/token").respond(json={"access_token": "TOKEN", "expires_in": 32400})
        paypal.get(f"/v1/notifications/webhooks/{WEBHOOK_ID}").respond(
            json={
                "id": WEBHOOK_ID,
                "url": "https://old.example/api/webhooks/paypal",
                "event_types": [{"name": name} for name in SUBSCRIBED_EVENTS if not name.startswith("PAYMENT.PAYOUTS")],
            }
        )
        status, detail = statuses(doctor())["PayPal webhook"]

    assert status == "warn"
    assert detail == (
        f"Webhook {WEBHOOK_ID}: it sends events to https://old.example/api/webhooks/paypal, not {HOOK_URL}; it is not "
        "subscribed to PAYMENT.PAYOUTSBATCH.SUCCESS, PAYMENT.PAYOUTS-ITEM.SUCCEEDED, PAYMENT.PAYOUTS-ITEM.FAILED."
    )


def test_a_webhook_for_every_event_counts_as_complete(use_settings):
    use_settings(OPENSTALL_MODE="sandbox", PAYPAL_WEBHOOK_ID=WEBHOOK_ID, PUBLIC_BASE_URL="https://openstall.example", **KEYS)
    with respx.mock(base_url=PAYPAL_SANDBOX) as paypal:
        paypal.post("/v1/oauth2/token").respond(json={"access_token": "TOKEN", "expires_in": 32400})
        paypal.get(f"/v1/notifications/webhooks/{WEBHOOK_ID}").respond(
            json={"id": WEBHOOK_ID, "url": HOOK_URL, "event_types": [{"name": "*"}]}
        )
        assert statuses(doctor())["PayPal webhook"][0] == "ok"


def test_a_webhook_paypal_does_not_know_fails(use_settings):
    use_settings(OPENSTALL_MODE="sandbox", PAYPAL_WEBHOOK_ID=WEBHOOK_ID, **KEYS)
    with respx.mock(base_url=PAYPAL_SANDBOX) as paypal:
        paypal.post("/v1/oauth2/token").respond(json={"access_token": "TOKEN", "expires_in": 32400})
        paypal.get(f"/v1/notifications/webhooks/{WEBHOOK_ID}").respond(
            404, json={"name": "INVALID_RESOURCE_ID", "message": "Webhook not found.", "debug_id": "d1"}
        )
        report = doctor()

    status, detail = statuses(report)["PayPal webhook"]
    assert (status, report["healthy"]) == ("fail", False)
    assert detail.startswith(f"PayPal could not show webhook {WEBHOOK_ID}: ")


def test_paypal_refusing_the_keys_fails_and_skips_the_webhook(use_settings):
    use_settings(OPENSTALL_MODE="sandbox", PAYPAL_WEBHOOK_ID=WEBHOOK_ID, **KEYS)
    with respx.mock(base_url=PAYPAL_SANDBOX) as paypal:
        paypal.post("/v1/oauth2/token").respond(
            401, json={"error": "invalid_client", "error_description": "Client Authentication failed"}
        )
        checks = statuses(doctor())

    assert checks["PayPal keys and token"] == ("fail", "PayPal gave no token: Client Authentication failed")
    assert checks["PayPal webhook"] == ("skip", "Needs a PayPal token first.")


def test_paypal_s_live_host_is_a_warning(use_settings):
    use_settings(OPENSTALL_MODE="sandbox", PAYPAL_API_BASE="https://api-m.paypal.com")

    status, detail = statuses(doctor())["Where the money goes"]

    assert status == "warn"
    assert detail.startswith("https://api-m.paypal.com is PayPal's live host, where money is real.")


def test_the_makers_without_a_sandbox_account_are_named(use_settings):
    use_settings(OPENSTALL_MODE="sandbox", PAYPAL_SANDBOX_PAYEE_LUCIA=PAYEES["PAYPAL_SANDBOX_PAYEE_LUCIA"])

    status, detail = statuses(doctor())["Makers' payout accounts"]

    assert status == "warn"
    assert detail.startswith(
        "No sandbox PayPal account for Priya, Noor, so their shares are not captured in sandbox mode: set "
        "PAYPAL_SANDBOX_PAYEE_PRIYA, PAYPAL_SANDBOX_PAYEE_NOOR."
    )


def test_the_report_never_shows_a_key_or_an_account(use_settings):
    use_settings(OPENSTALL_MODE="sandbox", PAYPAL_WEBHOOK_ID=WEBHOOK_ID, **KEYS, **PAYEES)
    with respx.mock(base_url=PAYPAL_SANDBOX, assert_all_called=False) as paypal:
        paypal.post("/v1/oauth2/token").respond(json={"access_token": "TOKEN-NEVER-SHOWN", "expires_in": 32400})
        paypal.get(f"/v1/notifications/webhooks/{WEBHOOK_ID}").respond(json={"id": WEBHOOK_ID, "event_types": []})
        body = json.dumps(doctor())

    for secret in [*KEYS.values(), *PAYEES.values(), "TOKEN-NEVER-SHOWN"]:
        assert secret not in body


def test_the_script_prints_the_report_and_fails_only_on_a_failed_check(use_settings, capsys):
    script = Path(__file__).resolve().parents[3] / "scripts" / "doctor.py"
    spec = importlib.util.spec_from_file_location("doctor_script", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    main = module.main

    use_settings(OPENSTALL_MODE="fake")
    assert main([]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith("PayPal doctor, fake mode\n")
    assert "  ok    APIMatic cross-check: The installed SDK has every planned operation:" in printed
    assert "  Hyperwallet" in printed and "Nothing failed." in printed

    use_settings(OPENSTALL_MODE="sandbox")
    assert main(["--checks"]) == 1
    printed = capsys.readouterr().out
    assert "  FAIL  PayPal keys and token: Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env." in printed
    assert "PayPal products" not in printed
    assert printed.rstrip().endswith("Failed: PayPal keys and token")
