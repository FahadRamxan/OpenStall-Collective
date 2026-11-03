"""PayPalClient: the token is cached and renewed, every write carries its idempotency key, errors are typed and
logged with PayPal's debug id, and nothing is retried except the token. PayPal is mocked with respx."""

import json
import logging

import httpx
import pytest
import respx

from openstall_paypal.client import (
    TOKEN_MARGIN_SECONDS,
    PayPalAuthError,
    PayPalClient,
    PayPalNotFound,
    PayPalUnavailable,
    PayPalValidationError,
)

BASE = "https://api-m.sandbox.paypal.com"
TOKEN_LIFE = 32_400  # what PayPal gives, in seconds


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def paypal():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.post("/v1/oauth2/token", name="token").mock(
            side_effect=[
                httpx.Response(200, json={"access_token": f"TOKEN-{n}", "expires_in": TOKEN_LIFE}) for n in range(1, 4)
            ]
        )
        yield router


@pytest.fixture
def client(clock: Clock) -> PayPalClient:
    return PayPalClient(BASE, "made-up-client-id", "made-up-secret", clock=clock)


def test_a_token_is_fetched_once_and_reused(paypal, client):
    orders = paypal.get("/v2/checkout/orders/ORDER-1").respond(json={"id": "ORDER-1"})

    client.get("/v2/checkout/orders/ORDER-1")
    client.get("/v2/checkout/orders/ORDER-1")

    assert paypal["token"].call_count == 1
    token_request = paypal["token"].calls.last.request
    assert token_request.headers["Authorization"].startswith("Basic ")  # the client id and secret, never a bearer
    assert token_request.content == b"grant_type=client_credentials"
    assert [call.request.headers["Authorization"] for call in orders.calls] == ["Bearer TOKEN-1"] * 2


def test_the_token_is_renewed_shortly_before_paypal_says_it_expires(paypal, client, clock):
    paypal.get("/v1/ping").respond(json={})
    client.get("/v1/ping")

    clock.now += TOKEN_LIFE - TOKEN_MARGIN_SECONDS - 1
    client.get("/v1/ping")
    assert paypal["token"].call_count == 1

    clock.now += 2
    client.get("/v1/ping")
    assert paypal["token"].call_count == 2


def test_a_refused_token_gets_one_fresh_token_and_one_retry(paypal, client):
    route = paypal.get("/v1/ping").mock(side_effect=[httpx.Response(401), httpx.Response(200, json={"ok": True})])

    assert client.get("/v1/ping") == {"ok": True}
    assert paypal["token"].call_count == 2
    assert [call.request.headers["Authorization"] for call in route.calls] == ["Bearer TOKEN-1", "Bearer TOKEN-2"]


def test_a_token_refused_twice_is_an_auth_error(paypal, client):
    paypal.get("/v1/ping").respond(401, json={"name": "AUTHENTICATION_FAILURE", "message": "Token is not valid"})

    with pytest.raises(PayPalAuthError, match="Token is not valid"):
        client.get("/v1/ping")
    assert paypal["token"].call_count == 2


def test_wrong_credentials_are_an_auth_error_from_paypals_own_words(clock):
    with respx.mock(base_url=BASE) as router:
        router.post("/v1/oauth2/token").respond(
            401, json={"error": "invalid_client", "error_description": "Client Authentication failed"}
        )

        with pytest.raises(PayPalAuthError, match="Client Authentication failed") as error:
            PayPalClient(BASE, "wrong-id", "wrong-secret", clock=clock).token()

    assert error.value.issue == "invalid_client"


def test_every_write_sends_its_idempotency_key_and_reads_send_none(paypal, client):
    write = paypal.post("/v2/checkout/orders").respond(201, json={"id": "ORDER-1"})
    read = paypal.get("/v2/checkout/orders/ORDER-1").respond(json={"id": "ORDER-1"})

    client.post("/v2/checkout/orders", {"intent": "AUTHORIZE"}, idempotency_key="openstall-checkout-ord_1")
    client.get("/v2/checkout/orders/ORDER-1")

    sent = write.calls.last.request
    assert sent.headers["PayPal-Request-Id"] == "openstall-checkout-ord_1"
    assert sent.headers["Prefer"] == "return=representation"
    assert json.loads(sent.content) == {"intent": "AUTHORIZE"}
    assert "PayPal-Request-Id" not in read.calls.last.request.headers


def test_a_422_carries_paypals_issue_and_details(paypal, client):
    details = [{"field": "/purchase_units/0/amount/value", "issue": "DECIMAL_PRECISION", "description": "Too many"}]
    paypal.post("/v2/checkout/orders").respond(
        422,
        json={"name": "UNPROCESSABLE_ENTITY", "message": "The requested action could not be performed.", "details": details},
        headers={"Paypal-Debug-Id": "f00dcafe1234"},
    )

    with pytest.raises(PayPalValidationError) as error:
        client.post("/v2/checkout/orders", {}, idempotency_key="key-1")

    assert error.value.status == 422
    assert error.value.issue == "DECIMAL_PRECISION"
    assert error.value.details == details
    assert error.value.debug_id == "f00dcafe1234"


def test_the_debug_id_is_logged_with_every_error(paypal, client, caplog):
    paypal.get("/v2/checkout/orders/NOPE").respond(
        404, json={"name": "RESOURCE_NOT_FOUND", "message": "Not found"}, headers={"Paypal-Debug-Id": "abc123debug"}
    )

    with caplog.at_level(logging.WARNING, logger="openstall_paypal.client"), pytest.raises(PayPalNotFound):
        client.get("/v2/checkout/orders/NOPE")

    assert "abc123debug" in caplog.text
    assert "/v2/checkout/orders/NOPE" in caplog.text
    assert "made-up-secret" not in caplog.text


def test_a_network_error_on_a_write_is_not_retried(paypal, client):
    route = paypal.post("/v2/checkout/orders/ORDER-1/authorize").mock(side_effect=httpx.ConnectTimeout("slow"))

    with pytest.raises(PayPalUnavailable, match="could not be reached"):
        client.post("/v2/checkout/orders/ORDER-1/authorize", {}, idempotency_key="key-1")

    assert route.call_count == 1


def test_a_server_error_is_unavailable_and_not_retried(paypal, client):
    route = paypal.post("/v1/payments/payouts").respond(503, json={"name": "SERVICE_UNAVAILABLE"})

    with pytest.raises(PayPalUnavailable) as error:
        client.post("/v1/payments/payouts", {}, idempotency_key="key-1")

    assert error.value.issue == "SERVICE_UNAVAILABLE"
    assert route.call_count == 1


def test_an_empty_answer_reads_as_an_empty_body(paypal, client):
    paypal.post("/v2/payments/authorizations/AUTH-1/void").respond(204)

    assert client.post("/v2/payments/authorizations/AUTH-1/void", None, idempotency_key="key-1") == {}


@pytest.mark.live
def test_the_real_sandbox_gives_us_a_token(settings):
    client = PayPalClient(
        settings.PAYPAL_API_BASE, settings.PAYPAL_CLIENT_ID or "", settings.PAYPAL_CLIENT_SECRET.get_secret_value()
    )

    assert client.token()
