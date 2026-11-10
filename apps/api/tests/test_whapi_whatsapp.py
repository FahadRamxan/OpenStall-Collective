"""WhatsApp through Whapi.Cloud: only requests to our secret address from our channel count, our own messages that
Whapi sends back are left out, each message is handled once, her photos and voice notes are fetched from Whapi with
the channel's token, replies go out through Whapi's messages endpoints, and what became of each reply is kept."""

import json

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from openstall_api.adapters import AdapterRegistry
from openstall_api.chat.handler import WELCOME, WELCOMES
from openstall_api.events import EventType
from openstall_api.fixtures import fixture_photo
from openstall_api.main import app
from openstall_api.models import ChatMessage, Event, Seller
from openstall_api.whapi_whatsapp import (
    FAKE_WHAPI_WEBHOOK_SECRET,
    WhapiMessenger,
    parse_whapi_inbound,
    parse_whapi_statuses,
)
from openstall_api.whatsapp import MessengerError

client = TestClient(app)
SECRET = "made-up-webhook-secret"
TOKEN = "made-up-whapi-token"
CHANNEL = "MANTIS-M72HC"
API = "https://gate.whapi.cloud"
WEBHOOK = f"/api/webhooks/whapi/{SECRET}"
AMINA = "923001234567"


def event(*messages: dict, statuses: tuple[dict, ...] = (), channel: str = CHANNEL) -> dict:
    """Whapi's webhook body, as its docs show it."""
    body: dict = {"event": {"type": "messages" if messages else "statuses", "event": "post"}, "channel_id": channel}
    if messages:
        body["messages"] = list(messages)
    if statuses:
        body["statuses"] = list(statuses)
    return body


def message(kind: str, message_id: str, **fields) -> dict:
    """A message from Amina's number, with her profile name."""
    base = {"id": message_id, "from_me": False, "type": kind, "chat_id": f"{AMINA}@s.whatsapp.net",
            "timestamp": 1712995245, "source": "mobile", "from": AMINA, "from_name": "Amina"}
    return {**base, **fields}


def text(body: str = "السلام علیکم، میں کشن کور بناتی ہوں", message_id: str = "p.1", **fields) -> dict:
    return message("text", message_id, text={"body": body}, **fields)


def status(wamid: str, state: str) -> dict:
    return {"id": wamid, "code": 3, "status": state, "recipient_id": f"{AMINA}@s.whatsapp.net",
            "timestamp": "1712995290"}


def her_chat(seller_id: str) -> list[dict]:
    return client.get(f"/api/chats/{seller_id}").json()["messages"]


@pytest.fixture
def whapi(use_settings, db):
    """Fake mode with a Whapi channel's webhook secret, token and id, answering everyone (no start word)."""
    use_settings(OPENSTALL_MODE="fake", WHAPI_WEBHOOK_SECRET=SECRET, WHAPI_TOKEN=TOKEN, WHAPI_CHANNEL_ID=CHANNEL,
                 WHAPI_ANSWER_EVERYONE="true")
    return db


def test_on_someones_own_number_only_a_maker_who_began_with_start_is_answered(use_settings, db, fakes):
    use_settings(OPENSTALL_MODE="fake", WHAPI_WEBHOOK_SECRET=SECRET, WHAPI_CHANNEL_ID=CHANNEL)
    friend = message("text", "p.friend", text={"body": "Ameen Summa Ameen"}, **{"from": "923339876543",
                     "chat_id": "923339876543@s.whatsapp.net", "from_name": "A friend"})

    client.post(WEBHOOK, json=event(friend))  # a friend writing to the number's owner: left alone
    client.post(WEBHOOK, json=event(text("Salaam", message_id="p.early")))  # Amina, before she began

    assert db.scalar(select(func.count()).select_from(Seller)) == 0
    assert db.scalar(select(func.count()).select_from(ChatMessage)) == 0
    assert fakes.messenger.calls == []

    client.post(WEBHOOK, json=event(text("Start", message_id="p.start")))  # her link to OpenStall writes it
    client.post(WEBHOOK, json=event(text()))  # and from then on she is answered

    db.expire_all()
    assert db.scalars(select(Seller.name)).all() == ["Amina"]
    welcome, _ = fakes.messenger.sent_to("whatsapp:+923001234567")
    # "Start" says nothing of her language: her number is in Pakistan, so she is welcomed in Urdu.
    assert welcome.text == WELCOMES["ur"]
    assert fakes.messenger.sent_to("whatsapp:+923339876543") == []


def test_start_from_a_number_outside_pakistan_is_welcomed_in_english_and_saves_no_language(use_settings, db, fakes):
    use_settings(OPENSTALL_MODE="fake", WHAPI_WEBHOOK_SECRET=SECRET)
    start = message("text", "p.us", text={"body": "Start"}, **{"from": "15551234567",
                    "chat_id": "15551234567@s.whatsapp.net", "from_name": "Grace"})

    client.post(WEBHOOK, json=event(start))

    assert [sent.text for sent in fakes.messenger.calls] == [WELCOME]
    db.expire_all()
    assert db.scalars(select(Seller.language)).one() is None


def test_a_message_to_our_secret_address_is_stored_and_answered_in_urdu(whapi, fakes):
    response = client.post(WEBHOOK, json=event(text()))

    assert (response.status_code, response.text) == (200, "OK")
    whapi.expire_all()
    seller = whapi.scalars(select(Seller)).one()
    assert (seller.name, seller.whatsapp_number, seller.country, seller.language) == ("Amina", "+923001234567", "PK",
                                                                                      "ur")
    [welcome] = fakes.messenger.sent_to("whatsapp:+923001234567")
    assert welcome.text == WELCOMES["ur"]


def test_a_request_to_any_other_address_or_from_another_channel_is_refused_and_recorded(whapi, fakes):
    assert client.post("/api/webhooks/whapi/a-guess", json=event(text())).status_code == 403
    assert client.post(WEBHOOK, json=event(text(), channel="SOMEONE-ELSES")).status_code == 403
    assert client.get("/api/webhooks/whapi/a-guess").status_code == 403
    assert client.get(WEBHOOK).text == "OK"

    assert whapi.scalar(select(func.count()).select_from(Seller)) == 0
    assert fakes.messenger.calls == []
    refusals = whapi.scalars(select(Event).where(Event.type == EventType.SECURITY_REJECTED)).all()
    assert [event.payload_json["summary"] for event in refusals] == [
        "A WhatsApp webhook without Whapi's secret was refused",
        "A WhatsApp webhook from another Whapi channel was refused",
    ]


def test_in_fake_mode_without_a_whapi_channel_the_address_carries_the_fake_secret(db, fakes):
    hello = event(text("Start"))

    assert client.post(f"/api/webhooks/whapi/{FAKE_WHAPI_WEBHOOK_SECRET}", json=hello).status_code == 200
    assert [sent.text for sent in fakes.messenger.calls] == [WELCOMES["ur"]]  # a number in Pakistan


def test_our_own_messages_groups_and_status_updates_are_left_out_and_each_message_counts_once(whapi, fakes):
    ours = text("Welcome to OpenStall!", message_id="p.ours", from_me=True)
    group = text("Hello all", message_id="p.group", chat_id="120363000000000000@g.us")
    story = text("My status", message_id="p.story", chat_id="status@broadcast")

    client.post(WEBHOOK, json=event(ours, group, story))
    client.post(WEBHOOK, json=event(text()))
    client.post(WEBHOOK, json=event(text()))  # Whapi sends it again

    assert whapi.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.direction == "inbound")) == 1
    assert len(fakes.messenger.calls) == 1


def test_her_photo_and_voice_note_are_fetched_from_whapi_with_the_token_and_kept(whapi, fakes):
    photo = message("image", "p.photo",
                    image={"id": "png-0123abcd-ef01", "mime_type": "image/png", "file_size": 120, "caption": "My cushion"})
    voice = message("voice", "p.voice",
                    voice={"id": "oga-a0ebf86acc6d9653-805113c25d2b57", "mime_type": "audio/ogg; codecs=opus",
                           "file_size": 7848, "seconds": 3})
    with respx.mock() as api:
        got_photo = api.get(f"{API}/media/png-0123abcd-ef01").respond(
            content=fixture_photo(), headers={"Content-Type": "image/png"}
        )
        api.get(f"{API}/media/oga-a0ebf86acc6d9653-805113c25d2b57").respond(
            content=b"OggS voice", headers={"Content-Type": "audio/ogg"}
        )

        assert client.post(WEBHOOK, json=event(photo, voice)).status_code == 200

    assert got_photo.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"
    seller_id = whapi.scalars(select(Seller.id)).one()
    inbound = [m for m in her_chat(seller_id) if m["direction"] == "inbound"]
    assert [(m["text"], [item["content_type"] for item in m["media"]]) for m in inbound] == [
        ("My cushion", ["image/png"]),
        (None, ["audio/ogg"]),
    ]


def test_what_became_of_each_reply_is_kept_from_whapis_statuses(whapi, fakes):
    client.post(WEBHOOK, json=event(text()))
    seller_id = whapi.scalars(select(Seller.id)).one()
    [reply] = fakes.messenger.calls

    client.post(WEBHOOK, json=event(statuses=(status(reply.message_id, "delivered"),)))
    assert her_chat(seller_id)[1]["delivery"] == "delivered"

    client.post(WEBHOOK, json=event(statuses=(status(reply.message_id, "played"),)))  # she listened: read
    assert her_chat(seller_id)[1]["delivery"] == "read"


def test_a_reply_whapi_could_not_deliver_says_so_on_her_chat_and_once_in_the_feed(whapi, fakes):
    client.post(WEBHOOK, json=event(text()))
    seller_id = whapi.scalars(select(Seller.id)).one()
    [reply] = fakes.messenger.calls

    client.post(WEBHOOK, json=event(statuses=(status(reply.message_id, "failed"),)))
    client.post(WEBHOOK, json=event(statuses=(status(reply.message_id, "failed"),)))  # sent again

    welcome = her_chat(seller_id)[1]
    assert (welcome["delivery"], welcome["delivery_error"]) == (
        "failed",
        "WhatsApp could not deliver it: Whapi gave no reason.",
    )
    whapi.expire_all()
    [failed] = whapi.scalars(select(Event).where(Event.type == EventType.MESSAGE_UNDELIVERED)).all()
    assert failed.payload_json["summary"] == "WhatsApp could not deliver a message to Amina: Whapi gave no reason."


def test_statuses_are_read_as_openstall_keeps_them():
    found = parse_whapi_statuses(event(statuses=(
        status("p.a", "pending"), status("p.b", "sent"), status("p.c", "played"),
        {"id": "p.d", "status": "failed", "recipient_id": AMINA,
         "errors": [{"code": 470, "title": "Message failed", "error_data": {"details": "The number is not on WhatsApp"}}]},
    )))

    assert [(s.message_id, s.status, s.recipient) for s in found] == [
        ("p.b", "sent", "+923001234567"),
        ("p.c", "read", "+923001234567"),
        ("p.d", "failed", "+923001234567"),
    ]
    assert found[2].reason == "(470) Message failed: The number is not on WhatsApp"
    link = message("link_preview", "p.link", link_preview={"body": "See https://example.com"})
    assert [inbound.text for inbound in parse_whapi_inbound(event(link))] == ["See https://example.com"]


def test_the_whapi_messenger_sends_text_then_a_voice_note_as_a_link():
    with respx.mock() as api:
        sent_text = api.post(f"{API}/messages/text").respond(json={"sent": True, "message": {"id": "PsqXn5SAD5v7HRA"}})
        sent_voice = api.post(f"{API}/messages/voice").respond(json={"sent": True, "message": {"id": "PsrVoice9"}})

        sent = WhapiMessenger(TOKEN).send("whatsapp:+923001234567", "شکریہ", ["https://openstall.example/m/a.mp3"])

    assert sent.message_id == "PsqXn5SAD5v7HRA"
    assert json.loads(sent_text.calls.last.request.content) == {"to": AMINA, "body": "شکریہ"}
    assert json.loads(sent_voice.calls.last.request.content) == {"to": AMINA, "media": "https://openstall.example/m/a.mp3"}
    assert sent_text.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


def test_a_message_whapi_refuses_says_why():
    with respx.mock() as api:
        api.post(f"{API}/messages/text").respond(402, json={"error": {"code": 402, "message": "Trial limit reached"}})

        with pytest.raises(MessengerError, match=r"Whapi refused the message \(402\): Trial limit reached"):
            WhapiMessenger(TOKEN).send("whatsapp:+923001234567", "Hello")


def test_sandbox_mode_with_whapi_chosen_uses_the_whapi_messenger_and_names_its_key(use_settings):
    registry = AdapterRegistry(use_settings(OPENSTALL_MODE="sandbox", WHATSAPP_PROVIDER="whapi", WHAPI_TOKEN=TOKEN))

    assert isinstance(registry.messenger, WhapiMessenger)
    assert registry.status("messenger") == "real"
    missing = AdapterRegistry(use_settings(OPENSTALL_MODE="sandbox", WHATSAPP_PROVIDER="whapi"))
    assert missing.status("messenger") != "real"
