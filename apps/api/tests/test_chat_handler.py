"""One chat handler for WhatsApp and the web (spec 3.1): the same input through either channel is stored the same way
and gets the same replies, so a judge can onboard a seller in the browser."""

from urllib.parse import urlencode

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from openstall_api.chat.handler import WELCOME
from openstall_api.events import EventType
from openstall_api.fixtures import fixture_photo, fixture_voice_note
from openstall_api.main import app
from openstall_api.media import MAX_BYTES
from openstall_api.models import Event, Seller
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
    assert [text for direction, text, _ in on_the_web if direction == "outbound"] == [
        WELCOME,
        "Thank you, I have your photo. Your listing so far: Hand-embroidered cushion cover. Still needed: the price, "
        "how many a week, how many days delivery takes and the city it ships from.",
        "Thank you, I have your voice note and your message. Your listing so far: Hand-embroidered cushion cover, "
        "$18.00 each, 4 a week, from Lahore. Still needed: how many days delivery takes.",
    ]


def test_same_listing_from_both_channels(twilio):
    """Spec checklist: "/seller-chat and WhatsApp produce the same listing from the same input".

    Started in prompt 15, where the chats themselves must match; prompt 17 compares the draft listings; prompt 19 adds
    the published listings.
    """
    for number, (text, files) in enumerate(CONVERSATION):
        send_on_whatsapp("+923001234567", f"SM{number}", text, files)
        send_on_the_web(DEMO_PHONE, text, files)

    assert conversation_of(twilio, whatsapp_number="+923001234567") == conversation_of(twilio, web_chat_id=DEMO_PHONE)
    drafts = [
        client.get(f"/api/chats/{twilio.scalars(select(Seller).filter_by(**by)).one().id}").json()["draft"]
        for by in ({"whatsapp_number": "+923001234567"}, {"web_chat_id": DEMO_PHONE})
    ]
    assert drafts[0] == drafts[1]
    assert (drafts[0]["title"], drafts[0]["price_usd"], drafts[0]["missing"]) == (
        "Hand-embroidered cushion cover",
        "18.00",
        ["ship_days"],
    )


def test_a_web_seller_is_known_by_her_demo_phone_and_labelled_web_chat(db):
    first = send_on_the_web(DEMO_PHONE, "Hello", [])
    second = send_on_the_web(DEMO_PHONE, "I make quilts", [(fixture_photo(), "image/png")])

    assert first.status_code == second.status_code == 200
    assert first.json()["replies"] == [WELCOME]
    assert second.json()["replies"] == [
        "Thank you, I have your photo and your message. Your listing so far: Hand-embroidered cushion cover. Still "
        "needed: the price, how many a week, how many days delivery takes and the city it ships from."
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
