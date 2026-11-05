"""The order heals itself (prompt 39): a maker who cannot make her share says so in her chat and confirms; her share
is released, never charged; the other makers' agents are asked for her units, and a top-up order for them waits for the
buyer's approval, like any order."""

import asyncio
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from sqlalchemy import select

from openstall_allocator import FixedClock
from openstall_api import quotes
from openstall_api.events import EventType
from openstall_api.healing import cant_make_it, heal_after
from openstall_api.main import app
from openstall_api.models import Event, Order, OrderPart, OrderStatus, PartStatus, QuoteRequest
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order
from openstall_api.storefront import storefront

client = TestClient(app)
TODAY = date(2026, 11, 10)
ROOT = Path(__file__).resolve().parents[3]
SORRY = "Sorry, I can't make this order."


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(quotes, "clock", FixedClock(TODAY))


@pytest.fixture
def story(db):
    """The story's order (Amina 12, Priya 11, Lucía 10, Grace 7; due December 10, Chicago), approved on the simulated
    PayPal page and reserved: PayPal holds it, and each maker has been told. Returns the database session."""
    seed(db, with_amina=True)
    seed_demo_order(db, TODAY)
    db.commit()
    reserve(DEMO_ORDER_ID)
    return db


def reserve(order_id: str) -> None:
    token = client.post(f"/api/orders/{order_id}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    assert client.post(f"/api/orders/{order_id}/reserve").status_code == 200


def play(seller_id: str, text: str) -> list[str]:
    """As if this maker wrote to OpenStall (fake mode), and OpenStall's replies. Work after the commit (a release and
    its re-plan) runs before the test client returns."""
    response = client.post(f"/api/dev/sellers/{seller_id}/messages", json={"text": text})
    assert response.status_code == 201, response.text
    return response.json()["replies"]


def part_of(db, name: str, order_id: str = DEMO_ORDER_ID) -> OrderPart:
    db.expire_all()
    return next(part for part in db.get(Order, order_id).parts if part.seller.name == name)


def events(db, kind: EventType) -> list[Event]:
    db.expire_all()
    return list(db.scalars(select(Event).where(Event.type == kind.value).order_by(Event.id)))


def top_ups(db, order_id: str = DEMO_ORDER_ID) -> list[Order]:
    db.expire_all()
    return list(db.scalars(select(Order).where(Order.parent_order_id == order_id).order_by(Order.created_at)))


def calls(fakes, name: str) -> int:
    return sum(1 for called, _ in fakes.payment_gateway.calls if called == name)


def get_order_status(order_id: str) -> dict:
    async def go():
        async with Client(storefront) as mcp:
            return await mcp.call_tool("get_order_status", {"order_id": order_id})

    result = asyncio.run(go())
    assert not result.is_error, result.content
    return result.structured_content


# "I can't make it", in the makers' languages


@pytest.mark.parametrize(
    "text",
    [
        SORRY,
        "I cant make it, sorry",
        "I cannot deliver the order",
        "I won't be able to make them in time",
        "معاف کیجیے، میں یہ آرڈر نہیں بنا سکتی۔",
        "main nahi bana sakti",
        "माफ़ कीजिए, मैं यह ऑर्डर नहीं बना सकती।",
        "Lo siento, no puedo hacer este pedido.",
        "No voy a poder, lo siento",
    ],
)
def test_cant_make_it_in_each_language(text):
    assert cant_make_it(text)


@pytest.mark.parametrize(
    "text", ["I can make it", "Can you make it bigger?", "yes", "I made it!", "میں بنا سکتی ہوں", "sí puedo hacerlo"]
)
def test_words_that_are_not_dropping_out(text):
    assert not cant_make_it(text)


def test_the_words_the_demo_phones_play_are_heard_as_cant_make_it():
    """/demo's test-mode button plays these words as the maker, in her language: each must start the drop-out."""
    source = (ROOT / "apps" / "web" / "src" / "components" / "maker-phones.tsx").read_text(encoding="utf-8")
    block = re.search(r"CANT_WORDS[^{]*\{(.*?)\}", source, re.S)
    assert block is not None
    words = dict(re.findall(r'(\w+): "([^"]+)"', block.group(1)))
    assert set(words) == {"ur", "hi", "es", "en"}
    assert all(cant_make_it(text) for text in words.values()), words


# Asked first, then dropped on her yes


def test_grace_says_she_cannot_make_it_and_is_asked_to_confirm_before_anything_moves(story, fakes):
    [reply] = play("s_grace", SORRY)

    assert reply.startswith("I'm sorry to hear that. Do you want to give up your share of order ord_demo (7 × ")
    assert "$203.00" in reply and "Reply YES to give it up, or NO to keep it." in reply
    grace = part_of(story, "Grace")
    assert grace.status == PartStatus.AUTHORIZED
    assert grace.drop_json["state"] == "asked" and grace.drop_json["said"] == SORRY
    [asked] = events(story, EventType.PART_DROP_ASKED)
    assert asked.entity_id == grace.id
    assert asked.payload_json["summary"].startswith("Grace said she cannot make her share of order ord_demo")
    assert calls(fakes, "release_share") == 0
    assert events(story, EventType.PART_DROPPED) == []
    assert top_ups(story) == []


def test_her_yes_releases_her_share_and_the_other_makers_are_asked_for_her_units(story, fakes):
    play("s_grace", SORRY)
    [reply] = play("s_grace", "Yes")

    assert reply.startswith("Done: your share of order ord_demo goes back to the buyer, and nothing is charged for it.")
    grace = part_of(story, "Grace")
    assert grace.status == PartStatus.RELEASED
    assert grace.drop_json["state"] == "dropped"
    [dropped] = events(story, EventType.PART_DROPPED)
    assert dropped.payload_json["summary"].startswith("Grace dropped out of order ord_demo: she cannot make her 7 × ")
    assert [event.entity_id for event in events(story, EventType.PART_RELEASED)] == [grace.id]
    assert calls(fakes, "release_share") == 1
    assert calls(fakes, "pay_share") == 0  # nothing is captured for anyone

    # Her units were asked of every other matching maker, by the same deadline, at most the buyer's price.
    asked_again = story.get(QuoteRequest, grace.drop_json["request_id"])
    first = story.get(Order, DEMO_ORDER_ID).request
    assert (asked_again.quantity, asked_again.deadline, asked_again.ship_to) == (7, first.deadline, first.ship_to)
    assert asked_again.max_unit_price == first.max_unit_price and asked_again.items_json == first.items_json
    requested = next(e for e in events(story, EventType.QUOTE_REQUESTED) if e.entity_id == asked_again.id)
    assert requested.payload_json["summary"].startswith(
        "OpenStall, replacing Grace in order ord_demo, asked for 7 × "
    )
    assert "s_grace" not in requested.payload_json["asked"] and requested.payload_json["asked"]

    # A top-up order for her units waits for the buyer's approval; the first order goes on without her.
    [top_up] = top_ups(story)
    assert grace.drop_json["top_up_order_id"] == top_up.id
    assert top_up.status == OrderStatus.DRAFT and top_up.source == "replan"
    assert top_up.request_id == asked_again.id
    assert sum(line.quantity for line in top_up.parts) == 7
    assert "s_grace" not in {line.seller_id for line in top_up.parts}
    assert top_up.total_usd == sum((line.amount_usd for line in top_up.parts), Decimal("0.00"))
    assert story.get(Order, DEMO_ORDER_ID).status == OrderStatus.AUTHORIZED
    [created] = events(story, EventType.TOPUP_CREATED)
    assert created.entity_id == top_up.id
    assert created.payload_json["summary"].startswith(f"Top-up order {top_up.id} for order ord_demo: 7 units from ")
    assert created.payload_json["approval_url"].endswith(f"/approve/{top_up.id}")
    [replanned] = events(story, EventType.ORDER_REPLANNED)
    assert replanned.entity_id == DEMO_ORDER_ID
    summary = replanned.payload_json["summary"]
    assert "re-planned without Grace" in summary and "all 7 units she dropped" in summary


def test_her_no_keeps_her_share(story, fakes):
    play("s_grace", SORRY)
    [reply] = play("s_grace", "No")

    assert reply == "Good: you keep your share of order ord_demo. Please ship it by December 7, 2026."
    grace = part_of(story, "Grace")
    assert grace.status == PartStatus.AUTHORIZED and grace.drop_json["state"] == "kept"
    assert len(events(story, EventType.PART_KEPT)) == 1
    assert calls(fakes, "release_share") == 0 and top_ups(story) == []
    # A yes now is not a drop: nothing is being asked.
    assert not any("goes back to the buyer" in text for text in play("s_grace", "Yes"))
    assert part_of(story, "Grace").status == PartStatus.AUTHORIZED


def test_priya_drops_out_in_hindi(story, fakes):
    [ask] = play("s_priya", "माफ़ कीजिए, मैं यह ऑर्डर नहीं बना सकती।")
    assert "ऑर्डर ord_demo" in ask and "छोड़ना" in ask
    [done] = play("s_priya", "हाँ")
    assert done.startswith("हो गया: ऑर्डर ord_demo में से आपका हिस्सा")
    assert part_of(story, "Priya").status == PartStatus.RELEASED
    [top_up] = top_ups(story)
    assert "s_priya" not in {line.seller_id for line in top_up.parts}


def test_only_a_reserved_share_can_be_dropped(db, fakes):
    seed(db, with_amina=True)
    seed_demo_order(db, TODAY)  # drafted, never approved: nothing is reserved, and she was never told
    db.commit()

    replies = play("s_grace", SORRY)

    assert not any("give up your share" in text for text in replies)
    assert part_of(db, "Grace").drop_json is None


def test_a_share_whose_receipt_she_is_confirming_is_not_dropped(story, fakes):
    response = client.post("/api/dev/sellers/s_priya/messages", json={"text": "", "receipt": True})
    assert response.status_code == 201
    play("s_priya", "माफ़ कीजिए, मैं यह ऑर्डर नहीं बना सकती।")

    assert part_of(story, "Priya").drop_json is None


# Once only, and when it cannot be done


def test_healing_again_changes_nothing(story, fakes):
    play("s_grace", SORRY)
    play("s_grace", "Yes")
    grace = part_of(story, "Grace")
    [top_up] = top_ups(story)

    again = heal_after(grace.id, lambda: fakes.payment_gateway, lambda: fakes.llm)

    assert again == top_up.id
    assert len(top_ups(story)) == 1 and calls(fakes, "release_share") == 1
    assert len(events(story, EventType.ORDER_REPLANNED)) == 1


def test_when_no_other_maker_can_make_her_units_the_feed_says_so(story, fakes):
    story.get(Order, DEMO_ORDER_ID).request.max_unit_price = Decimal("5.00")  # below every maker's floor
    story.commit()

    play("s_grace", SORRY)
    play("s_grace", "Yes")

    grace = part_of(story, "Grace")
    assert grace.status == PartStatus.RELEASED and top_ups(story) == []
    assert grace.drop_json["replan_failed"]
    [replanned] = events(story, EventType.ORDER_REPLANNED)
    assert replanned.payload_json["summary"] == (
        "Order ord_demo re-planned without Grace: no other maker can make her 7 units by December 10, so the buyer "
        "gets the rest of the order without them"
    )
    assert events(story, EventType.TOPUP_CREATED) == []


def test_after_the_deadline_her_units_are_not_asked_for_again(story, fakes, monkeypatch):
    monkeypatch.setattr(quotes, "clock", FixedClock(date(2026, 12, 11)))

    play("s_grace", SORRY)
    play("s_grace", "Yes")

    assert part_of(story, "Grace").status == PartStatus.RELEASED and top_ups(story) == []
    [replanned] = events(story, EventType.ORDER_REPLANNED)
    assert replanned.payload_json["summary"] == (
        "Order ord_demo could not be re-planned without Grace: its deadline, December 10, has passed"
    )


# What the buyer and the buyer's agent see


def test_the_order_shows_her_drop_and_its_top_up(story, fakes):
    play("s_grace", SORRY)
    asked = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()
    assert next(p for p in asked["parts"] if p["seller"]["name"] == "Grace")["drop"]["state"] == "asked"
    play("s_grace", "Yes")
    [top_up] = top_ups(story)

    order = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()

    grace = next(p for p in order["parts"] if p["seller"]["name"] == "Grace")
    assert grace["status"] == "released"
    assert grace["drop"]["state"] == "dropped" and grace["drop"]["top_up_order_id"] == top_up.id
    [shown] = order["top_ups"]
    assert shown["id"] == top_up.id and shown["status"] == "draft" and shown["units"] == 7
    replaces = {"order_id": DEMO_ORDER_ID, "part_id": grace["id"], "seller_name": "Grace", "quantity": 7}
    assert shown["replaces"] == replaces
    assert sum(part["quantity"] for part in shown["parts"]) == 7
    assert client.get(f"/api/orders/{top_up.id}").json()["replaces"]["seller_name"] == "Grace"
    # /demo follows the first order, with its top-ups inside it; the newest order of all is the top-up.
    assert client.get("/api/orders?limit=1&top_ups=false").json()[0]["id"] == DEMO_ORDER_ID
    assert client.get("/api/orders?limit=1").json()[0]["id"] == top_up.id


def test_get_order_status_tells_the_buyer_agent_about_the_top_up(story, fakes):
    play("s_grace", SORRY)
    play("s_grace", "Yes")
    [top_up] = top_ups(story)

    status = get_order_status(DEMO_ORDER_ID)

    grace = next(share for share in status["shares"] if share["seller_name"] == "Grace")
    assert grace["dropped_out"] is True and grace["status"] == "released"
    [shown] = status["top_ups"]
    assert shown["order_id"] == top_up.id and shown["units"] == 7 and shown["approved"] is False
    assert shown["approval_link"].endswith(f"/approve/{top_up.id}")
    assert shown["replaces"] == "Grace's 7 units of order ord_demo, which she could not make"
    assert get_order_status(top_up.id)["replaces"] == shown["replaces"]


def test_the_top_up_is_approved_like_any_order_and_its_makers_are_told(story, fakes):
    play("s_grace", SORRY)
    play("s_grace", "Yes")
    [top_up] = top_ups(story)

    reserve(top_up.id)

    story.expire_all()
    assert story.get(Order, top_up.id).status == OrderStatus.AUTHORIZED
    told = {event.entity_id for event in events(story, EventType.ORDER_NOTICE_SENT)}
    assert {line.id for line in story.get(Order, top_up.id).parts} <= told
