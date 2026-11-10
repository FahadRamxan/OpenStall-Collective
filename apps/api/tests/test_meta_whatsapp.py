"""WhatsApp through Meta's WhatsApp Cloud API: Meta checks the webhook's address with our verify token, only requests
signed with our app secret count, each message is handled once, her photos and voice notes are fetched from Graph API
with our access token, and replies go out through Meta's messages endpoint."""

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from openstall_api.adapters import AdapterRegistry
from openstall_api.chat.handler import WELCOME, WELCOMES
from openstall_api.events import EventType
from openstall_api.fixtures import fixture_photo
from openstall_api.main import app
from openstall_api.meta_whatsapp import (
    FAKE_META_APP_SECRET,
    FAKE_META_VERIFY_TOKEN,
    MetaMessenger,
    meta_signature,
    parse_meta_inbound,
)
from openstall_api.models import ChatMessage, Event, Seller
from openstall_api.whatsapp import MessengerError

client = TestClient(app)
WEBHOOK = "/api/webhooks/whatsapp"
SECRET = "made-up-app-secret"
VERIFY = "made-up-verify-token"
TOKEN = "made-up-meta-token"
PHONE_ID = "155500000000000"
GRAPH = "https://graph.facebook.com/v23.0"


def payload(*messages: dict, statuses: tuple[dict, ...] = ()) -> dict:
    """Meta's webhook body for messages from Amina's number, with her profile name."""
    value: dict = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15551918781", "phone_number_id": PHONE_ID},
        "contacts": [{"profile": {"name": "Amina"}, "wa_id": "923001234567"}],
        "messages": list(messages),
    }
    if statuses:
        value["statuses"] = list(statuses)
    change = {"field": "messages", "value": value}
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA1", "changes": [change]}]}


def text(body: str = "السلام علیکم، میں کشن کور بناتی ہوں", message_id: str = "wamid.1") -> dict:
    return {"from": "923001234567", "id": message_id, "timestamp": "1762800000", "type": "text", "text": {"body": body}}


def post(body: dict, *, secret: str = SECRET, signature: str | None = None):
    raw = json.dumps(body).encode()
    signature = signature if signature is not None else meta_signature(raw, secret)
    headers = {"Content-Type": "application/json", "X-Hub-Signature-256": signature}
    return client.post(WEBHOOK, content=raw, headers=headers)


@pytest.fixture
def meta(use_settings, db):
    """Fake mode with a Meta app's secret and tokens: requests are checked with them, and media fetched with them."""
    use_settings(
        OPENSTALL_MODE="fake", META_APP_SECRET=SECRET, META_WHATSAPP_VERIFY_TOKEN=VERIFY, META_WHATSAPP_TOKEN=TOKEN
    )
    return db


def test_meta_checks_the_address_with_our_verify_token_and_gets_its_challenge_back(meta):
    query = {"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "1158201444"}

    response = client.get(WEBHOOK, params=query)

    assert (response.status_code, response.text) == (200, "1158201444")
    assert client.get(WEBHOOK, params={**query, "hub.verify_token": "someone-elses"}).status_code == 403
    assert client.get(WEBHOOK, params={**query, "hub.mode": "unsubscribe"}).status_code == 403


def test_sandbox_mode_without_a_verify_token_refuses_every_check(use_settings, db):
    use_settings(OPENSTALL_MODE="sandbox")

    query = {"hub.mode": "subscribe", "hub.verify_token": FAKE_META_VERIFY_TOKEN, "hub.challenge": "1"}
    assert client.get(WEBHOOK, params=query).status_code == 403


def test_a_signed_urdu_message_is_stored_and_answered_in_urdu(meta, fakes):
    response = post(payload(text()))

    assert (response.status_code, response.text) == (200, "EVENT_RECEIVED")
    meta.expire_all()
    seller = meta.scalars(select(Seller)).one()
    who = (seller.name, seller.whatsapp_number, seller.country, seller.language)
    assert who == ("Amina", "+923001234567", "PK", "ur")
    [welcome] = fakes.messenger.sent_to("whatsapp:+923001234567")
    assert welcome.text == WELCOMES["ur"]


def test_a_request_without_metas_signature_is_refused_and_recorded(meta, fakes):
    assert post(payload(text()), signature="").status_code == 403
    assert post(payload(text()), secret="someone-elses-secret").status_code == 403

    assert meta.scalar(select(func.count()).select_from(Seller)) == 0
    assert fakes.messenger.calls == []
    refusals = meta.scalars(select(Event).where(Event.type == EventType.SECURITY_REJECTED)).all()
    assert [event.payload_json["summary"] for event in refusals] == [
        "A WhatsApp webhook without Meta's signature was refused"
    ] * 2


def test_in_fake_mode_without_a_meta_app_requests_are_signed_with_the_fake_secret(db, fakes):
    assert post(payload(text("Salaam! I make cushion covers.")), secret=FAKE_META_APP_SECRET).status_code == 200
    assert [sent.text for sent in fakes.messenger.calls] == [WELCOME]


def test_a_message_meta_sends_twice_is_stored_and_answered_once(meta, fakes):
    post(payload(text()))
    post(payload(text()))

    assert meta.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.direction == "inbound")) == 1
    assert len(fakes.messenger.calls) == 1


def test_delivery_and_read_receipts_are_acknowledged_and_nothing_else(meta, fakes):
    receipt = {"id": "wamid.out1", "status": "read", "timestamp": "1762800001", "recipient_id": "923001234567"}

    assert post(payload(statuses=(receipt,))).status_code == 200
    assert meta.scalar(select(func.count()).select_from(ChatMessage)) == 0
    assert fakes.messenger.calls == []


def test_her_photo_and_voice_note_are_fetched_from_graph_with_our_token_and_kept(meta):
    photo = {"from": "923001234567", "id": "wamid.p", "type": "image",
             "image": {"id": "MEDIA-PHOTO", "mime_type": "image/png", "caption": "My cushion"}}
    voice = {"from": "923001234567", "id": "wamid.v", "type": "audio",
             "audio": {"id": "MEDIA-VOICE", "mime_type": "audio/ogg; codecs=opus", "voice": True}}
    with respx.mock() as graph:
        info = graph.get(f"{GRAPH}/MEDIA-PHOTO").respond(
            json={"url": "https://lookaside.fbsbx.com/p", "mime_type": "image/png", "file_size": 120}
        )
        graph.get("https://lookaside.fbsbx.com/p").respond(
            content=fixture_photo(), headers={"Content-Type": "image/png"}
        )
        graph.get(f"{GRAPH}/MEDIA-VOICE").respond(
            json={"url": "https://lookaside.fbsbx.com/v", "mime_type": "audio/ogg; codecs=opus"}
        )
        graph.get("https://lookaside.fbsbx.com/v").respond(content=b"OggS voice", headers={"Content-Type": "audio/ogg"})

        assert post(payload(photo, voice)).status_code == 200

    assert info.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"
    seller_id = meta.scalars(select(Seller.id)).one()
    inbound = [m for m in client.get(f"/api/chats/{seller_id}").json()["messages"] if m["direction"] == "inbound"]
    assert [(m["text"], [item["content_type"] for item in m["media"]]) for m in inbound] == [
        ("My cushion", ["image/png"]),
        (None, ["audio/ogg"]),
    ]
    assert client.get(inbound[0]["media"][0]["url"]).content == fixture_photo()


def test_a_file_meta_cannot_give_us_is_refused_politely(meta, fakes):
    photo = {"from": "923001234567", "id": "wamid.p", "type": "image",
             "image": {"id": "GONE", "mime_type": "image/jpeg"}}
    with respx.mock() as graph:
        graph.get(f"{GRAPH}/GONE").respond(404, json={"error": {"message": "Unsupported get request."}})
        post(payload(photo))

    refusal = fakes.messenger.sent_to("whatsapp:+923001234567")[0]
    assert "could not be fetched from WhatsApp" in refusal.text


def test_buttons_and_captions_count_as_her_words_and_reactions_are_left_out():
    tapped = {"from": "923001234567", "id": "wamid.b", "type": "interactive",
              "interactive": {"type": "button_reply", "button_reply": {"id": "yes", "title": "ہاں"}}}
    reaction = {"from": "923001234567", "id": "wamid.r", "type": "reaction", "reaction": {"emoji": "👍"}}

    [message] = parse_meta_inbound(payload(tapped, reaction))

    heard = (message.message_id, message.sender, message.profile_name, message.text)
    assert heard == ("wamid.b", "+923001234567", "Amina", "ہاں")


def test_the_meta_messenger_sends_text_then_a_voice_note_as_a_link():
    with respx.mock() as graph:
        route = graph.post(f"{GRAPH}/{PHONE_ID}/messages").mock(
            side_effect=[
                httpx.Response(200, json={"messages": [{"id": "wamid.out-text"}]}),
                httpx.Response(200, json={"messages": [{"id": "wamid.out-voice"}]}),
            ]
        )
        sent = MetaMessenger(TOKEN, PHONE_ID, "v23.0", http=httpx.Client()).send(
            "whatsapp:+923001234567", "Your listing is live", ["https://openstall.example/media/uploads/a.mp3"]
        )

    assert (sent.message_id, sent.to) == ("wamid.out-text", "whatsapp:+923001234567")
    first, second = (json.loads(call.request.content) for call in route.calls)
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert first == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "923001234567",
        "type": "text",
        "text": {"body": "Your listing is live", "preview_url": False},
    }
    assert (second["type"], second["audio"]) == ("audio", {"link": "https://openstall.example/media/uploads/a.mp3"})


def test_a_message_meta_refuses_says_why():
    with respx.mock() as graph:
        graph.post(f"{GRAPH}/{PHONE_ID}/messages").respond(
            400, json={"error": {"message": "Recipient phone number not in allowed list", "code": 131030}}
        )
        with pytest.raises(MessengerError, match="Recipient phone number not in allowed list"):
            MetaMessenger(TOKEN, PHONE_ID, "v23.0", http=httpx.Client()).send("+923001234567", "Hello")


def test_sandbox_mode_with_meta_chosen_uses_the_meta_messenger_and_names_its_keys(use_settings):
    registry = AdapterRegistry(
        use_settings(OPENSTALL_MODE="sandbox", WHATSAPP_PROVIDER="meta", META_WHATSAPP_TOKEN=TOKEN,
                     META_WHATSAPP_PHONE_NUMBER_ID=PHONE_ID)
    )

    assert isinstance(registry.messenger, MetaMessenger)
    assert registry.status("messenger") == "real"
    missing = AdapterRegistry(use_settings(OPENSTALL_MODE="sandbox", WHATSAPP_PROVIDER="meta"))
    assert missing.status("messenger") != "real"
