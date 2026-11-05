"""A maker who talks to OpenStall in voice notes (ElevenLabs, at the user's request): her voice notes go to speech to
text with the language she is known to speak as a hint, and each answer to a voice note is spoken too, in her
language, kept on its message and, on WhatsApp, sent after the text. A typed message gets text only; an answer that
cannot be spoken still goes out as text."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from openstall_agents.adapters import TextToSpeechError
from openstall_api.chat.handler import WELCOMES
from openstall_api.events import EventType
from openstall_api.fixtures import fixture_photo, fixture_voice_note
from openstall_api.main import app
from openstall_api.models import Event, Seller
from openstall_api.seed import seed

client = TestClient(app)
DEMO_PHONE = "demo-9d1e0f5a"
SELLER = "Web seller 0F5A"
VOICE_NOTE = (fixture_voice_note(), "audio/wav")
SAMPLES = [(fixture_photo(), "image/png"), VOICE_NOTE]


def on_the_web(text: str, files: list[tuple[bytes, str]] | None = None) -> dict:
    uploads = [("files", (f"file{index}", data, kind)) for index, (data, kind) in enumerate(files or [])]
    response = client.post(
        "/api/seller-chat/messages", data={"sender": DEMO_PHONE, "text": text}, files=uploads or None
    )
    assert response.status_code == 200, response.text
    return response.json()


def answers(seller_id: str) -> list[dict]:
    """OpenStall's messages in her chat, oldest first."""
    messages = client.get(f"/api/chats/{seller_id}").json()["messages"]
    return [message for message in messages if message["direction"] == "outbound"]


def spoken(message: dict) -> list[dict]:
    return [item for item in message["media"] if item["spoken"]]


def events(db, kind: EventType) -> list[str]:
    db.expire_all()
    return [event.payload_json["summary"] for event in db.scalars(select(Event).where(Event.type == kind))]


def test_her_voice_note_is_answered_in_text_and_spoken_in_her_language(db, fakes):
    sent = on_the_web("", SAMPLES)

    replies = answers(sent["seller_id"])
    assert [reply["text"] for reply in replies] == sent["replies"]
    assert sent["replies"][0] == WELCOMES["ur"]
    for reply in replies:
        [audio] = spoken(reply)
        assert (audio["content_type"], reply["language"]) == ("audio/wav", "ur")  # the stand-in voice, in test mode
        assert client.get(audio["url"]).status_code == 200
    assert fakes.text_to_speech.calls == [(text, "ur") for text in sent["replies"]]
    assert events(db, EventType.MESSAGE_SPOKEN) == [
        f"OpenStall's 2 answers were spoken to {SELLER} in the web chat, in Urdu, as she sent a voice note"
    ]


def test_a_typed_message_is_answered_in_text_only(db, fakes):
    sent = on_the_web("Hello")

    assert [spoken(reply) for reply in answers(sent["seller_id"])] == [[]]
    assert fakes.text_to_speech.calls == []
    assert events(db, EventType.MESSAGE_SPOKEN) == []


def test_on_whatsapp_each_spoken_answer_follows_the_texts_as_a_voice_note(db, fakes, settings):
    response = client.post("/api/dev/inbound", json={"text": "Salaam", "voice_note": True})

    assert response.status_code == 201
    sent = [(call.text, call.media_urls) for call in fakes.messenger.sent_to("whatsapp:+923001234567")]
    texts, voice_notes = sent[:2], sent[2:]
    assert [text for text, _ in texts] == response.json()["replies"]
    assert all(media == () for _, media in texts)
    assert [text for text, _ in voice_notes] == ["", ""]
    urls = [media[0] for _, media in voice_notes]
    assert all(url.startswith(f"{settings.PUBLIC_BASE_URL}/media/uploads/") for url in urls)


def test_an_answer_that_cannot_be_spoken_still_goes_out_as_text(db, fakes):
    fakes.text_to_speech.fail = TextToSpeechError("the voice took too long to answer")

    sent = on_the_web("", SAMPLES)

    assert sent["replies"][0] == WELCOMES["ur"]
    assert [spoken(reply) for reply in answers(sent["seller_id"])] == [[], []]
    assert events(db, EventType.MESSAGE_SPOKEN) == []


def test_spoken_answers_can_be_turned_off(db, use_settings, fakes):
    use_settings(OPENSTALL_MODE="fake", SPOKEN_REPLIES="false")

    sent = on_the_web("", SAMPLES)

    assert [spoken(reply) for reply in answers(sent["seller_id"])] == [[], []]
    assert fakes.text_to_speech.calls == []


def test_a_pakistani_number_hints_urdu_and_a_known_language_hints_itself(db, fakes):
    seed(db, with_amina=True)
    db.commit()

    client.post("/api/dev/inbound", json={"sender": "+923001110000", "voice_note": True})  # new, in Pakistan
    client.post("/api/dev/inbound", json={"sender": "+919811100000", "voice_note": True})  # new, in India
    client.post("/api/dev/sellers/s_priya/messages", json={"text": "", "receipt": False})  # no voice note: no hint asked
    on_the_web("", [VOICE_NOTE])  # a new web seller: no country, no language yet
    on_the_web("", [VOICE_NOTE])  # her first voice note saved Urdu as her language

    assert fakes.speech_to_text.hints == ["ur", None, None, "ur"]


def test_a_seeded_maker_s_voice_note_carries_her_own_language(db, fakes):
    seed(db, with_amina=True)
    db.commit()
    db.get(Seller, "s_priya").whatsapp_number = "+919811100001"
    db.commit()

    client.post("/api/dev/inbound", json={"sender": "+919811100001", "voice_note": True})

    assert fakes.speech_to_text.hints == ["hi"]
