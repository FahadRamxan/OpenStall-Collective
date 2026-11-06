"""A materials advance for a trusted maker (prompt 37): she asks in her chat; OpenStall offers a quarter of her reserved
share if her signed trust score is 0.90 or more; her yes has it paid by OpenStall, ahead of her proof, never by the
buyer; and when she ships, her share is captured whole and her payout is that much less."""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from openstall_api.advance import asks_for_advance
from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import (
    ChatMessage,
    ChatSession,
    Direction,
    Event,
    Order,
    OrderPart,
    PartStatus,
    Passport,
    PayoutRailChoice,
    Seller,
)
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order

client = TestClient(app)
TODAY = date(2026, 11, 10)
ROOT = Path(__file__).resolve().parents[3]
ASK = "Could I have an advance for materials?"


@pytest.fixture
def story(db):
    """The story's order, approved and reserved: each maker told, nothing captured."""
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


def share(db, name: str) -> OrderPart:
    db.expire_all()
    return next(part for part in db.get(Order, DEMO_ORDER_ID).parts if part.seller.name == name)


def calls(fakes, name: str) -> list:
    return [args for called, args in fakes.payment_gateway.calls if called == name]


def told(db, seller_id: str) -> list[str]:
    db.expire_all()
    rows = db.scalars(
        select(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .where(ChatSession.seller_id == seller_id, ChatMessage.direction == Direction.OUTBOUND)
        .order_by(ChatMessage.created_at)
    )
    return [message.text or "" for message in rows]


@pytest.mark.parametrize(
    "text",
    [ASK, "can you pay me an advance", "کیا مجھے پیشگی مل سکتا ہے؟", "क्या मुझे अग्रिम मिलेगा?", "¿un anticipo?"],
)
def test_asking_for_an_advance_in_each_language(text):
    assert asks_for_advance(text)


@pytest.mark.parametrize("text", ["yes", "I shipped it", "advanced embroidery"])
def test_words_that_do_not_ask(text):
    assert not asks_for_advance(text)


def test_the_words_the_demo_phones_play_ask_for_an_advance():
    source = (ROOT / "apps" / "web" / "src" / "components" / "maker-phones.tsx").read_text(encoding="utf-8")
    block = re.search(r"ADVANCE_WORDS[^{]*\{(.*?)\}", source, re.S)
    assert block is not None
    words = dict(re.findall(r'(\w+): "([^"]+)"', block.group(1)))
    assert set(words) == {"ur", "hi", "es", "en"} and all(asks_for_advance(text) for text in words.values())


def test_grace_is_offered_a_quarter_of_her_share_and_nothing_moves_before_her_yes(story, fakes):
    [offer] = play("s_grace", ASK)

    assert offer.startswith("Yes: your trust record lets OpenStall pay you $50.75 now for materials")
    assert "your $203.00 share of order ord_demo" in offer and "the other $152.25" in offer
    assert share(story, "Grace").advance_json["state"] == "asked"
    [requested] = story.scalars(select(Event).where(Event.type == EventType.ADVANCE_REQUESTED.value)).all()
    summary = requested.payload_json["summary"]
    assert "her trust score 0.96 earns $50.75 for materials, paid by OpenStall, not the buyer" in summary
    assert calls(fakes, "pay_advance") == []


def test_her_yes_has_openstall_pay_it_and_her_payout_on_proof_is_the_rest(story, fakes):
    play("s_grace", ASK)
    [accepted] = play("s_grace", "Yes")

    assert accepted == "Thank you! Your $50.75 advance is on its way."
    grace = share(story, "Grace")
    assert grace.advance_json["state"] == "paid" and grace.status == PartStatus.AUTHORIZED  # nothing captured
    [advance] = calls(fakes, "pay_advance")
    assert advance.amount_usd == Decimal("50.75") and advance.share.part_id == grace.id
    assert calls(fakes, "pay_share") == []
    [paid] = story.scalars(select(Event).where(Event.type == EventType.ADVANCE_PAID.value)).all()
    assert paid.payload_json["summary"].startswith("OpenStall paid Grace a $50.75 advance for materials")
    assert told(story, "s_grace")[-1].startswith("Your advance of $50.75 for materials has been sent to your")

    # She ships: her share is captured whole, and the payout is the rest.
    play("s_grace", receipt=True)
    play("s_grace", "Yes")

    [paid_share] = calls(fakes, "pay_share")
    assert paid_share.amount_usd == Decimal("203.00") and paid_share.paid_ahead_usd == Decimal("50.75")
    assert share(story, "Grace").status == PartStatus.CAPTURED
    captured = story.scalars(select(Event).where(Event.type == EventType.PART_CAPTURED.value)).all()
    assert captured[-1].payload_json["summary"] == (
        "Grace was paid $203.00 on proof of shipping ($50.75 of it ahead, as OpenStall's advance; $152.25 sent now)"
    )
    assert any("$152.25" in text and "You are paid!" in text for text in told(story, "s_grace"))


def test_her_no_takes_it_back(story, fakes):
    play("s_grace", ASK)
    [declined] = play("s_grace", "No")

    assert declined.startswith("All right: no advance.")
    assert share(story, "Grace").advance_json is None and calls(fakes, "pay_advance") == []


def test_one_advance_per_share(story, fakes):
    play("s_grace", ASK)
    play("s_grace", "Yes")

    [again] = play("s_grace", ASK)

    assert again == "You already have an advance of $50.75 on this order."
    assert len(calls(fakes, "pay_advance")) == 1


def test_amina_s_advance_goes_to_her_bank_through_hyperwallet_simulated(story, fakes):
    """Prompt 52: Hyperwallet (simulated) reaches Pakistan, so Amina's record earns her an advance too."""
    [offer] = play("s_amina", "کیا مجھے سامان کے لیے کچھ پیشگی مل سکتا ہے؟")
    assert "54.00" in offer  # a quarter of her $216.00

    play("s_amina", "ہاں")

    [advance] = calls(fakes, "pay_advance")
    assert (advance.share.payout_rail, advance.amount_usd) == ("hyperwallet", Decimal("54.00"))
    assert share(story, "Amina").advance_json["payout_simulated"] is True
    assert any("Hyperwallet کے ذریعے آپ کے بینک اکاؤنٹ میں" in text for text in told(story, "s_amina"))
    order = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()
    amina = next(part for part in order["parts"] if part["seller"]["id"] == "s_amina")
    assert amina["advance"]["payout_simulated"] is True


def test_who_cannot_have_one(story, fakes):
    # No payout rail reaches her: an override to PayPal, which cannot pay out in Pakistan.
    story.get(Seller, "s_amina").payout_rail = PayoutRailChoice.PAYPAL
    story.commit()
    [no_rail] = play("s_amina", ASK)
    assert no_rail == (
        "آپ کے ملک میں ادائیگی کا انتظام ابھی مکمل نہیں ہوا، اس لیے OpenStall آپ کو پیشگی رقم نہیں بھیج سکتا۔"
    )
    # A score under 0.90.
    passport = story.get(Passport, "s_lucia")
    passport.metrics_json = {**passport.metrics_json, "on_time_rate": 0.5}
    story.commit()
    [low] = play("s_lucia", ASK)
    assert "0.90" in low and "0.78" in low  # 0.4 × 0.5 + 0.3 × (1 − 0.03) + 0.3 × 0.95 = 0.776
    # A maker with no share waiting on her: Noor is not in the story's order.
    [none] = play("s_noor", ASK)
    assert none == "پیشگی رقم اس آرڈر پر ملتی ہے جو آپ نے ابھی بھیجا نہ ہو، اور ابھی آپ کے پاس ایسا کوئی آرڈر نہیں۔"
    assert calls(fakes, "pay_advance") == []


def test_the_order_shows_her_advance(story, fakes):
    play("s_grace", ASK)
    play("s_grace", "Yes")

    order = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()

    grace = next(part for part in order["parts"] if part["seller"]["name"] == "Grace")
    assert grace["advance"]["state"] == "paid" and grace["advance"]["amount_usd"] == "50.75"
