"""ElevenLabs, the real voice of OpenStall (sandbox mode): Scribe turns voice notes into text word for word, with the
language it heard and the hint it was given; Eleven v4 Turbo speaks an answer in her language. Every failure is a
SpeechToTextError or TextToSpeechError with no key in it. ElevenLabs is mocked with respx; the request and answer
shapes were checked against the real API on 2026-11-06."""

import httpx
import pytest
import respx

from openstall_agents.adapters import (
    ElevenLabsSpeechToText,
    ElevenLabsTextToSpeech,
    FakeTextToSpeech,
    Media,
    SpeechToText,
    SpeechToTextError,
    TextToSpeech,
    TextToSpeechError,
    Transcript,
    language_code,
)
from openstall_agents.adapters.elevenlabs import DEFAULT_VOICE

BASE = "https://api.elevenlabs.io"
KEY = "sk_madeupelevenlabs0000000000000000000000000000"
URDU = "OpenStall میں خوش آمدید! جو آپ بناتی ہیں، اس کی تصویریں بھیجیں۔"
WHATSAPP_NOTE = Media(b"OggS\x00 a made-up voice note", "audio/ogg")


@pytest.fixture
def elevenlabs():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


def heard(text: str, language: str) -> httpx.Response:
    """Scribe's answer, as the real API gives it."""
    return httpx.Response(
        200,
        json={
            "language_code": language,
            "language_probability": 1.0,
            "text": text,
            "words": [],
            "transcription_id": "made-up",
            "audio_duration_secs": 4.88,
        },
    )


def form_fields(request: httpx.Request) -> dict[str, str]:
    """The plain fields of a multipart request, by name."""
    body = request.content.decode("latin-1")
    fields = {}
    for part in body.split("Content-Disposition: form-data; ")[1:]:
        head, _, value = part.partition("\r\n\r\n")
        if "filename=" not in head:
            name = head.split('name="', 1)[1].split('"', 1)[0]
            fields[name] = value.split("\r\n--", 1)[0]
    return fields


def test_both_follow_their_interfaces():
    assert isinstance(ElevenLabsSpeechToText(KEY), SpeechToText)
    assert isinstance(ElevenLabsTextToSpeech(KEY), TextToSpeech)
    assert isinstance(FakeTextToSpeech(), TextToSpeech)


def test_a_voice_note_comes_back_word_for_word_with_its_language_and_no_audio_tags(elevenlabs):
    route = elevenlabs.post("/v1/speech-to-text").mock(return_value=heard(URDU, "urd"))

    transcript = ElevenLabsSpeechToText(KEY).transcribe(WHATSAPP_NOTE, language="ur")

    assert transcript == Transcript(URDU, "ur")
    request = route.calls.last.request
    assert request.headers["xi-api-key"] == KEY
    assert form_fields(request) == {"model_id": "scribe_v2", "tag_audio_events": "false", "language_code": "ur"}
    assert b'filename="voice-note.ogg"' in request.content
    assert b"Content-Type: audio/ogg" in request.content


def test_without_a_hint_scribe_decides_the_language(elevenlabs):
    route = elevenlabs.post("/v1/speech-to-text").mock(
        return_value=heard("OpenStall में खुशामदीद। जो आप बनाती हैं उसकी तस्वीरें भेजें।", "hin")
    )

    transcript = ElevenLabsSpeechToText(KEY, model="scribe_v1").transcribe(Media(b"webm", "audio/webm"))

    assert transcript.language == "hi"
    assert form_fields(route.calls.last.request) == {"model_id": "scribe_v1", "tag_audio_events": "false"}


@pytest.mark.parametrize(("code", "two"), [("urd", "ur"), ("hin", "hi"), ("spa", "es"), ("eng", "en"), ("xyz", None)])
def test_three_letter_codes_are_kept_as_two_letter_ones(code, two):
    assert language_code(code) == two


@pytest.mark.parametrize(
    ("answer", "problem"),
    [
        (httpx.Response(401, json={"detail": {"status": "invalid_api_key", "message": f"Invalid key {KEY}"}}),
         "the API key was not accepted"),
        (httpx.Response(422, json={"detail": {"message": f"Bad audio, key {KEY}"}}), "422, Bad audio, key sk_…"),
        (httpx.Response(200, json={"language_code": "urd", "text": "  "}), "heard no words"),
        (httpx.Response(200, content=b"not json"), "not JSON"),
    ],
)
def test_a_refusal_or_an_empty_answer_says_why_without_the_key(elevenlabs, answer, problem):
    elevenlabs.post("/v1/speech-to-text").mock(return_value=answer)

    with pytest.raises(SpeechToTextError) as raised:
        ElevenLabsSpeechToText(KEY).transcribe(WHATSAPP_NOTE)

    assert problem in str(raised.value)
    assert KEY not in str(raised.value)


def test_a_timeout_is_a_speech_to_text_error(elevenlabs):
    elevenlabs.post("/v1/speech-to-text").mock(side_effect=httpx.ReadTimeout("slow"))

    with pytest.raises(SpeechToTextError, match="took too long"):
        ElevenLabsSpeechToText(KEY).transcribe(WHATSAPP_NOTE)


def test_an_answer_is_spoken_with_eleven_v4_turbo_in_her_language(elevenlabs):
    route = elevenlabs.post(f"/v1/text-to-speech/{DEFAULT_VOICE}").mock(
        return_value=httpx.Response(200, content=b"ID3 made-up mp3")
    )

    spoken = ElevenLabsTextToSpeech(KEY).speak(URDU, "ur")

    assert spoken == Media(b"ID3 made-up mp3", "audio/mpeg")
    request = route.calls.last.request
    assert request.headers["xi-api-key"] == KEY
    assert request.url.params["output_format"] == "mp3_44100_128"
    assert request.read() == httpx.Request(
        "POST", "/", json={"text": URDU, "model_id": "eleven_v4_turbo", "language_code": "ur"}
    ).read()


def test_another_voice_and_model_can_be_chosen_and_no_language_is_sent_when_unknown(elevenlabs):
    route = elevenlabs.post("/v1/text-to-speech/voice-123").mock(return_value=httpx.Response(200, content=b"mp3"))

    ElevenLabsTextToSpeech(KEY, model="eleven_flash_v2_5", voice="voice-123").speak("Hello")

    assert route.calls.last.request.read() == httpx.Request(
        "POST", "/", json={"text": "Hello", "model_id": "eleven_flash_v2_5"}
    ).read()


@pytest.mark.parametrize(
    ("answer", "problem"),
    [
        (httpx.Response(401, json={"detail": {"status": "missing_permissions"}}), "the API key was not accepted"),
        (httpx.Response(400, json={"detail": {"message": "Unsupported language"}}), "400, Unsupported language"),
        (httpx.Response(200, content=b""), "no audio"),
    ],
)
def test_speaking_fails_with_a_reason_and_no_key(elevenlabs, answer, problem):
    elevenlabs.post(f"/v1/text-to-speech/{DEFAULT_VOICE}").mock(return_value=answer)

    with pytest.raises(TextToSpeechError) as raised:
        ElevenLabsTextToSpeech(KEY).speak("Hello", "en")

    assert problem in str(raised.value)
    assert KEY not in str(raised.value)


def test_the_test_mode_voice_is_a_short_tone_the_same_for_the_same_words():
    voice = FakeTextToSpeech()

    first = voice.speak("Your listing so far", "en")
    again = voice.speak("Your listing so far", "en")
    other = voice.speak("Your listing so far", "ur")

    assert first.media_type == "audio/wav" and first.data.startswith(b"RIFF")
    assert first == again and first != other
    assert voice.calls == [("Your listing so far", "en")] * 2 + [("Your listing so far", "ur")]
    voice.fail = TextToSpeechError("the stand-in voice was told to fail")
    with pytest.raises(TextToSpeechError):
        voice.speak("Hello")
