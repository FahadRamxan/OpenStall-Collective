"""Voice notes to text (spec 3.1, step 2): a seller's voice note is turned into text before her message is stored,
the words are kept as she said them, and their language is saved on her profile. A voice note that cannot be heard
is kept all the same, and she is asked to send it again or type it."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from openstall_agents.adapters import SpeechToTextError, Transcript
from openstall_api.chat.voice import UNCLEAR, UNCLEAR_SEVERAL
from openstall_api.db import new_session
from openstall_api.events import EventType
from openstall_api.fixtures import SAMPLE_VOICE_NOTE_SAYS, fixture_photo, fixture_voice_note
from openstall_api.main import app
from openstall_api.models import ChatMessage, Event, Seller

client = TestClient(app)
NUMBER = "+923001234567"
DEMO_PHONE = "demo-5e1d77a0"


def on_whatsapp(text: str = "", *, voice_note: bool = True, photo: bool = False) -> dict:
    """A message as if it came through Twilio, with fake mode's sample voice note (the webhook's own path)."""
    response = client.post(
        "/api/dev/inbound", json={"sender": NUMBER, "text": text, "voice_note": voice_note, "photo": photo}
    )
    assert response.status_code == 201, response.text
    return response.json()


def on_the_web(text: str, files: list[tuple[bytes, str]]) -> dict:
    uploads = [("files", (f"file{index}", data, kind)) for index, (data, kind) in enumerate(files)]
    response = client.post(
        "/api/seller-chat/messages", data={"sender": DEMO_PHONE, "text": text}, files=uploads or None
    )
    assert response.status_code == 200, response.text
    return response.json()


def message(db, message_id: str) -> ChatMessage:
    db.expire_all()
    found = db.get(ChatMessage, message_id)
    assert found is not None
    return found


def transcribed(db) -> list[dict]:
    db.expire_all()
    events = db.scalars(select(Event).where(Event.type == EventType.MESSAGE_TRANSCRIBED).order_by(Event.id))
    return [event.payload_json for event in events]


def test_a_whatsapp_voice_note_is_kept_as_text_and_its_language_saved_on_her_profile(db, fakes):
    sent = on_whatsapp()

    kept = message(db, sent["message_id"])
    assert kept.transcript == SAMPLE_VOICE_NOTE_SAYS.text
    assert kept.language == "ur"
    assert [item["content_type"] for item in kept.media_json] == ["audio/wav"]  # the voice note itself is kept too
    assert db.get(Seller, sent["seller_id"]).language == "ur"
    assert transcribed(db) == [
        {
            "summary": "Amina's voice note was turned into text, in Urdu, now saved as her language",
            "channel": "whatsapp",
            "message_id": sent["message_id"],
            "language": "ur",
            "language_saved": True,
        }
    ]
    assert len(fakes.speech_to_text.calls) == 1
    assert UNCLEAR not in sent["replies"]


def test_the_chat_api_gives_each_message_its_words_and_language(db):
    sent = on_whatsapp("Salaam!")

    messages = client.get(f"/api/chats/{sent['seller_id']}").json()["messages"]

    hers = next(item for item in messages if item["id"] == sent["message_id"])
    assert hers["text"] == "Salaam!"
    assert hers["transcript"] == SAMPLE_VOICE_NOTE_SAYS.text
    assert hers["language"] == "ur"
    assert all(item["transcript"] is None for item in messages if item["id"] != sent["message_id"])


def test_the_same_voice_note_in_the_web_chat_is_heard_the_same_way(db):
    sent = on_the_web("", [(fixture_voice_note(), "audio/wav")])

    assert message(db, sent["message_id"]).transcript == SAMPLE_VOICE_NOTE_SAYS.text
    assert db.get(Seller, sent["seller_id"]).language == "ur"
    assert transcribed(db)[0]["channel"] == "web"


def test_a_language_already_on_her_profile_stays(db, fakes):
    first = on_whatsapp()
    fakes.speech_to_text.queue(Transcript("I can also make table runners.", "en"))

    second = on_whatsapp()

    assert message(db, second["message_id"]).language == "en"
    assert db.get(Seller, second["seller_id"]).language == "ur"
    assert [event["summary"] for event in transcribed(db)] == [
        "Amina's voice note was turned into text, in Urdu, now saved as her language",
        "Amina's voice note was turned into text, in English",
    ]
    assert first["seller_id"] == second["seller_id"]


def test_a_voice_note_that_cannot_be_heard_is_kept_and_she_is_asked_to_send_it_again(db, fakes):
    fakes.speech_to_text.queue(SpeechToTextError("OpenAI took too long to answer."))

    sent = on_whatsapp()

    kept = message(db, sent["message_id"])
    assert kept.transcript is None
    assert kept.language is None
    assert [item["content_type"] for item in kept.media_json] == ["audio/wav"]
    assert sent["replies"][0] == UNCLEAR
    assert db.get(Seller, sent["seller_id"]).language is None
    assert transcribed(db) == []


def test_two_voice_notes_in_one_message_keep_their_order(db, fakes):
    fakes.speech_to_text.queue(Transcript("Cushion covers, three colours.", "en"), Transcript("Fifteen a week.", "en"))

    sent = on_the_web("", [(b"OggS first note", "audio/ogg"), (b"OggS second note", "audio/ogg")])

    assert message(db, sent["message_id"]).transcript == "Cushion covers, three colours.\n\nFifteen a week."
    assert transcribed(db)[0]["summary"].startswith("Web seller 77A0's 2 voice notes were turned into text, in English")


def test_one_of_two_voice_notes_unheard_keeps_the_other_and_says_which(db, fakes):
    fakes.speech_to_text.queue(SpeechToTextError("no words"), Transcript("Fifteen a week.", "en"))

    sent = on_the_web("", [(b"OggS first note", "audio/ogg"), (b"OggS second note", "audio/ogg")])

    assert message(db, sent["message_id"]).transcript == "Fifteen a week."
    assert UNCLEAR in sent["replies"]

    fakes.speech_to_text.queue(SpeechToTextError("no words"), SpeechToTextError("no words"))
    again = on_the_web("", [(b"OggS third note", "audio/ogg"), (b"OggS fourth note", "audio/ogg")])
    assert UNCLEAR_SEVERAL.format(count=2) in again["replies"]


def test_a_message_without_a_voice_note_never_reaches_speech_to_text(db, fakes):
    on_whatsapp("$18 each", voice_note=False, photo=True)
    on_the_web("Ships from Lahore", [(fixture_photo(), "image/png")])

    assert fakes.speech_to_text.calls == []
    assert transcribed(db) == []


def test_a_file_the_media_store_refuses_is_never_sent_to_be_heard(db, fakes):
    sent = on_the_web("", [(b"FORM a made-up aiff file", "audio/x-aiff")])

    assert fakes.speech_to_text.calls == []
    assert sent["replies"][0].startswith("Sorry, I could not keep one of your files")
    assert UNCLEAR not in sent["replies"]


def test_her_voice_note_is_heard_before_her_message_is_stored(db, fakes, monkeypatch):
    stored_while_hearing: list[int] = []
    hear = fakes.speech_to_text.transcribe

    def transcribe(audio):
        # What another connection sees while the provider is asked: nothing of her message is stored yet.
        with new_session() as other:
            stored_while_hearing.append(other.scalar(select(func.count()).select_from(ChatMessage)) or 0)
        return hear(audio)

    monkeypatch.setattr(fakes.speech_to_text, "transcribe", transcribe)

    on_whatsapp()

    assert stored_while_hearing == [0]


def test_without_an_openai_key_in_sandbox_mode_she_is_asked_to_type_it(use_settings, db):
    use_settings(OPENSTALL_MODE="sandbox")

    sent = on_the_web("Salaam", [(fixture_voice_note(), "audio/wav")])

    assert UNCLEAR in sent["replies"]
    assert message(db, sent["message_id"]).text == "Salaam"
    assert message(db, sent["message_id"]).transcript is None


def test_a_text_message_in_sandbox_mode_without_an_openai_key_is_not_apologised_for(use_settings, db):
    use_settings(OPENSTALL_MODE="sandbox")

    sent = on_the_web("Salaam", [])

    assert UNCLEAR not in sent["replies"]


def test_the_web_chat_offers_the_sample_voice_note_in_fake_mode(db):
    samples = client.get("/api/seller-chat/samples").json()

    assert samples == {"voice_note": "/api/dev/samples/voice-note.wav"}
    sample = client.get(samples["voice_note"])
    assert sample.status_code == 200
    assert sample.headers["content-type"] == "audio/wav"
    assert sample.content == fixture_voice_note()


def test_in_sandbox_mode_there_is_no_sample_voice_note(use_settings):
    use_settings(OPENSTALL_MODE="sandbox")

    assert client.get("/api/seller-chat/samples").json() == {"voice_note": None}
    assert client.get("/api/dev/samples/voice-note.wav").status_code == 404


@pytest.mark.parametrize("words", ["", "   "])
def test_a_voice_note_heard_as_nothing_counts_as_not_heard(db, fakes, words):
    fakes.speech_to_text.queue(Transcript(words, "en"))

    sent = on_whatsapp()

    assert message(db, sent["message_id"]).transcript is None
    assert UNCLEAR in sent["replies"]
