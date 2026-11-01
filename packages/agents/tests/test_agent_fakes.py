"""The AI adapters' fakes: deterministic, recording every call, and following their interfaces."""

import json
import math
import os
import subprocess
import sys

import pytest

from openstall_agents.adapters import (
    LLM,
    Embedder,
    FakeEmbedder,
    FakeImageSearch,
    FakeLLM,
    FakeSpeechToText,
    ImageSearch,
    LLMCall,
    Media,
    SpeechToText,
    Transcript,
    WebMatches,
)

PHOTO = Media(b"\x89PNG made-up photo bytes", "image/png")
OTHER_PHOTO = Media(b"\x89PNG another made-up photo", "image/png")
VOICE_NOTE = Media(b"OggS made-up voice note", "audio/ogg")
SCHEMA = {"type": "object", "properties": {"price_usd": {"type": ["number", "null"]}}}


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


@pytest.mark.parametrize(
    ("fake", "interface"),
    [
        (FakeLLM(), LLM),
        (FakeSpeechToText(), SpeechToText),
        (FakeEmbedder(), Embedder),
        (FakeImageSearch(), ImageSearch),
    ],
)
def test_each_fake_follows_its_interface(fake, interface):
    assert isinstance(fake, interface)


def test_fake_llm_records_every_request():
    llm = FakeLLM()

    llm.generate_text("Say hello", system="Be brief")
    llm.generate_json("Read this listing", schema=SCHEMA, images=[PHOTO])

    assert llm.calls == [
        LLMCall("text", "Say hello", "Be brief", (), None),
        LLMCall("json", "Read this listing", None, (PHOTO,), SCHEMA),
    ]


def test_fake_llm_gives_queued_replies_in_order_then_fixed_defaults():
    llm = FakeLLM(replies=["first"])
    llm.queue({"price_usd": 18}, '{"price_usd": null}')

    assert llm.generate_text("a") == "first"
    assert llm.generate_json("b", schema=SCHEMA) == {"price_usd": 18}
    assert llm.generate_json("c", schema=SCHEMA) == {"price_usd": None}
    assert llm.generate_text("Describe the photo") == "Fake reply to: Describe the photo"
    assert llm.generate_json("e", schema=SCHEMA) == {}


def test_fake_llm_asks_its_responder_when_nothing_is_queued():
    llm = FakeLLM(responder=lambda call: {"echo": call.prompt} if call.kind == "json" else call.prompt.upper())

    assert llm.generate_text("hello") == "HELLO"
    assert llm.generate_json("hi", schema=SCHEMA) == {"echo": "hi"}


def test_fake_llm_answers_the_same_way_every_time():
    answers = {FakeLLM().generate_text("Describe the photo", images=[PHOTO]) for _ in range(3)}

    assert len(answers) == 1


def test_changing_a_fake_llm_answer_leaves_the_queued_reply_alone():
    reply = {"variants": ["red"]}
    llm = FakeLLM(replies=[reply])

    llm.generate_json("x", schema=SCHEMA)["variants"].append("blue")

    assert reply == {"variants": ["red"]}


def test_fake_llm_refuses_a_reply_of_the_wrong_kind():
    with pytest.raises(TypeError, match="text request needs a str reply"):
        FakeLLM(replies=[{"a": 1}]).generate_text("x")
    with pytest.raises(TypeError, match="JSON request needs an object reply"):
        FakeLLM(replies=["[1, 2]"]).generate_json("x", schema=SCHEMA)


def test_fake_speech_to_text_gives_queued_transcripts_then_a_fixed_one():
    amina = Transcript("Embroidered cushion covers, 3 colours, 18 dollars", "ur")
    stt = FakeSpeechToText([amina])

    assert stt.transcribe(VOICE_NOTE) == amina
    fallback = stt.transcribe(VOICE_NOTE)
    assert fallback == FakeSpeechToText().transcribe(VOICE_NOTE)
    assert fallback.language == "en"
    assert stt.calls == [VOICE_NOTE, VOICE_NOTE]


def test_fake_speech_to_text_tells_voice_notes_apart():
    stt = FakeSpeechToText()

    assert stt.transcribe(VOICE_NOTE).text != stt.transcribe(Media(b"OggS another note", "audio/ogg")).text


def test_fake_embedder_gives_the_same_unit_vectors_every_time():
    texts = ["ceramic mugs", "hand-thrown coffee mug"]

    vectors = FakeEmbedder().embed(texts)

    assert vectors == FakeEmbedder().embed(texts)
    assert [len(vector) for vector in vectors] == [256, 256]
    assert all(math.isclose(cosine(vector, vector), 1.0) for vector in vectors)


def test_fake_embedder_puts_texts_that_share_words_closer_together():
    mugs, coffee_mugs, cushions = FakeEmbedder().embed(
        ["ceramic mugs", "ceramic coffee mugs", "embroidered cushion covers"]
    )

    assert cosine(mugs, coffee_mugs) > cosine(mugs, cushions)


def test_fake_embedder_gives_the_same_vectors_in_every_process():
    # Python seeds hash() differently in each process, so the fake must not use it.
    code = (
        "import json; from openstall_agents.adapters import FakeEmbedder; "
        "print(json.dumps(FakeEmbedder().embed(['pottery mug set'])))"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in ("1", "2")
    }

    assert len(outputs) == 1
    assert json.loads(outputs.pop()) == FakeEmbedder().embed(["pottery mug set"])


def test_fake_embedder_records_each_call():
    embedder = FakeEmbedder()

    embedder.embed(["ceramic mugs"])
    embedder.embed(["pottery", "mug set"])

    assert embedder.calls == [("ceramic mugs",), ("pottery", "mug set")]


def test_fake_image_search_finds_nothing_unless_a_test_says_so():
    search = FakeImageSearch()
    assert search.find_matches(PHOTO) == WebMatches()
    assert not WebMatches().found

    stock = WebMatches(full_matches=("https://stock.example/cushion.jpg",))
    search.add_matches(Media(PHOTO.data, "image/png"), stock)

    assert search.find_matches(PHOTO) == stock
    assert stock.found
    assert search.find_matches(OTHER_PHOTO) == WebMatches()
    assert search.calls == [PHOTO, PHOTO, OTHER_PHOTO]


def test_media_names_a_file_without_printing_its_bytes():
    assert repr(PHOTO) == f"Media('image/png', {len(PHOTO.data)} bytes, sha256={PHOTO.sha256[:12]})"
