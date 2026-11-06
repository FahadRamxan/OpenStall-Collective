"""Disputes answered with the proof (prompt 56): a buyer's PayPal dispute on a maker's paid share is answered with her
proof of shipping, once, after the webhook's commit; she is told in her language; anything her proof does not answer
waits for a person; and a dispute PayPal decides for the buyer counts against her trust passport."""

import asyncio
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from sqlalchemy import select

from openstall_api.events import EventType
from openstall_api.fixtures import demo_shipment
from openstall_api.main import app
from openstall_api.models import ChatMessage, ChatSession, Direction, Event, Order, OrderPart, Passport, PartStatus
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order
from openstall_api.storefront import storefront
from openstall_api.webhooks import receive_paypal_webhook
from openstall_paypal import DisputeEvidence, PaymentError
from openstall_paypal.webhooks import fake_event, sign_fake_webhook

client = TestClient(app)
TODAY = date(2026, 11, 3)
INDIA_POST, PRIYA_TRACKING = demo_shipment("IN")


@pytest.fixture
def story(db):
    """The story's order, approved on the simulated PayPal page and reserved; each maker told."""
    seed(db, with_amina=True)
    seed_demo_order(db, TODAY)
    db.commit()
    token = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve").status_code == 200
    return db


def play(seller_id: str, text: str = "", receipt: bool = False) -> list[str]:
    response = client.post(f"/api/dev/sellers/{seller_id}/messages", json={"text": text, "receipt": receipt})
    assert response.status_code == 201, response.text
    return response.json()["replies"]


def part_of(db, name: str) -> OrderPart:
    db.expire_all()
    return next(part for part in db.get(Order, DEMO_ORDER_ID).parts if part.seller.name == name)


def events(db, kind: EventType) -> list[Event]:
    db.expire_all()
    return list(db.scalars(select(Event).where(Event.type == kind.value).order_by(Event.id)))


def chat_texts(db, seller_id: str) -> list[str]:
    db.expire_all()
    query = (
        select(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .where(ChatSession.seller_id == seller_id, ChatMessage.direction == Direction.OUTBOUND)
        .order_by(ChatMessage.created_at)
    )
    return [message.text or "" for message in db.scalars(query)]


def answers(fakes) -> list[DisputeEvidence]:
    return [evidence for name, evidence in fakes.payment_gateway.calls if name == "answer_dispute"]


def priya_paid_by_her_receipt(story) -> OrderPart:
    play("s_priya", receipt=True)
    play("s_priya", "हाँ")
    priya = part_of(story, "Priya")
    assert priya.status == PartStatus.CAPTURED
    return priya


def dispute(part_id: str, reason: str | None = None) -> dict:
    response = client.post(f"/api/dev/parts/{part_id}/dispute", json={"reason": reason} if reason else None)
    assert response.status_code == 200, response.text
    return next(part for part in response.json()["parts"] if part["id"] == part_id)


def send(kind: str, resource: dict) -> str:
    raw = json.dumps(fake_event(kind, "dispute", resource, kind)).encode("utf-8")
    return receive_paypal_webhook(raw, sign_fake_webhook(raw))


def test_a_parcel_the_buyer_says_never_came_is_answered_with_her_proof_and_she_is_told(story, fakes):
    priya = priya_paid_by_her_receipt(story)

    part = dispute(priya.id)

    [evidence] = answers(fakes)
    assert (evidence.carrier, evidence.tracking_number) == (INDIA_POST, PRIYA_TRACKING)
    assert evidence.photo is not None and evidence.photo_type == "image/png"
    assert evidence.photo_name == f"courier-receipt-{priya.id}.png"
    assert evidence.notes.startswith(
        "OpenStall Collective order ord_demo: 11 x Mirror-work embroidered cushion cover, made and sent by Priya (Jaipur, "
        f"IN). Shipped with {INDIA_POST}, tracking number {PRIYA_TRACKING}, confirmed by her on "
    )
    assert evidence.notes.endswith("Her courier receipt photo is attached.")
    # Simulated PayPal took her proof and decided at once, and the receipt says so.
    assert part["dispute"] == {
        "dispute_id": evidence.dispute_id,
        "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        "state": "resolved",
        "outcome": "seller",
        "words": "PayPal dispute (the parcel did not arrive): decided in her favour (simulated PayPal)",
    }
    [opened] = events(story, EventType.DISPUTE_OPENED)
    assert opened.payload_json["summary"] == (
        "The buyer opened a PayPal dispute on Priya's share of order ord_demo ($176.00): the parcel did not arrive. "
        "OpenStall answers with her proof of shipping (simulated PayPal)"
    )
    [answered] = events(story, EventType.DISPUTE_ANSWERED)
    assert answered.payload_json["summary"] == (
        "OpenStall answered the buyer's PayPal dispute on Priya's share of order ord_demo with her proof of shipping: "
        f"{INDIA_POST} {PRIYA_TRACKING}, her courier receipt photo (simulated PayPal)"
    )
    [resolved] = events(story, EventType.DISPUTE_RESOLVED)
    assert resolved.payload_json["outcome"] == "seller"
    told = chat_texts(story, "s_priya")
    assert (
        "एक खरीदार ने ऑर्डर ord_demo पर PayPal में शिकायत की है कि पार्सल नहीं पहुँचा। OpenStall ने PayPal को आपका ट्रैकिंग नंबर "
        f"{PRIYA_TRACKING} और कूरियर रसीद की फ़ोटो भेज दिया है। आपको कुछ करने की ज़रूरत नहीं है।\n"
        "(टेस्ट मोड: नकली PayPal, कोई असली पैसा नहीं भेजा गया।)"
    ) in told
    assert told[-1].startswith("PayPal ने ऑर्डर ord_demo की शिकायत आपके पक्ष में बंद कर दी है।")
    # Her share is still paid: a dispute moves no money on our side.
    assert part_of(story, "Priya").status == PartStatus.CAPTURED


def test_the_buyer_s_agent_sees_the_dispute(story, fakes):
    priya = priya_paid_by_her_receipt(story)
    dispute(priya.id)

    async def status() -> dict:
        async with Client(storefront) as mcp:
            return (await mcp.call_tool("get_order_status", {"order_id": DEMO_ORDER_ID})).structured_content

    shares = {share["seller_name"]: share for share in asyncio.run(status())["shares"]}
    assert shares["Priya"]["dispute"] == "PayPal dispute (the parcel did not arrive): decided in her favour (simulated PayPal)"
    assert shares["Lucía"]["dispute"] is None


def test_a_dispute_her_proof_does_not_answer_waits_for_a_person(story, fakes):
    priya = priya_paid_by_her_receipt(story)

    part = dispute(priya.id, "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED")

    assert answers(fakes) == []
    assert part["dispute"]["state"] == "needs_person"
    assert part["dispute"]["words"] == (
        "PayPal dispute: the buyer says the item is not as described. Needs a person: the buyer says the item is not "
        "as described, which proof of shipping does not answer"
    )
    [opened] = events(story, EventType.DISPUTE_OPENED)
    assert opened.payload_json["summary"].endswith(
        "It needs a person: the buyer says the item is not as described, which proof of shipping does not answer "
        "(simulated PayPal)"
    )


def test_only_a_paid_share_can_be_disputed(story):
    response = client.post(f"/api/dev/parts/{part_of(story, 'Lucía').id}/dispute")

    assert response.status_code == 409
    assert response.json()["detail"] == "Lucía's share is authorized: a dispute is about a payment, and hers is not taken."


def test_a_repeated_event_answers_nothing_twice(story, fakes):
    priya = priya_paid_by_her_receipt(story)
    resource = {
        "dispute_id": "PP-D-REPEAT",
        "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        "status": "UNDER_REVIEW",
        "dispute_amount": {"currency_code": "USD", "value": "176.00"},
        "disputed_transactions": [{"seller_transaction_id": priya.capture_id}],
        "links": [],
    }

    assert send("CUSTOMER.DISPUTE.CREATED", resource) == "processed"
    assert send("CUSTOMER.DISPUTE.CREATED", resource) == "repeat"

    # PayPal does not take the seller's evidence yet: nothing is sent, and the receipt says why.
    assert answers(fakes) == []
    record = part_of(story, "Priya").dispute_json
    assert record["state"] == "waiting"
    assert len(events(story, EventType.DISPUTE_OPENED)) == 1


def test_a_dispute_waiting_for_paypal_is_answered_once_paypal_asks_for_the_seller_s_evidence(story, fakes):
    priya = priya_paid_by_her_receipt(story)
    waiting = {
        "dispute_id": "PP-D-LATER",
        "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        "status": "UNDER_REVIEW",
        "disputed_transactions": [{"seller_transaction_id": priya.capture_id}],
        "links": [],
    }
    send("CUSTOMER.DISPUTE.CREATED", waiting)
    fakes.payment_gateway._disputes["PP-D-LATER"] = {**waiting, "status": "WAITING_FOR_SELLER_RESPONSE"}

    send(
        "CUSTOMER.DISPUTE.UPDATED",
        {
            **waiting,
            "status": "WAITING_FOR_SELLER_RESPONSE",
            "links": [{"rel": "provide_evidence", "href": "/v1/customer/disputes/PP-D-LATER/provide-evidence"}],
        },
    )

    [evidence] = answers(fakes)
    assert evidence.dispute_id == "PP-D-LATER"
    assert part_of(story, "Priya").dispute_json["state"] in ("answered", "resolved")


def test_paypal_refusing_her_proof_leaves_the_dispute_open_with_the_reason(story, fakes, monkeypatch):
    priya = priya_paid_by_her_receipt(story)

    def refuse(evidence):
        raise PaymentError("NOT_ELIGIBLE", "PayPal does not take evidence on this dispute")

    monkeypatch.setattr(fakes.payment_gateway, "answer_dispute", refuse)

    part = dispute(priya.id)

    assert part["dispute"]["state"] == "open"
    assert part["dispute"]["words"] == (
        "PayPal dispute: the buyer says the parcel did not arrive. Her proof could not be sent yet: NOT_ELIGIBLE: "
        "PayPal does not take evidence on this dispute"
    )
    assert events(story, EventType.DISPUTE_ANSWERED) == []


def test_a_dispute_paypal_decides_for_the_buyer_counts_against_her_passport(story, fakes):
    priya = priya_paid_by_her_receipt(story)
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/parts/{priya.id}/delivered").status_code == 200
    before = dict(story.get(Passport, "s_priya").metrics_json)

    send(
        "CUSTOMER.DISPUTE.RESOLVED",
        {
            "dispute_id": "PP-D-LOST",
            "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
            "status": "RESOLVED",
            "dispute_outcome": {"outcome_code": "RESOLVED_BUYER_FAVOUR"},
            "disputed_transactions": [{"seller_transaction_id": priya.capture_id}],
        },
    )

    story.expire_all()
    after = story.get(Passport, "s_priya").metrics_json
    assert after["dispute_rate"] > before["dispute_rate"]
    assert after["orders_delivered"] == before["orders_delivered"]
    [resolved] = events(story, EventType.DISPUTE_RESOLVED)
    assert resolved.payload_json["summary"] == (
        "PayPal decided the buyer's dispute on Priya's share of order ord_demo: for the buyer (simulated PayPal)"
    )
    assert chat_texts(story, "s_priya")[-1].startswith(
        "PayPal ने ऑर्डर ord_demo की शिकायत का फ़ैसला खरीदार के पक्ष में किया है।"
    )


def test_a_dispute_on_a_payment_that_is_not_ours_changes_nothing(story, fakes):
    assert send(
        "CUSTOMER.DISPUTE.CREATED",
        {"dispute_id": "PP-D-ELSEWHERE", "status": "OPEN", "disputed_transactions": [{"seller_transaction_id": "X"}]},
    ) == "processed"

    assert answers(fakes) == []
    assert events(story, EventType.DISPUTE_OPENED) == []
