"""OpenAI's speech to text (spec 3.1, step 2): one transcriptions call per voice note, the words as she said them and
the language it heard, and every failure as SpeechToTextError with no key in it. OpenAI is mocked with respx."""

import json

import httpx
import pytest
import respx

from openstall_agents.adapters import (
    Media,
    OpenAISpeechToText,
    SpeechToText,
    SpeechToTextError,
    Transcript,
    language_code,
    language_name,
)

BASE = "https://api.openai.com/v1"
KEY = "sk-made-up-openai-4c7b"
URDU = "کڑھائی والے کشن کور، تین رنگوں میں، اٹھارہ ڈالر کا ایک۔"
WHATSAPP_NOTE = Media(b"OggS\x00 a made-up voice note", "audio/ogg")


@pytest.fixture
def openai():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


def verbose(text: str, language: str) -> httpx.Response:
    return httpx.Response(200, json={"task": "transcribe", "language": language, "duration": 4.2, "text": text})


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


def test_it_follows_the_interface():
    assert isinstance(OpenAISpeechToText(KEY), SpeechToText)


def test_a_whatsapp_voice_note_comes_back_word_for_word_with_its_language(openai):
    route = openai.post("/audio/transcriptions").mock(return_value=verbose(URDU, "urdu"))

    heard = OpenAISpeechToText(KEY).transcribe(WHATSAPP_NOTE)

    assert heard == Transcript(URDU, "ur")
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert form_fields(request) == {"model": "whisper-1", "response_format": "verbose_json"}
    assert b'filename="voice-note.ogg"' in request.content
    assert b"Content-Type: audio/ogg" in request.content
    assert b"OggS\x00 a made-up voice note" in request.content


@pytest.mark.parametrize(
    ("media_type", "file_name"),
    [
        ("audio/webm", "voice-note.webm"),
        ("audio/webm;codecs=opus", "voice-note.webm"),
        ("audio/mp4", "voice-note.m4a"),
        ("audio/mpeg", "voice-note.mp3"),
        ("audio/wav", "voice-note.wav"),
    ],
)
def test_each_recording_is_named_for_its_format(openai, media_type, file_name):
    route = openai.post("/audio/transcriptions").mock(return_value=verbose("Hello", "english"))

    OpenAISpeechToText(KEY).transcribe(Media(b"audio", media_type))

    assert f'filename="{file_name}"'.encode() in route.calls.last.request.content


@pytest.mark.parametrize("media_type", ["audio/amr", "audio/aac", ""])
def test_a_format_openai_cannot_read_is_refused_before_any_call(openai, media_type):
    route = openai.post("/audio/transcriptions")

    with pytest.raises(SpeechToTextError, match="OpenAI cannot read"):
        OpenAISpeechToText(KEY).transcribe(Media(b"audio", media_type))

    assert not route.called


def test_another_model_answers_in_json_and_its_language_is_not_known(openai):
    route = openai.post("/audio/transcriptions").mock(return_value=httpx.Response(200, json={"text": URDU}))

    heard = OpenAISpeechToText(KEY, "gpt-4o-transcribe").transcribe(WHATSAPP_NOTE)

    assert heard == Transcript(URDU, None)
    assert form_fields(route.calls.last.request) == {"model": "gpt-4o-transcribe", "response_format": "json"}


def test_a_language_nobody_can_read_is_not_kept(openai):
    openai.post("/audio/transcriptions").mock(return_value=verbose("Bonjour", "klingon"))

    assert OpenAISpeechToText(KEY).transcribe(WHATSAPP_NOTE).language is None


def test_a_refused_key_says_so_without_any_of_the_key(openai):
    openai.post("/audio/transcriptions").mock(
        return_value=httpx.Response(
            401, json={"error": {"message": f"Incorrect API key provided: {KEY[:8]}****4c7b.", "type": "invalid"}}
        )
    )

    with pytest.raises(SpeechToTextError) as raised:
        OpenAISpeechToText(KEY).transcribe(WHATSAPP_NOTE)

    assert str(raised.value) == "OpenAI refused the voice note: 401, the API key was not accepted."
    assert "4c7b" not in str(raised.value)


def test_another_refusal_carries_openais_words_with_any_key_taken_out(openai):
    openai.post("/audio/transcriptions").mock(
        return_value=httpx.Response(400, json={"error": {"message": f"Invalid file format for {KEY}."}})
    )

    with pytest.raises(SpeechToTextError) as raised:
        OpenAISpeechToText(KEY).transcribe(WHATSAPP_NOTE)

    assert str(raised.value) == "OpenAI refused the voice note: 400, Invalid file format for sk-….."
    assert KEY not in str(raised.value)


def test_a_server_error_without_a_body_gives_its_status(openai):
    openai.post("/audio/transcriptions").mock(return_value=httpx.Response(503, text="upstream down"))

    with pytest.raises(SpeechToTextError, match=r"refused the voice note: 503\.$"):
        OpenAISpeechToText(KEY).transcribe(WHATSAPP_NOTE)


def test_a_timeout_and_a_lost_connection_are_speech_to_text_errors(openai):
    route = openai.post("/audio/transcriptions")
    route.side_effect = httpx.ReadTimeout("slow")
    with pytest.raises(SpeechToTextError, match="took too long"):
        OpenAISpeechToText(KEY).transcribe(WHATSAPP_NOTE)

    route.side_effect = httpx.ConnectError("no route")
    with pytest.raises(SpeechToTextError, match=r"could not be reached \(ConnectError\)"):
        OpenAISpeechToText(KEY).transcribe(WHATSAPP_NOTE)


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, json={"text": "   ", "language": "english"}),
        httpx.Response(200, json=[]),
        httpx.Response(200, text="not json"),
    ],
)
def test_an_empty_or_unreadable_answer_is_an_error_not_an_empty_transcript(openai, answer):
    openai.post("/audio/transcriptions").mock(return_value=answer)

    with pytest.raises(SpeechToTextError):
        OpenAISpeechToText(KEY).transcribe(WHATSAPP_NOTE)


def test_the_key_never_appears_in_the_adapter_s_repr():
    assert KEY not in repr(OpenAISpeechToText(KEY))
    assert KEY not in json.dumps(vars(OpenAISpeechToText(KEY)), default=str)


@pytest.mark.parametrize(
    ("heard", "code"),
    [("urdu", "ur"), ("Urdu", "ur"), ("ur", "ur"), (" hindi ", "hi"), ("spanish", "es"), ("myanmar", "my"),
     ("jw", "jv"), ("cantonese", "yue"), ("", None), (None, None), (42, None), ("elvish", None)],
)  # fmt: skip
def test_language_code_reads_whisper_s_names_and_codes(heard, code):
    assert language_code(heard) == code


def test_language_name_is_english_and_falls_back_to_the_code():
    assert language_name("ur") == "Urdu"
    assert language_name("yue") == "Cantonese"
    assert language_name("xx") == "xx"
    assert language_name(None) is None
