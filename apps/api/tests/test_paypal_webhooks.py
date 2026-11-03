"""PayPal webhooks (spec 3.5 and section 7): only verified events count, each counts once, and they confirm each
reservation, payment and release, whatever order they arrive in."""

import json
from datetime import date

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import Event, Order, OrderPart, PartStatus, ProcessedWebhook
from openstall_api.payments import reserve_order, start_checkout
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order
from openstall_paypal import fake_event, sign_fake_webhook

client = TestClient(app)
PAYPAL = "https://api-m.sandbox.paypal.com"


def post_event(event: dict, *, headers: dict | None = None, raw: bytes | None = None):
    raw = raw if raw is not None else json.dumps(event).encode()
    headers = sign_fake_webhook(raw) if headers is None else headers
    return client.post("/api/webhooks/paypal", content=raw, headers={**headers, "Content-Type": "application/json"})


def feed(db, kind: EventType) -> list[str]:
    db.expire_all()
    return [event.payload_json["summary"] for event in db.scalars(select(Event).where(Event.type == kind))]


def order(order_id: str = DEMO_ORDER_ID) -> dict:
    return client.get(f"/api/orders/{order_id}").json()


@pytest.fixture
def demo_order(db):
    seed(db, with_amina=True)
    seed_demo_order(db, date(2026, 11, 10))
    db.commit()
    return db


@pytest.fixture
def reserved_quietly(demo_order, fakes, settings):
    """The demo order reserved through the services, with PayPal's webhooks held back, so a test sends them itself."""
    checkout = start_checkout(demo_order, DEMO_ORDER_ID, fakes.payment_gateway, settings.WEB_BASE_URL)
    fakes.payment_gateway.approve(checkout.paypal_order_id)
    reserve_order(demo_order, DEMO_ORDER_ID, fakes.payment_gateway)
    demo_order.commit()
    fakes.payment_gateway.take_outbox()
    return {part.seller_id: part for part in demo_order.get(Order, DEMO_ORDER_ID).parts}


def test_the_whole_fake_flow_ends_with_every_share_confirmed_by_paypal(demo_order):
    token = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve").status_code == 200

    parts = order()["parts"]

    assert [(part["status"], part["confirmed_by_paypal"]) for part in parts] == [("authorized", True)] * 4
    assert feed(demo_order, EventType.PAYMENT_WEBHOOK) == [
        "PayPal confirmed the buyer approved order ord_demo",
        "PayPal confirmed the money for Amina is reserved",
        "PayPal confirmed the money for Priya is reserved",
        "PayPal confirmed the money for Lucía is reserved",
        "PayPal confirmed the money for Grace is reserved",
    ]


def test_a_share_is_not_confirmed_until_paypal_says_so(reserved_quietly):
    assert [part["confirmed_by_paypal"] for part in order()["parts"]] == [False] * 4

    amina = reserved_quietly["s_amina"]
    post_event(
        fake_event("PAYMENT.AUTHORIZATION.CREATED", "authorization", {"id": amina.authorization_id}, "Authorized")
    )

    assert [part["confirmed_by_paypal"] for part in order()["parts"]] == [True, False, False, False]


def test_an_event_without_paypals_signature_is_refused_and_recorded(demo_order):
    event = fake_event("PAYMENT.CAPTURE.COMPLETED", "capture", {"id": "CAP-1"}, "Captured")

    response = post_event(event, headers={"PAYPAL-TRANSMISSION-ID": "made-up", "PAYPAL-TRANSMISSION-SIG": "made-up"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Refused: PayPal did not sign this event."
    assert demo_order.scalar(select(func.count()).select_from(ProcessedWebhook)) == 0
    assert feed(demo_order, EventType.SECURITY_REJECTED) == ["A PayPal webhook failed verification and was refused"]


def test_an_event_changed_after_it_was_signed_is_refused(demo_order):
    raw = json.dumps(fake_event("PAYMENT.CAPTURE.COMPLETED", "capture", {"id": "CAP-1"}, "Captured")).encode()
    headers = sign_fake_webhook(raw)

    response = post_event({}, raw=raw.replace(b"CAP-1", b"CAP-2"), headers=headers)

    assert response.status_code == 400


@pytest.mark.parametrize("raw", [b"not json", b"[1, 2]", b'{"id": "WH-1"}'])
def test_a_body_that_is_not_a_paypal_event_is_refused(db, raw):
    assert post_event({}, raw=raw).status_code == 400


def test_the_same_event_twice_changes_nothing_the_second_time(reserved_quietly, demo_order):
    lucia = reserved_quietly["s_lucia"]
    voided = fake_event("PAYMENT.AUTHORIZATION.VOIDED", "authorization", {"id": lucia.authorization_id}, "Voided")

    first, second = post_event(voided), post_event(voided)

    assert (first.json(), second.json()) == ({"status": "processed"}, {"status": "repeat"})
    assert demo_order.scalar(select(func.count()).select_from(ProcessedWebhook)) == 1
    assert feed(demo_order, EventType.PART_RELEASED) == [
        "Lucía's share of $220.00 was released: PayPal voided its hold"
    ]


def test_a_hold_voided_at_paypal_releases_the_share_and_is_confirmed(reserved_quietly, demo_order):
    lucia = reserved_quietly["s_lucia"]

    post_event(fake_event("PAYMENT.AUTHORIZATION.VOIDED", "authorization", {"id": lucia.authorization_id}, "Voided"))

    share = next(part for part in order()["parts"] if part["seller"]["name"] == "Lucía")
    assert (share["status"], share["confirmed_by_paypal"]) == ("released", True)


def test_a_capture_completed_before_its_authorization_was_confirmed_still_ends_paid_and_confirmed(
    reserved_quietly, demo_order
):
    amina = reserved_quietly["s_amina"]
    captured = fake_event(
        "PAYMENT.CAPTURE.COMPLETED",
        "capture",
        {"id": "CAP-AMINA", "invoice_id": amina.id, "status": "COMPLETED"},
        "Captured",
    )
    created = fake_event("PAYMENT.AUTHORIZATION.CREATED", "authorization", {"id": amina.authorization_id}, "Authorized")

    post_event(captured)  # our own capture call timed out, but PayPal took the money
    post_event(created)  # and the authorization's own event arrives last

    demo_order.expire_all()
    part = demo_order.get(OrderPart, amina.id)
    assert (part.status, part.capture_id) == (PartStatus.CAPTURED, "CAP-AMINA")
    share = next(share for share in order()["parts"] if share["id"] == amina.id)
    assert (share["status"], share["confirmed_by_paypal"]) == ("captured", True)
    assert order()["status"] == "partly_shipped"


def test_a_reservation_confirmed_before_our_side_saved_it_counts_once_saved(demo_order, fakes, settings):
    checkout = start_checkout(demo_order, DEMO_ORDER_ID, fakes.payment_gateway, settings.WEB_BASE_URL)
    demo_order.commit()
    fakes.payment_gateway.approve(checkout.paypal_order_id)
    early = [
        fake_event("PAYMENT.AUTHORIZATION.CREATED", "authorization", {"id": f"{checkout.paypal_order_id}-AUTH-{n}"}, "")
        for n in range(1, 5)
    ]
    for event in early:
        assert post_event(event).json() == {"status": "processed"}

    reserve_order(demo_order, DEMO_ORDER_ID, fakes.payment_gateway)
    demo_order.commit()

    assert [part["confirmed_by_paypal"] for part in order()["parts"]] == [True] * 4


def test_a_denied_payment_needs_attention(reserved_quietly, demo_order):
    grace = reserved_quietly["s_grace"]

    post_event(fake_event("PAYMENT.CAPTURE.DENIED", "capture", {"id": "CAP-G", "invoice_id": grace.id}, "Denied"))

    share = next(share for share in order()["parts"] if share["id"] == grace.id)
    assert share["attention"] == "PayPal denied this payment"
    assert feed(demo_order, EventType.PAYMENT_WEBHOOK) == [
        "PayPal denied this payment: Grace's share needs attention"
    ]


def test_a_payout_to_a_maker_is_reported_by_her_share(reserved_quietly, demo_order):
    priya = reserved_quietly["s_priya"]
    item = {"payout_item_id": "ITEM-1", "transaction_status": "SUCCESS", "payout_item": {"sender_item_id": priya.id}}

    post_event(fake_event("PAYMENT.PAYOUTS-ITEM.SUCCEEDED", "payouts_item", item, "Paid out"))

    assert feed(demo_order, EventType.PAYMENT_WEBHOOK) == ["PayPal paid out Priya's share"]


def test_an_event_we_do_not_handle_is_kept_and_ignored(demo_order):
    response = post_event(fake_event("BILLING.PLAN.CREATED", "plan", {"id": "P-1"}, "A plan"))

    assert response.json() == {"status": "processed"}
    kept = demo_order.scalars(select(ProcessedWebhook)).one()
    assert (kept.event_type, kept.resource_id) == ("BILLING.PLAN.CREATED", "P-1")
    assert feed(demo_order, EventType.PAYMENT_WEBHOOK) == ["PayPal sent BILLING.PLAN.CREATED; nothing to do"]


# In sandbox mode PayPal itself checks the signature.

TRANSMISSION = {
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-360caa42-fca2a594-a5cafa77",
    "PAYPAL-TRANSMISSION-ID": "69cd13f0-d67a-11e5-baa3-778b53f4ae55",
    "PAYPAL-TRANSMISSION-SIG": "lmI95Jx3Y9nhR5SJWlHVIWpg4AgFk7n9bCHSRxbrd8A9zrhdu2rMyFrmz+Zjh3s3boXB07VXCXUZy/UFzUlnGJn0wDugt7FlSvdKeIJenLRemUxYCPVoEZzg9VFNqOa48gMkvF+XEZxBeH6CQHMZjQiE0Afpc4OTDtGJHgXZimBTaEKZPdgm+5x5lAG9hKUGB/qDXFbbAfrYAVNoCdKNMSEoplCvXqPGQZZIuaFSx2rORaGO+ZpoiKmqZYkEEbYKXqXEMJ3n6g4UDeU+O2IsCGb39DD6Cj7Lu/DT3IR/0Mo+1+Rr8vbt4yfWHXSHr3EfhmHmnyuUnCa1PJ+kCnKeYDvXEijlLX3ZGPROsJ2sqpb+3rvBg/7G4z8tF8fn/fTVL7iC07/FERoi8w5ZqGsHYN4nObPu2gBwplS4E6O7AYWo5A8xJ1MVYBmFYTyMbWlPRyMeGv9wGEJqfFnOFC9dQ==",
    "PAYPAL-TRANSMISSION-TIME": "2026-11-03T12:00:00Z",
}


@pytest.fixture
def sandbox(use_settings, db):
    use_settings(
        OPENSTALL_MODE="sandbox",
        PAYPAL_CLIENT_ID="made-up-id",
        PAYPAL_CLIENT_SECRET="made-up-secret",
        PAYPAL_WEBHOOK_ID="8PT597110X687430LKGECATA",
    )
    with respx.mock(base_url=PAYPAL, assert_all_called=False) as paypal:
        paypal.post("/v1/oauth2/token").respond(json={"access_token": "TOKEN", "expires_in": 32400})
        yield paypal


def test_paypal_is_sent_the_event_byte_for_byte_with_our_webhook_id(sandbox, db):
    verify = sandbox.post("/v1/notifications/verify-webhook-signature").respond(
        json={"verification_status": "SUCCESS"}
    )
    raw = b'{"id":"WH-REAL-1","event_type":"BILLING.PLAN.CREATED","resource":{"id":"P-1"},  "spacing":"kept"}'

    response = post_event({}, raw=raw, headers=TRANSMISSION)

    assert response.json() == {"status": "processed"}
    sent = verify.calls.last.request.content
    assert raw in sent
    body = json.loads(sent)
    assert body["webhook_id"] == "8PT597110X687430LKGECATA"
    assert body["transmission_id"] == TRANSMISSION["PAYPAL-TRANSMISSION-ID"]
    assert body["transmission_sig"] == TRANSMISSION["PAYPAL-TRANSMISSION-SIG"]
    assert body["cert_url"] == TRANSMISSION["PAYPAL-CERT-URL"]
    assert body["auth_algo"] == "SHA256withRSA"


def test_an_event_paypal_does_not_recognise_is_refused(sandbox, db):
    sandbox.post("/v1/notifications/verify-webhook-signature").respond(json={"verification_status": "FAILURE"})

    response = post_event({}, raw=b'{"id":"WH-X","event_type":"PAYMENT.CAPTURE.COMPLETED"}', headers=TRANSMISSION)

    assert response.status_code == 400


def test_an_event_without_paypals_headers_is_refused_without_asking_paypal(sandbox, db):
    verify = sandbox.post("/v1/notifications/verify-webhook-signature").respond(json={"verification_status": "SUCCESS"})

    response = post_event({}, raw=b'{"id":"WH-X","event_type":"PAYMENT.CAPTURE.COMPLETED"}', headers={})

    assert response.status_code == 400
    assert not verify.called


def test_when_paypal_cannot_verify_right_now_it_is_asked_to_send_the_event_again(sandbox, db):
    sandbox.post("/v1/notifications/verify-webhook-signature").respond(503)

    response = post_event({}, raw=b'{"id":"WH-X","event_type":"PAYMENT.CAPTURE.COMPLETED"}', headers=TRANSMISSION)

    assert response.status_code == 503
    assert db.scalar(select(func.count()).select_from(ProcessedWebhook)) == 0


def test_without_a_webhook_id_no_event_is_accepted(use_settings, db):
    use_settings(OPENSTALL_MODE="sandbox", PAYPAL_CLIENT_ID="made-up-id", PAYPAL_CLIENT_SECRET="made-up-secret")

    with respx.mock(base_url=PAYPAL) as paypal:
        response = post_event({}, raw=b'{"id":"WH-X","event_type":"PAYMENT.CAPTURE.COMPLETED"}', headers=TRANSMISSION)

    assert response.status_code == 400
    assert not paypal.calls
