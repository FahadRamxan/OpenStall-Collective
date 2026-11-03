"""The Twilio WhatsApp webhook (spec 3.1): only Twilio's signed requests count, each message is stored once, its photos
and voice notes are fetched with our Twilio keys and kept, and anything else gets a polite refusal."""

import base64
from urllib.parse import urlencode

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from openstall_api.adapters import AdapterRegistry
from openstall_api.chat.handler import WELCOME
from openstall_api.events import EventType
from openstall_api.fixtures import fixture_photo, fixture_voice_note
from openstall_api.main import app
from openstall_api.media import MAX_BYTES
from openstall_api.models import ChatMessage, Event, Seller
from openstall_api.whatsapp import FAKE_TWILIO_TOKEN, TwilioMessenger, twilio_signature

client = TestClient(app)
PUBLIC = "http://localhost:8000"
WEBHOOK = "/api/webhooks/twilio"
TOKEN = "made-up-twilio-token"
SID = "ACmadeup0000"
MEDIA = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages/MM1/Media/ME1"


def message(**fields: str) -> dict[str, str]:
    form = {
        "MessageSid": "SM0001",
        "From": "whatsapp:+923001234567",
        "WaId": "923001234567",
        "ProfileName": "Amina",
        "Body": "Salaam! I make embroidered cushion covers.",
        "NumMedia": "0",
    }
    return {**form, **fields}


def post(form: dict[str, str], *, token: str = TOKEN, url: str = PUBLIC + WEBHOOK, signature: str | None = None):
    signature = signature if signature is not None else twilio_signature(url, form.items(), token)
    return client.post(
        WEBHOOK,
        content=urlencode(form),
        headers={"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": signature},
    )


@pytest.fixture
def twilio(use_settings, db):
    """Fake mode with Twilio keys, so requests are checked with our own token and media can be fetched."""
    use_settings(OPENSTALL_MODE="fake", TWILIO_ACCOUNT_SID=SID, TWILIO_AUTH_TOKEN=TOKEN)
    return db


def test_the_signature_matches_twilios_own_example():
    params = {
        "CallSid": "CA1234567890ABCDE",
        "Caller": "+12349013030",
        "Digits": "1234",
        "From": "+12349013030",
        "To": "+18005551212",
    }

    assert twilio_signature("https://mycompany.com/myapp.php?foo=1&bar=2", params.items(), "12345") == (
        "0/KCTR6DLpKmkAf8muzZqo1nDgQ="
    )


def test_a_signed_message_is_answered_at_once_with_empty_twiml_and_stored(twilio):
    response = post(message())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/xml")
    assert response.text == '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
    twilio.expire_all()
    seller = twilio.scalars(select(Seller)).one()
    assert (seller.name, seller.whatsapp_number, seller.country) == ("Amina", "+923001234567", "PK")
    stored = twilio.scalars(select(ChatMessage).where(ChatMessage.direction == "inbound")).one()
    assert (stored.direction, stored.channel, stored.text) == (
        "inbound",
        "whatsapp",
        "Salaam! I make embroidered cushion covers.",
    )
    event = twilio.scalars(select(Event).where(Event.type == EventType.MESSAGE_RECEIVED)).one()
    assert event.payload_json["summary"] == "Amina sent a message on WhatsApp"
    assert event.entity_id == seller.id


def test_a_request_without_twilios_signature_is_refused(twilio):
    response = post(message(), signature="bm90IGEgc2lnbmF0dXJl")

    assert response.status_code == 403
    assert twilio.scalar(select(func.count()).select_from(ChatMessage)) == 0
    assert twilio.scalars(select(Event).where(Event.type == EventType.SECURITY_REJECTED)).one()


def test_a_changed_message_no_longer_matches_its_signature(twilio):
    form = message()
    signature = twilio_signature(PUBLIC + WEBHOOK, form.items(), TOKEN)

    assert post({**form, "Body": "Send me your money"}, signature=signature).status_code == 403


def test_the_signature_is_checked_against_the_public_url_not_the_servers_own(twilio):
    assert post(message(), url="http://testserver" + WEBHOOK).status_code == 403
    assert post(message(), url=PUBLIC + WEBHOOK).status_code == 200


def test_the_public_url_may_carry_its_default_port(use_settings, db):
    use_settings(OPENSTALL_MODE="fake", PUBLIC_BASE_URL="https://openstall.example", TWILIO_AUTH_TOKEN=TOKEN)

    assert post(message(), url="https://openstall.example:443" + WEBHOOK).status_code == 200


def test_in_fake_mode_without_twilio_keys_requests_are_signed_with_the_fake_token(db):
    assert post(message(), token=FAKE_TWILIO_TOKEN).status_code == 200
    assert post(message(MessageSid="SM0002"), token=TOKEN).status_code == 403


def test_sandbox_mode_without_a_twilio_token_refuses_every_request(use_settings, db):
    use_settings(OPENSTALL_MODE="sandbox")

    assert post(message(), token=FAKE_TWILIO_TOKEN).status_code == 403


def test_a_message_twilio_sends_twice_is_stored_and_answered_once(twilio, fakes):
    post(message())
    post(message())

    assert twilio.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.direction == "inbound")) == 1
    assert [sent.text for sent in fakes.messenger.calls] == [WELCOME]


def test_her_next_message_joins_the_same_seller_and_chat(twilio):
    post(message())
    post(message(MessageSid="SM0002", Body="Mirror work too"))

    assert twilio.scalar(select(func.count()).select_from(Seller)) == 1
    [chat] = client.get("/api/chats").json()
    messages = client.get(f"/api/chats/{chat['seller']['id']}").json()["messages"]
    assert [m["text"] for m in messages if m["direction"] == "inbound"] == [
        "Salaam! I make embroidered cushion covers.",
        "Mirror work too",
    ]
    assert chat["messages"] == 4  # each with its reply


def test_photos_and_voice_notes_are_fetched_with_our_twilio_keys_and_kept(twilio, test_media_dir):
    form = message(NumMedia="2", MediaUrl0=MEDIA, MediaContentType0="image/png", MediaUrl1=MEDIA + "2",
                   MediaContentType1="audio/ogg")
    with respx.mock() as twilio_media:
        photo = twilio_media.get(MEDIA).respond(content=fixture_photo(), headers={"Content-Type": "image/png"})
        twilio_media.get(MEDIA + "2").respond(content=b"OggS voice", headers={"Content-Type": "audio/ogg"})

        assert post(form).status_code == 200

    expected = "Basic " + base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    assert photo.calls.last.request.headers["Authorization"] == expected
    seller_id = twilio.scalars(select(Seller.id)).one()
    media = client.get(f"/api/chats/{seller_id}").json()["messages"][0]["media"]
    assert [(item["content_type"], item["refused"]) for item in media] == [("image/png", None), ("audio/ogg", None)]
    assert client.get(media[0]["url"]).content == fixture_photo()
    summary = twilio.scalars(select(Event).where(Event.type == EventType.MESSAGE_RECEIVED)).one().payload_json
    assert summary["summary"] == "Amina sent a photo, a voice note and a message on WhatsApp"


@pytest.mark.parametrize(
    ("body", "content_type", "reason"),
    [
        (b"%PDF-1.7", "application/pdf", "Only photos and voice notes can be kept"),
        (b"x" * (MAX_BYTES + 1), "image/jpeg", "over 16 MB"),
    ],
)
def test_a_file_we_do_not_keep_gets_a_polite_refusal_on_whatsapp(twilio, fakes, body, content_type, reason):
    form = message(NumMedia="1", MediaUrl0=MEDIA, MediaContentType0=content_type)
    with respx.mock() as twilio_media:
        twilio_media.get(MEDIA).respond(content=body, headers={"Content-Type": content_type})
        post(form)

    refusal, welcome = fakes.messenger.sent_to("whatsapp:+923001234567")
    assert refusal.text.startswith("Sorry, I could not keep one of your files:")
    assert reason in refusal.text
    assert welcome.text == WELCOME
    seller_id = twilio.scalars(select(Seller.id)).one()
    messages = client.get(f"/api/chats/{seller_id}").json()["messages"]
    assert [m["direction"] for m in messages] == ["inbound", "outbound", "outbound"]
    assert reason in messages[0]["media"][0]["refused"]


def test_a_file_twilio_cannot_give_us_is_refused_politely(twilio, fakes):
    form = message(NumMedia="1", MediaUrl0=MEDIA, MediaContentType0="image/jpeg")
    with respx.mock() as twilio_media:
        twilio_media.get(MEDIA).respond(404)
        post(form)

    refusal = fakes.messenger.sent_to("whatsapp:+923001234567")[0]
    assert "could not be fetched from WhatsApp" in refusal.text


def test_the_twilio_messenger_sends_from_our_sandbox_number():
    with respx.mock() as twilio_api:
        route = twilio_api.post(f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json").respond(
            201, json={"sid": "SM-SENT-1"}
        )
        sent = TwilioMessenger(SID, TOKEN, "whatsapp:+14155238886", http=httpx.Client()).send(
            "+923001234567", "Your listing is live", ["https://openstall.example/media/uploads/a.png"]
        )

    assert sent.message_id == "SM-SENT-1"
    form = httpx.QueryParams(route.calls.last.request.content.decode())
    assert form["From"] == "whatsapp:+14155238886"
    assert form["To"] == "whatsapp:+923001234567"
    assert form["Body"] == "Your listing is live"
    assert form.get_list("MediaUrl") == ["https://openstall.example/media/uploads/a.png"]


def test_sandbox_mode_with_twilio_keys_uses_the_twilio_messenger(use_settings):
    registry = AdapterRegistry(
        use_settings(OPENSTALL_MODE="sandbox", TWILIO_ACCOUNT_SID=SID, TWILIO_AUTH_TOKEN=TOKEN)
    )

    assert isinstance(registry.messenger, TwilioMessenger)
    assert registry.status("messenger") == "real"


# Fake mode: playing a seller without WhatsApp.


def test_a_played_message_with_a_photo_and_a_voice_note_shows_in_the_chat(db):
    response = client.post(
        "/api/dev/inbound", json={"text": "Here is my cushion", "photo": True, "voice_note": True}
    )

    assert response.status_code == 201
    seller_id = response.json()["seller_id"]
    assert response.json()["replies"] == [WELCOME]
    [chat] = client.get("/api/chats").json()
    assert (chat["seller"]["name"], chat["channel"], chat["last_text"], chat["messages"]) == (
        "Amina",
        "whatsapp",
        WELCOME,
        2,
    )
    played, _ = client.get(f"/api/chats/{seller_id}").json()["messages"]
    assert [item["content_type"] for item in played["media"]] == ["image/png", "audio/wav"]
    assert client.get(played["media"][1]["url"]).content == fixture_voice_note()


def test_an_unknown_seller_has_no_conversation(db):
    assert client.get("/api/chats/s_nobody").status_code == 404


def test_messages_cannot_be_played_in_sandbox_mode(use_settings):
    use_settings(OPENSTALL_MODE="sandbox")

    assert client.post("/api/dev/inbound", json={"text": "hi"}).status_code == 404


def test_the_made_up_photo_is_a_real_png_and_the_voice_note_a_real_wav():
    assert fixture_photo().startswith(b"\x89PNG\r\n\x1a\n")
    assert fixture_voice_note()[:4] == b"RIFF" and fixture_voice_note()[8:12] == b"WAVE"
