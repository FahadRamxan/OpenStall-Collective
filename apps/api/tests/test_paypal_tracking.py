"""Each maker's tracking on the PayPal order (prompt 33, spec 3.6): once her share is captured on proof of shipping,
her confirmed tracking goes on that capture at PayPal, once, with PayPal's carrier code. PayPal takes no request id on
this route, so the order is read back first and a tracker already there is never sent again; one PayPal refuses is
tried again when the order is opened again."""

import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from sqlalchemy import select

from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import Event, Order, OrderPart, PartStatus, PayoutRailChoice, Seller
from openstall_api.payments import WrongStatus, track_share
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order
from openstall_api.storefront import storefront
from openstall_api.tracking import track_on_paypal
from openstall_paypal import PaymentError

client = TestClient(app)
TODAY = date(2026, 11, 10)


@pytest.fixture
def story(db):
    """The story's order, approved on the simulated PayPal page and reserved; each maker told. The session."""
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


def prove(seller_id: str) -> None:
    """She sends her courier receipt photo and confirms what was read: paid on proof, if a rail reaches her."""
    play(seller_id, receipt=True)
    play(seller_id, "yes")


def part_of(db, name: str) -> OrderPart:
    db.expire_all()
    return next(part for part in db.get(Order, DEMO_ORDER_ID).parts if part.seller.name == name)


def tracking_calls(fakes) -> list:
    return [args for name, args in fakes.payment_gateway.calls if name == "add_tracking"]


def events(db, kind: EventType) -> list[Event]:
    db.expire_all()
    return list(db.scalars(select(Event).where(Event.type == kind.value).order_by(Event.id)))


def test_once_priya_is_paid_on_proof_her_tracking_goes_on_her_capture_at_paypal(story, fakes):
    prove("s_priya")

    priya = part_of(story, "Priya")
    assert priya.status == PartStatus.CAPTURED
    [sent] = tracking_calls(fakes)
    assert (sent.capture_id, sent.tracking_number, sent.carrier, sent.carrier_name_other) == (
        priya.capture_id,
        "EE123456789IN",
        "INDIA_POST",
        None,
    )
    assert sent.paypal_order_id == story.get(Order, DEMO_ORDER_ID).paypal_order_id
    assert priya.paypal_tracker_id == f"{priya.capture_id}-EE123456789IN"
    [added] = events(story, EventType.TRACKING_ADDED)
    assert added.payload_json["summary"] == (
        f"Priya's tracking (India Post EE123456789IN) is on simulated PayPal order {sent.paypal_order_id}, on her "
        "payment"
    )
    order = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()
    by_name = {part["seller"]["name"]: part for part in order["parts"]}
    assert by_name["Priya"]["tracking_on_paypal"] is True
    assert by_name["Lucía"]["tracking_on_paypal"] is False


def test_the_buyer_agent_sees_her_tracking_is_on_the_paypal_order(story):
    prove("s_priya")

    async def go():
        async with Client(storefront) as mcp:
            return await mcp.call_tool("get_order_status", {"order_id": DEMO_ORDER_ID})

    status = asyncio.run(go()).structured_content
    shares = {share["seller_name"]: share for share in status["shares"]}
    assert (shares["Priya"]["tracking_number"], shares["Priya"]["tracking_on_paypal"]) == ("EE123456789IN", True)
    assert shares["Grace"]["tracking_on_paypal"] is False


def test_a_maker_who_is_not_paid_yet_has_no_tracking_at_paypal(story, fakes):
    story.get(Seller, "s_amina").payout_rail = PayoutRailChoice.PAYPAL  # PayPal Payouts cannot reach Pakistan
    story.commit()
    prove("s_amina")  # no payout rail reaches her: tracked, not captured

    amina = part_of(story, "Amina")
    assert (amina.tracking_number, amina.status, amina.paypal_tracker_id) == ("7712345678", PartStatus.AUTHORIZED, None)
    assert tracking_calls(fakes) == []  # PayPal tracks a capture, and there is none
    with pytest.raises(WrongStatus, match="not captured yet"):
        track_share(story, amina.id, fakes.payment_gateway)


def test_tracking_paypal_refuses_is_said_and_added_when_the_order_is_opened_again(story, fakes):
    gateway = fakes.payment_gateway
    gateway.add_tracking = lambda tracking: (_ for _ in ()).throw(PaymentError("INVALID_CAPTURE_ID", "no capture"))

    prove("s_priya")

    priya = part_of(story, "Priya")
    assert (priya.status, priya.paypal_tracker_id) == (PartStatus.CAPTURED, None)  # paid all the same
    [refused] = events(story, EventType.TRACKING_NOT_ADDED)
    assert refused.payload_json["summary"] == (
        "Priya's tracking is not on the simulated PayPal order yet (INVALID_CAPTURE_ID). It is tried again when the "
        "order is opened again"
    )

    del gateway.add_tracking  # PayPal takes it now; the receipt page reserving the order again puts it right
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve").status_code == 200

    assert part_of(story, "Priya").paypal_tracker_id is not None
    assert len(events(story, EventType.TRACKING_ADDED)) == 1


def test_a_tracker_already_on_the_paypal_order_is_recorded_never_sent_again(story, fakes):
    prove("s_priya")
    first = part_of(story, "Priya").paypal_tracker_id
    part_of(story, "Priya").paypal_tracker_id = None  # as if our side lost its save after PayPal took it
    story.commit()

    assert track_on_paypal(part_of(story, "Priya").id, lambda: fakes.payment_gateway) is True

    assert part_of(story, "Priya").paypal_tracker_id == first
    assert len(tracking_calls(fakes)) == 1  # read back from the order, not sent a second time


def test_putting_it_on_twice_sends_it_once(story, fakes):
    prove("s_priya")
    part_id = part_of(story, "Priya").id

    assert track_on_paypal(part_id, lambda: fakes.payment_gateway) is True
    assert track_on_paypal(part_id, lambda: fakes.payment_gateway) is True

    assert len(tracking_calls(fakes)) == 1
    assert len(events(story, EventType.TRACKING_ADDED)) == 1


def test_simulated_proof_puts_its_tracking_on_simulated_paypal_too(story, fakes):
    grace = part_of(story, "Grace")

    order = client.post(f"/api/dev/parts/{grace.id}/proof").json()

    shared = next(part for part in order["parts"] if part["seller"]["name"] == "Grace")
    assert (shared["status"], shared["tracking_on_paypal"]) == ("captured", True)
    [sent] = tracking_calls(fakes)
    assert (sent.tracking_number, sent.carrier, sent.carrier_name_other) == (
        f"SIMULATED-{grace.id}",
        "OTHER",
        "Courier not named",
    )
