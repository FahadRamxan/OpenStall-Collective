"""Snap the receipt, get paid (prompt 32, spec 3.6): a maker whose share PayPal holds photographs her courier
receipt; the model reads the courier and the tracking number; she confirms them in her language; then, and only
then, her share is captured and paid, and she is told. A maker no payout rail reaches keeps her tracking unpaid."""

import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from sqlalchemy import select

from openstall_agents.adapters import LLMError
from openstall_api.chat.handler import WELCOMES
from openstall_api.events import EventType
from openstall_api.fixtures import demo_shipment, fixture_photo, fixture_receipt
from openstall_api.main import app
from openstall_api.models import ChatMessage, ChatSession, Direction, Event, Order, OrderPart, OrderStatus, PartStatus, Seller
from openstall_api.proof import is_no, is_yes, typed_tracking
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order
from openstall_api.storefront import storefront
from openstall_paypal import PaymentUnavailable

client = TestClient(app)
TODAY = date(2026, 11, 10)
PRIYA_PHONE = "+15550100002"  # fictional (555-01xx), never a real phone
INDIA_POST, PRIYA_TRACKING = demo_shipment("IN")  # India Post, EE123456789IN
TCS, AMINA_TRACKING = demo_shipment("PK")  # TCS, 7712345678


# Yes, no, and a typed number, in the makers' languages


@pytest.mark.parametrize(
    "text", ["yes", "Yes!", "YES", "ok", "👍", "haan ji", "ہاں", "جی ہاں", "हाँ", "हां जी", "Sí", "si", "claro", "yes it is"]
)
def test_yes_in_each_language(text):
    assert is_yes(text)


@pytest.mark.parametrize("text", ["no", "No.", "nahi", "نہیں", "नहीं", "incorrecto", "yes 7712345678", "not yet sure why"])
def test_not_yes(text):
    assert not is_yes(text)


@pytest.mark.parametrize("text", ["no", "No!", "nahi", "نہیں", "नहीं", "está mal", "wrong"])
def test_no_in_each_language(text):
    assert is_no(text)


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("EE987654321IN", "EE987654321IN"),
        ("EE 987654321 IN", "EE987654321IN"),
        ("7712 3456 78", "7712345678"),
        ("my number is 7712345678", "7712345678"),
        ("ٹریکنگ نمبر 7712345678 ہے", "7712345678"),
        ("yes 7712345678", "7712345678"),
        ("YES 7712345678", "7712345678"),
        ("yes", None),
        ("thank you", None),
        ("12 34", None),
    ],
)
def test_a_typed_tracking_number_is_found_without_gluing_words_to_it(text, number):
    assert typed_tracking(text) == number


# The story's order, reserved


@pytest.fixture
def story(db):
    """The story's order (Amina 12, Priya 11, Lucía 10, Grace 7; due December 10, Chicago), approved on the simulated
    PayPal page and reserved: PayPal holds it, and each maker has been told. Returns the database session."""
    seed(db, with_amina=True)
    seed_demo_order(db, TODAY)
    db.commit()
    token = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve").status_code == 200
    return db


def play(seller_id: str, text: str = "", receipt: bool = False) -> list[str]:
    """As if this maker wrote to OpenStall (fake mode), and OpenStall's replies."""
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


def captures(fakes) -> int:
    return sum(1 for name, _ in fakes.payment_gateway.calls if name == "pay_share")


def test_priya_sends_her_receipt_and_is_asked_in_hindi_to_confirm_what_was_read(story, fakes):
    [reply] = play("s_priya", receipt=True)

    assert reply == (
        "धन्यवाद! मैंने ऑर्डर ord_demo (11 × Mirror-work embroidered cushion cover) की कूरियर रसीद पढ़ ली है:\n"
        f"कूरियर: {INDIA_POST}\nट्रैकिंग नंबर: {PRIYA_TRACKING}\n\n"
        "क्या यह सही है? \"हाँ\" लिखें, या सही ट्रैकिंग नंबर लिख दें।"
    )
    priya = part_of(story, "Priya")
    # Nothing is paid, and no tracking is set, on a reading alone.
    assert (priya.status, priya.tracking_number, priya.carrier) == (PartStatus.AUTHORIZED, None, None)
    assert priya.proof_json["state"] == "awaiting_confirmation"
    assert priya.proof_json["photo_url"].startswith("/media/uploads/")
    assert (priya.proof_json["carrier"], priya.proof_json["tracking_number"]) == (INDIA_POST, PRIYA_TRACKING)
    assert priya.proof_json["read_by"] == "the stand-in model of test mode"
    [read] = events(story, EventType.TRACKING_READ)
    assert read.payload_json["summary"] == (
        f"Priya's courier receipt for order ord_demo reads {INDIA_POST}, tracking {PRIYA_TRACKING} (read by the "
        "stand-in model of test mode). She is asked to confirm it"
    )
    assert captures(fakes) == 0


def test_her_yes_confirms_the_tracking_then_she_is_paid_and_told(story, fakes):
    play("s_priya", receipt=True)

    [reply] = play("s_priya", "हाँ")

    assert reply == (
        f"धन्यवाद! आपका ट्रैकिंग नंबर {PRIYA_TRACKING} सेव हो गया है, और आपके $176.00 का भुगतान अभी किया जा रहा है।"
    )
    priya = part_of(story, "Priya")
    assert (priya.tracking_number, priya.carrier) == (PRIYA_TRACKING, INDIA_POST)
    assert priya.status == PartStatus.CAPTURED  # paid on proof, after the answer
    assert priya.proof_json["state"] == "confirmed"
    assert captures(fakes) == 1
    [confirmed] = events(story, EventType.TRACKING_CONFIRMED)
    assert confirmed.payload_json["summary"] == (
        f"Priya confirmed her tracking for order ord_demo: {INDIA_POST} {PRIYA_TRACKING}"
    )
    [paid] = events(story, EventType.PART_CAPTURED)
    assert paid.payload_json["summary"] == "Priya was paid $176.00 on proof of shipping"
    assert chat_texts(story, "s_priya")[-1] == (
        "आपको भुगतान हो गया! ऑर्डर ord_demo के $176.00 आपके PayPal खाते में भेज दिए गए हैं।\n"
        "(टेस्ट मोड: नकली PayPal, कोई असली पैसा नहीं भेजा गया।)"
    )
    told = [event.payload_json["summary"] for event in events(story, EventType.MESSAGE_SENT)]
    assert "Priya was told in the web chat, in Hindi, that she is paid for order ord_demo" in told
    story.expire_all()
    assert story.get(Order, DEMO_ORDER_ID).status == OrderStatus.PARTLY_SHIPPED


def test_the_receipt_page_and_the_buyer_agent_see_her_tracking(story):
    play("s_priya", receipt=True)
    pending = next(part for part in client.get(f"/api/orders/{DEMO_ORDER_ID}").json()["parts"] if part["seller"]["name"] == "Priya")
    assert (pending["tracking_number"], pending["proof"]["state"]) == (None, "awaiting_confirmation")
    assert pending["proof"]["tracking_number"] == PRIYA_TRACKING

    play("s_priya", "yes")

    order = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()
    priya = next(part for part in order["parts"] if part["seller"]["name"] == "Priya")
    assert (priya["status"], priya["carrier"], priya["tracking_number"]) == ("captured", INDIA_POST, PRIYA_TRACKING)
    assert priya["proof"]["state"] == "confirmed"
    assert priya["proof"]["photo_url"].startswith("/media/uploads/")
    status = get_order_status(DEMO_ORDER_ID)
    share = next(share for share in status["shares"] if share["seller_name"] == "Priya")
    assert (share["carrier"], share["tracking_number"], share["status"]) == (INDIA_POST, PRIYA_TRACKING, "captured")


def test_amina_confirms_but_is_not_paid_because_no_payout_rail_reaches_pakistan_yet(story, fakes):
    [question] = play("s_amina", receipt=True)
    assert f"ٹریکنگ نمبر: {AMINA_TRACKING}" in question and f"کورئیر: {TCS}" in question

    [reply] = play("s_amina", "جی ہاں")

    assert reply.startswith(f"شکریہ! آپ کا ٹریکنگ نمبر {AMINA_TRACKING} محفوظ ہو گیا ہے۔")
    assert "216.00 ڈالر PayPal کے پاس محفوظ ہیں" in reply
    amina = part_of(story, "Amina")
    assert (amina.tracking_number, amina.status) == (AMINA_TRACKING, PartStatus.AUTHORIZED)  # tracked, not captured
    assert captures(fakes) == 0
    assert events(story, EventType.PART_CAPTURED) == []


def test_a_wrong_reading_is_put_right_by_typing_the_number(story):
    play("s_priya", receipt=True)

    [again] = play("s_priya", "नहीं")
    assert again == "कृपया सही ट्रैकिंग नंबर यहाँ लिखें, या रसीद की ज़्यादा साफ़ फ़ोटो भेजें।"
    assert part_of(story, "Priya").proof_json["state"] == "awaiting_number"

    [check] = play("s_priya", "EE 987654321 IN")
    assert "ट्रैकिंग नंबर: EE987654321IN" in check

    play("s_priya", "हाँ")
    priya = part_of(story, "Priya")
    assert (priya.tracking_number, priya.status) == ("EE987654321IN", PartStatus.CAPTURED)
    assert priya.proof_json["source"] == "typed"


def test_anything_else_while_she_is_asked_gets_the_question_again(story):
    [question] = play("s_lucia", receipt=True)

    [again] = play("s_lucia", "¿Cuándo me pagan?")

    assert again == question
    assert "¿Es correcto? Responde SÍ" in question
    assert part_of(story, "Lucía").tracking_number is None


def test_when_the_model_cannot_read_the_photo_she_is_asked_to_type_the_number(story, fakes):
    def down(prompt, *, schema, system=None, images=()):
        raise LLMError("the model could not be reached")

    fakes.llm.generate_json = down

    [reply] = play("s_grace", receipt=True)

    assert reply == (
        "Thank you for the photo of your courier receipt for order ord_demo. I could not read the tracking number: "
        "please type it here, or send a clearer photo."
    )
    grace = part_of(story, "Grace")
    assert grace.proof_json["state"] == "awaiting_number"
    assert grace.proof_json["read_error"] == "the model could not be reached"
    [read] = events(story, EventType.TRACKING_READ)
    assert "could not be read" in read.payload_json["summary"]

    del fakes.llm.generate_json
    [check] = play("s_grace", "9400 1118 9922 3197 4284 90")
    assert "Tracking number: 9400111899223197428490" in check
    assert "Courier: not printed" in check
    play("s_grace", "yes")
    assert part_of(story, "Grace").status == PartStatus.CAPTURED


def test_a_photo_that_is_not_a_receipt_gets_the_chats_usual_answer(story, fakes):
    story.get(Seller, "s_priya").whatsapp_number = PRIYA_PHONE
    story.commit()

    response = client.post(
        "/api/dev/inbound", json={"sender": PRIYA_PHONE, "profile_name": "Priya", "photo": True}
    )

    assert response.json()["replies"] == [WELCOMES["hi"]]  # her first WhatsApp message: the usual welcome, in Hindi
    assert [call for call in fakes.llm.calls if "courier_receipt" in call.prompt]  # the model was asked, and said no
    assert part_of(story, "Priya").proof_json is None
    assert events(story, EventType.TRACKING_READ) == []


def test_no_model_looks_at_a_photo_from_a_maker_with_nothing_to_prove(db, fakes):
    seed(db, with_amina=True)
    seed_demo_order(db, TODAY)  # a draft: nothing is reserved, so nobody waits for proof
    db.commit()

    play("s_priya", receipt=True)

    assert [call for call in fakes.llm.calls if "courier_receipt" in call.prompt] == []
    assert events(db, EventType.TRACKING_READ) == []


def test_on_whatsapp_the_questions_and_the_payment_message_go_out_on_whatsapp(story, fakes):
    story.get(Seller, "s_priya").whatsapp_number = PRIYA_PHONE
    story.commit()
    usps, tracking = demo_shipment("US")  # her number is American, so the made-up receipt is USPS
    fakes.messenger.calls.clear()

    client.post("/api/dev/inbound", json={"sender": PRIYA_PHONE, "profile_name": "Priya", "receipt": True})
    client.post("/api/dev/inbound", json={"sender": PRIYA_PHONE, "profile_name": "Priya", "text": "हाँ"})

    sent = [message.text for message in fakes.messenger.sent_to(f"whatsapp:{PRIYA_PHONE}")]
    assert f"ट्रैकिंग नंबर: {tracking}" in sent[0] and f"कूरियर: {usps}" in sent[0]
    assert sent[1].startswith(f"धन्यवाद! आपका ट्रैकिंग नंबर {tracking} सेव हो गया है")
    assert sent[2].startswith("आपको भुगतान हो गया!")
    assert len(sent) == 3
    assert part_of(story, "Priya").status == PartStatus.CAPTURED


def test_a_payment_that_does_not_go_through_is_said_and_tried_again_on_her_yes(story, fakes):
    gateway = fakes.payment_gateway
    real_pay = gateway.pay_share
    failures = iter([PaymentUnavailable("SERVICE_UNAVAILABLE", "PayPal did not answer", outcome_unknown=False)])

    def flaky(share):
        failure = next(failures, None)
        if failure is not None:
            raise failure
        return real_pay(share)

    gateway.pay_share = flaky
    play("s_priya", receipt=True)
    play("s_priya", "हाँ")

    assert chat_texts(story, "s_priya")[-1] == (
        "आपका ट्रैकिंग नंबर सेव है, लेकिन भुगतान अभी नहीं हो पाया। हम फिर से कोशिश करेंगे; अभी कोशिश करने के लिए "
        "यहाँ \"हाँ\" लिखें।"
    )
    priya = part_of(story, "Priya")
    assert (priya.tracking_number, priya.status) == (PRIYA_TRACKING, PartStatus.AUTHORIZED)

    [retrying] = play("s_priya", "हाँ")

    assert retrying == f"ऑर्डर ord_demo का आपका ट्रैकिंग नंबर पहले से सेव है। हम अभी फिर से भुगतान की कोशिश कर रहे हैं।"
    assert part_of(story, "Priya").status == PartStatus.CAPTURED
    assert chat_texts(story, "s_priya")[-1].startswith("आपको भुगतान हो गया!")


def test_saying_yes_again_after_she_is_paid_pays_nothing_more(story, fakes):
    play("s_priya", receipt=True)
    play("s_priya", "yes")

    replies = play("s_priya", "yes")

    assert captures(fakes) == 1
    assert replies == ["Thank you, I have your message. Send more photos, or tell me the price and how many you can make each week."]


def test_a_web_chat_maker_sends_her_receipt_from_her_demo_phone(story, fakes):
    """The real web chat endpoint, for a maker who chats from her browser."""
    story.get(Seller, "s_priya").web_chat_id = "demo-0123456789ab"
    story.commit()
    receipt = fixture_receipt(INDIA_POST, PRIYA_TRACKING)

    first = client.post(
        "/api/seller-chat/messages",
        data={"sender": "demo-0123456789ab", "text": ""},
        files=[("files", ("receipt.png", receipt, "image/png"))],
    )
    second = client.post("/api/seller-chat/messages", data={"sender": "demo-0123456789ab", "text": "हाँ"})

    assert f"ट्रैकिंग नंबर: {PRIYA_TRACKING}" in first.json()["replies"][0]
    assert second.json()["replies"][0].startswith(f"धन्यवाद! आपका ट्रैकिंग नंबर {PRIYA_TRACKING}")
    assert part_of(story, "Priya").status == PartStatus.CAPTURED


def test_only_seeded_makers_without_a_phone_can_be_played_and_only_in_test_mode(story, use_settings):
    assert client.get("/api/chats/s_priya").json()["playable"] is True
    story.get(Seller, "s_priya").whatsapp_number = PRIYA_PHONE
    story.commit()
    assert client.get("/api/chats/s_priya").json()["playable"] is False
    assert client.post("/api/dev/sellers/s_nobody/messages", json={"text": "hi"}).status_code == 404
    assert client.post("/api/dev/sellers/s_grace/messages", json={"text": " "}).status_code == 422

    use_settings(OPENSTALL_MODE="sandbox")

    assert client.get("/api/chats/s_grace").json()["playable"] is False
    assert client.post("/api/dev/sellers/s_grace/messages", json={"receipt": True}).status_code == 404


def test_fake_modes_receipt_photo_is_a_png_with_its_print_in_a_text_chunk():
    receipt = fixture_receipt(INDIA_POST, PRIYA_TRACKING)
    assert receipt.startswith(b"\x89PNG\r\n\x1a\n") and b"tEXt" in receipt
    assert PRIYA_TRACKING.encode() in receipt
    assert fixture_receipt(INDIA_POST, PRIYA_TRACKING) == receipt  # the same bytes every time
    assert receipt != fixture_photo()


def get_order_status(order_id: str) -> dict:
    async def go():
        async with Client(storefront) as mcp:
            return await mcp.call_tool("get_order_status", {"order_id": order_id})

    result = asyncio.run(go())
    assert not result.is_error, result.content
    return result.structured_content
