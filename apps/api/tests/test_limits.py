"""Security and abuse limits (prompt 46): how much one client, and everyone together, may ask of OpenStall; bodies too
large; the security headers; and a refusal recorded once a window, without the client's address."""

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select

from openstall_api import limits
from openstall_api.events import EventType
from openstall_api.limits import LIMITER, LIMITS, Limit, RateLimiter, TooMany, check, client_key, masked
from openstall_api.main import app
from openstall_api.models import Event

AGENT = ("203.0.113.5", 50000)  # TEST-NET-3: an address for documentation, never a real client
client = TestClient(app, client=AGENT)
local = TestClient(app)  # this computer: loopback is not counted


@pytest.fixture(autouse=True)
def fresh_windows():
    LIMITER.reset()
    yield
    LIMITER.reset()


def small(monkeypatch: pytest.MonkeyPatch, name: str, count: int) -> Limit:
    limit = LIMITS[name]
    smaller = Limit(limit.name, count, limit.seconds, limit.what, limit.everyone, limit.sandbox_only)
    monkeypatch.setitem(LIMITS, name, smaller)
    return smaller


def rejections(db) -> list[str]:
    db.expire_all()
    return [
        event.payload_json["summary"]
        for event in db.scalars(select(Event).where(Event.type == EventType.SECURITY_REJECTED.value))
    ]


def test_a_window_lets_its_count_through_then_says_when_to_try_again():
    now = [1000.0]
    limiter = RateLimiter(clock=lambda: now[0])
    limit = Limit("x", 3, 60, "things")

    assert [limiter.hit(limit, "a") for _ in range(3)] == [None, None, None]
    assert limiter.hit(limit, "a") == 60
    assert limiter.hit(limit, "b") is None  # each client has its own window
    now[0] += 30
    assert limiter.hit(limit, "a") == 30
    now[0] += 30.5  # the oldest use has left the window
    assert limiter.hit(limit, "a") is None


def test_the_refusal_says_what_was_limited_and_when_to_try_again():
    assert str(TooMany(LIMITS["mcp"], 12)) == (
        "Too many calls to the MCP storefront: each client may make 120 a minute. Try again in 12 seconds."
    )
    assert str(TooMany(LIMITS["quote"], 600)) == (
        "Too many quote requests, which start the makers' AI agents: OpenStall takes 60 an hour. Try again in 600 "
        "seconds."
    )


def test_a_client_is_its_address_and_behind_a_proxy_the_one_the_proxy_added():
    scope = {"client": ("10.0.0.7", 1), "headers": [(b"x-forwarded-for", b"127.0.0.1, 198.51.100.23")]}

    assert client_key(scope, hops=0) == "10.0.0.7"  # no proxy trusted: the peer
    # One proxy (Render): the entry it added, never one the client wrote, such as a pretend 127.0.0.1.
    assert client_key(scope, hops=1) == "198.51.100.23"
    assert client_key({"client": ("10.0.0.7", 1), "headers": []}, hops=1) == "10.0.0.7"


def test_too_many_stall_orders_from_one_client_get_429_with_retry_after(db, monkeypatch):
    small(monkeypatch, "stall_order", 2)

    answers = [client.post("/api/stall-orders", json={}) for _ in range(3)]

    assert [answer.status_code for answer in answers] == [422, 422, 429]  # two reach the endpoint, the third does not
    refused = answers[-1]
    assert int(refused.headers["retry-after"]) > 0
    assert refused.json()["detail"].startswith("Too many orders from stall pages: each client may make 2 an hour.")
    # The web app can read the refusal: CORS still wraps it.
    assert client.post("/api/stall-orders", json={}, headers={"Origin": "http://localhost:3000"}).headers[
        "access-control-allow-origin"
    ] == "http://localhost:3000"


def test_a_refusal_is_recorded_once_a_window_without_the_address(db, monkeypatch):
    small(monkeypatch, "stall_order", 1)

    for _ in range(4):
        client.post("/api/stall-orders", json={})

    [refusal] = [summary for summary in rejections(db) if summary.startswith("Limit reached")]
    assert refusal == f"Limit reached: more than 1 orders from stall pages from client {masked(AGENT[0])} were refused"
    assert AGENT[0] not in refusal


def test_this_computer_is_not_counted(db, monkeypatch):
    small(monkeypatch, "stall_order", 1)

    assert {local.post("/api/stall-orders", json={}).status_code for _ in range(5)} == {422}


def test_every_request_counts_against_the_api_limit_but_webhooks_do_not(db, monkeypatch):
    small(monkeypatch, "api", 2)

    assert [client.get("/health").status_code for _ in range(4)] == [200, 200, 200, 200]  # /health is not counted
    assert [client.get("/api/searches").status_code for _ in range(3)][-1] == 429
    # PayPal retries what is refused, and every webhook is verified first: never limited.
    assert client.post("/api/webhooks/paypal", content=b"{}").status_code == 400


def test_the_limits_can_be_turned_off(db, use_settings, monkeypatch):
    use_settings(RATE_LIMITS="false")
    small(monkeypatch, "stall_order", 1)

    assert {client.post("/api/stall-orders", json={}).status_code for _ in range(3)} == {422}


def test_a_body_larger_than_the_limit_is_refused_before_it_is_read(db, monkeypatch):
    monkeypatch.setattr(limits, "MAX_BODY_BYTES", 10)

    response = client.post("/api/stall-orders", content=b"x" * 11, headers={"Content-Type": "application/json"})

    assert (response.status_code, response.json()["detail"]) == (413, "The request is too large.")


def test_every_response_says_no_framing_and_no_type_guessing():
    response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


# The limits that protect what real AI services cost: sandbox mode only.


def test_quote_requests_are_limited_for_everyone_together_in_sandbox_mode_only(db, use_settings, monkeypatch):
    small(monkeypatch, "quote", 1)
    for _ in range(3):
        check("quote")  # test mode costs nothing

    use_settings(OPENSTALL_MODE="sandbox")
    check("quote")
    with pytest.raises(TooMany):
        check("quote")


def test_the_storefront_answers_an_agent_over_the_quote_limit_in_words(db, use_settings, monkeypatch):
    from datetime import date
    from decimal import Decimal

    from openstall_api.storefront import _request_quote

    use_settings(OPENSTALL_MODE="sandbox")
    small(monkeypatch, "quote", 0)

    with pytest.raises(ToolError, match="Too many quote requests, which start the makers' AI agents: OpenStall takes 0"):
        _request_quote(["cushion covers"], 40, Decimal("30"), date(2026, 12, 10), "Chicago")


def test_a_buyer_agent_run_over_its_limit_gets_429(db, use_settings, monkeypatch):
    use_settings(OPENSTALL_MODE="sandbox", DEMO_RUN_TOKEN="made-up-demo-token")
    small(monkeypatch, "agent_run", 0)

    response = local.post("/api/demo/run-agent", headers={"X-Demo-Run-Token": "made-up-demo-token"})

    assert response.status_code == 429
    assert response.json()["detail"].startswith("Too many runs of a buyer's AI agent: OpenStall takes 0 an hour.")
    assert int(response.headers["retry-after"]) > 0


def test_a_seller_over_her_message_limit_is_refused_before_anything_is_read(db, use_settings, monkeypatch):
    use_settings(OPENSTALL_MODE="sandbox")
    small(monkeypatch, "chat", 0)

    response = local.post("/api/seller-chat/messages", data={"sender": "demo-phone-0100", "text": "hello"})

    assert response.status_code == 429
    assert response.json()["detail"].startswith("Too many messages from one seller: each client may make 0 every 10")


def test_a_whatsapp_flood_is_dropped_before_any_file_is_fetched(db, use_settings, monkeypatch):
    from openstall_api import whatsapp_api
    from openstall_api.whatsapp import InboundMessage

    use_settings(OPENSTALL_MODE="sandbox")
    small(monkeypatch, "chat", 0)

    def never(*args, **kwargs):
        raise AssertionError("nothing is fetched or read for a sender over her limit")

    monkeypatch.setattr(whatsapp_api, "deliver_inbound", never)
    monkeypatch.setattr(whatsapp_api.httpx, "Client", never)

    whatsapp_api.process_whatsapp_inbound(InboundMessage("SM1", "+923001234567", "Amina", "hello", ()))
