"""One chat handler for WhatsApp and the web (spec 3.1): the same input through either channel is stored the same way
and gets the same replies, so a judge can onboard a seller in the browser."""

from decimal import Decimal
from urllib.parse import urlencode

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from openstall_agents.listing_reader import QUESTIONS
from openstall_api.chat.handler import PAY_ANSWERS, THANKS, WELCOME, WELCOMES, asked_about, turn
from openstall_api.chat.voice import Heard, language_hint, written_language
from openstall_api.events import EventType
from openstall_api.fixtures import fixture_photo, fixture_voice_note
from openstall_api.main import app
from openstall_api.media import MAX_BYTES
from openstall_api.models import Channel, Event, Product, ProductStatus, Seller
from openstall_api.whatsapp import twilio_signature

client = TestClient(app)
TOKEN = "made-up-twilio-token"
SID = "ACmadeup0000"
WEBHOOK = "http://localhost:8000/api/webhooks/twilio"
DEMO_PHONE = "demo-7f3a9c21"

# What a seller sends, message by message: words, and files as (bytes, type).
CONVERSATION = [
    ("Salaam! I make hand-embroidered cushion covers.", []),
    ("", [(fixture_photo(), "image/png")]),
    ("$18 each, 4 a week. Ships from Lahore.", [(fixture_voice_note(), "audio/wav")]),
]


@pytest.fixture
def twilio(use_settings, db):
    use_settings(OPENSTALL_MODE="fake", TWILIO_ACCOUNT_SID=SID, TWILIO_AUTH_TOKEN=TOKEN)
    return db


def send_on_whatsapp(number: str, sid: str, text: str, files: list[tuple[bytes, str]]) -> None:
    form = {"MessageSid": sid, "From": f"whatsapp:{number}", "WaId": number.lstrip("+"), "Body": text}
    form["NumMedia"] = str(len(files))
    with respx.mock() as twilio_media:
        for index, (data, kind) in enumerate(files):
            url = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages/{sid}/Media/ME{index}"
            form[f"MediaUrl{index}"], form[f"MediaContentType{index}"] = url, kind
            twilio_media.get(url).respond(content=data, headers={"Content-Type": kind})
        response = client.post(
            "/api/webhooks/twilio",
            content=urlencode(form),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Twilio-Signature": twilio_signature(WEBHOOK, form.items(), TOKEN),
            },
        )
    assert response.status_code == 200


def send_on_the_web(demo_phone: str, text: str, files: list[tuple[bytes, str]]):
    uploads = [("files", (f"file{index}", data, kind)) for index, (data, kind) in enumerate(files)]
    return client.post("/api/seller-chat/messages", data={"sender": demo_phone, "text": text}, files=uploads or None)


def conversation_of(db, **seller_by) -> list[tuple[str, str | None, list[tuple[str, str | None]]]]:
    """A seller's whole chat as (direction, text, [(media type, kept file)]), in order."""
    db.expire_all()
    seller = db.scalars(select(Seller).filter_by(**seller_by)).one()
    messages = client.get(f"/api/chats/{seller.id}").json()["messages"]
    return [
        (
            message["direction"],
            message["text"],
            [(item["content_type"], (item["url"] or "").rsplit("/", 1)[-1] or None) for item in message["media"]],
        )
        for message in messages
    ]


def test_same_input_through_whatsapp_and_the_web_gives_the_same_messages_and_replies(twilio):
    for number, (text, files) in enumerate(CONVERSATION):
        send_on_whatsapp("+923001234567", f"SM{number}", text, files)
        send_on_the_web(DEMO_PHONE, text, files)

    on_whatsapp = conversation_of(twilio, whatsapp_number="+923001234567")
    on_the_web = conversation_of(twilio, web_chat_id=DEMO_PHONE)

    assert on_whatsapp == on_the_web
    # Answered in English until her Urdu voice note saves her language, then in Urdu.
    assert [text for direction, text, _ in on_the_web if direction == "outbound"] == [
        WELCOME,
        f"Thank you. Your listing so far: Hand-embroidered cushion cover.\n\n{QUESTIONS['price_usd']}",
        "شکریہ۔ اب تک آپ کا اشتہار: ہاتھ کی کڑھائی والا کشن کور، 18.00 ڈالر فی عدد، ہفتے میں 4، Lahore سے۔\n\nآپ کا "
        "پارسل امریکہ میں خریدار تک کتنے دن میں پہنچتا ہے؟",
    ]


def test_same_listing_from_both_channels(twilio):
    """Spec checklist: "/seller-chat and WhatsApp produce the same listing from the same input".

    Started in prompt 15, where the chats themselves must match; prompt 17 compares the draft listings; prompt 19 the
    published listings, once she has answered every question and said yes.
    """
    channels = ({"whatsapp_number": "+923001234567"}, {"web_chat_id": DEMO_PHONE})
    for number, (text, files) in enumerate(CONVERSATION):
        send_on_whatsapp("+923001234567", f"SM{number}", text, files)
        send_on_the_web(DEMO_PHONE, text, files)

    assert conversation_of(twilio, whatsapp_number="+923001234567") == conversation_of(twilio, web_chat_id=DEMO_PHONE)
    sellers = [twilio.scalars(select(Seller).filter_by(**by)).one() for by in channels]
    drafts = [client.get(f"/api/chats/{seller.id}").json()["draft"] for seller in sellers]
    assert drafts[0] == drafts[1]
    assert (drafts[0]["title"], drafts[0]["price_usd"], drafts[0]["missing"], drafts[0]["asked"]) == (
        "Hand-embroidered cushion cover",
        "18.00",
        ["ship_days", "floor_price_usd", "min_lead_days"],
        "ship_days",
    )

    for number, text in enumerate(("9", "15", "5", "ہاں"), start=len(CONVERSATION)):
        send_on_whatsapp("+923001234567", f"SM{number}", text, [])
        send_on_the_web(DEMO_PHONE, text, [])

    # The same chats, each with her own stall's link at the end.
    chats = [
        [(direction, (text or "").replace(seller.id, "<her id>"), media) for direction, text, media in chat]
        for seller, chat in zip(sellers, (conversation_of(twilio, **by) for by in channels), strict=True)
    ]
    assert chats[0] == chats[1]
    assert chats[0][-1][1].endswith("/stall/<her id>")
    twilio.expire_all()
    published = [twilio.scalars(select(Product).where(Product.seller_id == seller.id)).one() for seller in sellers]
    listed = [
        {
            "status": product.status,
            "title": product.title,
            "description": product.description,
            "category": product.category,
            "variants": product.variants_json,
            "price_usd": product.price_usd,
            "capacity_per_week": product.capacity_per_week,
            "ship_days": product.ship_days,
            "ship_from_city": product.ship_from_city,
            "photos": product.photos_json,
            "source_text": product.source_text,
            "policy": {name: value for name, value in (product.seller.policy_json or {}).items() if name != "seller_id"},
        }
        for product in published
    ]
    assert listed[0] == listed[1]
    assert (listed[0]["status"], listed[0]["price_usd"], listed[0]["ship_days"], listed[0]["policy"]) == (
        ProductStatus.LIVE,
        Decimal("18.00"),
        9,
        {"floor_price_usd": "15.00", "max_discount_pct": "16.67", "capacity_per_week": 4, "min_lead_days": 5},
    )


def test_a_web_seller_is_known_by_her_demo_phone_and_labelled_web_chat(db):
    first = send_on_the_web(DEMO_PHONE, "Hello", [])
    second = send_on_the_web(DEMO_PHONE, "I make quilts", [(fixture_photo(), "image/png")])

    assert first.status_code == second.status_code == 200
    assert first.json()["replies"] == [WELCOME]
    assert second.json()["replies"] == [
        f"Thank you. Your listing so far: Hand-embroidered cushion cover.\n\n{QUESTIONS['price_usd']}"
    ]
    assert first.json()["seller_id"] == second.json()["seller_id"]
    [chat] = client.get("/api/chats").json()
    assert (chat["seller"]["name"], chat["channel"], chat["messages"]) == ("Web seller 9C21", "web", 4)
    received = db.scalars(select(Event).where(Event.type == EventType.MESSAGE_RECEIVED))
    assert [event.payload_json["summary"] for event in received] == [
        "Web seller 9C21 sent a message in the web chat",
        "Web seller 9C21 sent a photo and a message in the web chat",
    ]


def test_each_demo_phone_is_its_own_seller(db):
    one = send_on_the_web("demo-phone-one", "Hello", []).json()
    two = send_on_the_web("demo-phone-two", "Hello", []).json()

    assert one["seller_id"] != two["seller_id"]
    assert two["replies"] == [WELCOME]


def test_a_file_the_web_chat_cannot_keep_is_refused_politely(db):
    response = send_on_the_web(DEMO_PHONE, "", [(b"%PDF-1.7", "application/pdf")])

    refusal, welcome = response.json()["replies"]
    assert refusal.startswith("Sorry, I could not keep one of your files: Only photos and voice notes can be kept")
    assert welcome == WELCOME


def test_a_web_upload_over_16_mb_is_refused_without_keeping_it(db, test_media_dir):
    response = send_on_the_web(DEMO_PHONE, "big", [(b"x" * (MAX_BYTES + 1), "image/jpeg")])

    assert "over 16 MB" in response.json()["replies"][0]
    assert not test_media_dir.exists() or not any(test_media_dir.iterdir())


@pytest.mark.parametrize(
    ("data", "files", "problem"),
    [
        ({"sender": DEMO_PHONE, "text": "  "}, None, "Write a message or attach"),
        ({"sender": "../etc", "text": "hi"}, None, "sender"),
        ({"sender": DEMO_PHONE, "text": "hi"}, [("files", (f"f{n}", b"x", "image/png")) for n in range(6)], "at most 5"),
    ],
)
def test_the_web_chat_refuses_what_it_cannot_take(db, data, files, problem):
    response = client.post("/api/seller-chat/messages", data=data, files=files)

    assert response.status_code == 422
    assert problem in response.text


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("السلام علیکم، میں کشن کور بناتی ہوں", "ur"),
        ("नमस्ते, मैं कुशन कवर बनाती हूँ", "hi"),
        ("مرحبا، أصنع أغطية الوسائد", None),  # Arabic letters alone could be Arabic or Persian: not guessed
        ("Hola, hago fundas de cojín", None),  # Latin letters could be English or Spanish: not guessed
        ("", None),
    ],
)
def test_the_language_of_her_typed_words_when_the_script_alone_says_it(text, language):
    assert written_language(text) == language


@pytest.mark.parametrize(
    ("text", "country", "language"),
    [
        ("السلام علیکم", "PK", "ur"),  # no Urdu-only letter, but Arabic script from Pakistan is Urdu
        ("السلام علیکم", None, None),
        ("السلام علیکم", "SA", None),  # from Saudi Arabia it could be Arabic
        ("Salaam! I make cushion covers.", "PK", None),  # she writes English: she is answered in English
    ],
)
def test_arabic_script_from_a_country_that_writes_urdu_in_it_is_urdu(text, country, language):
    assert written_language(text, country) == language


def test_a_maker_in_pakistan_who_greets_in_urdu_is_welcomed_in_urdu(twilio):
    """"السلام علیکم" has no letter only Urdu writes; from a Pakistani number it is still Urdu. Found on the first
    real WhatsApp message, through Meta, on November 10. A greeting alone does not decide her language, though: the
    tester went on in English, and was answered in Urdu."""
    send_on_whatsapp("+923145550000", "SM_pk_1", "السلام علیکم", [])

    twilio.expire_all()
    seller = twilio.scalars(select(Seller).filter_by(whatsapp_number="+923145550000")).one()
    assert (seller.language, seller.country) == (None, "PK")
    [message] = [m for m in client.get(f"/api/chats/{seller.id}").json()["messages"] if m["direction"] == "outbound"]
    assert message["text"] == WELCOMES["ur"]


def test_after_an_urdu_greeting_her_english_question_is_answered_in_english_with_how_it_works(twilio):
    """"Who are you?" and "what can you do?" were answered with thanks for a message, in Urdu: now they get how it
    works, in the language she asked in."""
    send_on_whatsapp("+923145550001", "SM_pk_2", "السلام علیکم۔", [])
    send_on_whatsapp("+923145550001", "SM_pk_3", "Hello what can you do or what do you do", [])

    twilio.expire_all()
    seller = twilio.scalars(select(Seller).filter_by(whatsapp_number="+923145550001")).one()
    replies = [m["text"] for m in client.get(f"/api/chats/{seller.id}").json()["messages"] if m["direction"] == "outbound"]
    assert replies == [WELCOMES["ur"], WELCOME]
    assert seller.language is None


@pytest.mark.parametrize(
    ("question", "topic"),
    [
        ("Who are you?", "about"),
        ("Hello what can you do or what do you do", "about"),
        ("Help", "about"),
        ("آپ کیا کرتے ہیں؟", "about"),
        ("یہ کیا ہے", "about"),
        ("आप कौन हैं?", "about"),
        ("¿Qué haces?", "about"),
        ("aap kya karte ho", "about"),
        ("Is it free?", "about"),  # no topic of its own: told what OpenStall is
        ("How do I get paid?", "pay"),
        ("پیسے کب ملیں گے؟", "pay"),
        ("paise kab milenge", "pay"),
        ("भुगतान कैसे होगा?", "pay"),
        ("¿Cómo me pagan?", "pay"),
        ("Who buys these?", "buyers"),
        ("خریدار کون ہیں؟", "buyers"),
        ("What can I sell?", "sell"),
        ("میں کیا بیچ سکتی ہوں؟", "sell"),
    ],
)
def test_her_questions_about_openstall_are_answered_by_topic(question, topic):
    assert asked_about(question) == topic


@pytest.mark.parametrize("words", ["I make cushion covers", "18 dollars", "میں کشن کور بناتی ہوں", "helpful hint", "9"])
def test_her_own_words_are_not_questions_about_openstall(words):
    assert asked_about(words) is None


def test_while_she_answers_a_question_a_question_shaped_answer_is_her_answer():
    assert asked_about("How about 15 dollars?", answering=True) is None
    assert asked_about("How do I get paid?", answering=True) == "pay"  # a question with a topic is still answered


def test_her_question_about_payment_is_answered_in_her_language_and_her_listing_goes_on(twilio):
    send_on_whatsapp("+923145550002", "SM_pk_4", "السلام علیکم", [])
    send_on_whatsapp("+923145550002", "SM_pk_5", "پیسے کب ملیں گے؟", [])

    twilio.expire_all()
    seller = twilio.scalars(select(Seller).filter_by(whatsapp_number="+923145550002")).one()
    replies = [m for m in client.get(f"/api/chats/{seller.id}").json()["messages"] if m["direction"] == "outbound"]
    assert [reply["text"] for reply in replies] == [WELCOMES["ur"], PAY_ANSWERS["ur"]]
    assert replies[1]["english"] == PAY_ANSWERS["en"]


def test_a_maker_outside_pakistan_who_writes_in_urdu_is_answered_in_urdu(twilio):
    """A number from Saudi Arabia says nothing about her language; her words in Urdu do, so the welcome is in Urdu
    (with its English line) and Urdu is saved on her profile, the hint for her voice notes from then on."""
    send_on_whatsapp("+966551230000", "SM_ur_1", "السلام علیکم، میں کشن کور بناتی ہوں", [])

    twilio.expire_all()
    seller = twilio.scalars(select(Seller).filter_by(whatsapp_number="+966551230000")).one()
    assert (seller.language, seller.country) == ("ur", None)
    [message] = [m for m in client.get(f"/api/chats/{seller.id}").json()["messages"] if m["direction"] == "outbound"]
    assert message["text"] == WELCOMES["ur"]
    assert message["english"] == WELCOMES["en"]
    assert language_hint(Channel.WHATSAPP, "+966551230000") == "ur"


@pytest.mark.parametrize("language", ["en", "ur", "hi", "es"])
def test_with_nothing_to_ask_yet_she_is_thanked_in_her_own_language(language):
    """A voice note before her listing can be read (no draft yet, no live listing) is answered in her language, not
    always in English: the reply a seller gets in sandbox mode while her listing cannot be read."""
    voice_note = [{"content_type": "audio/ogg", "key": "uploads/note.ogg"}]

    replies = turn(None, False, "", voice_note, Heard(texts=("her words",), language=language), language=language)

    expected = THANKS[language].format(what="your voice note")
    assert [reply.text for reply in replies] == [expected]
    assert ("Thank you, I have your voice note." in expected) == (language == "en")

