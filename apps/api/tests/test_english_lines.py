"""The English line under a message to a maker in Urdu, Hindi or Spanish: the same message composed again from the
English templates with the same facts (wording.say), kept with it for the pages, and never sent to her."""

import pytest

from openstall_api.chat.asking import asking_reply, live_reply
from openstall_api.chat.handler import THANKS, WELCOMES, turn
from openstall_api.chat.voice import Heard
from openstall_api.wording import Said, english_of, say

LANGUAGES = ["ur", "hi", "es"]
DRAFT = {
    "title": "Hand-embroidered cushion cover",
    "price_usd": "18.00",
    "capacity_per_week": 4,
    "missing": ["ship_days"],
    "asked": "ship_days",
}
VOICE_NOTE = [{"content_type": "audio/ogg", "key": "uploads/note.ogg"}]


def test_a_said_message_is_its_own_text_and_carries_its_english():
    said = Said("شکریہ", "Thank you")

    assert said == "شکریہ"
    assert isinstance(said, str)
    assert english_of(said) == "Thank you"
    assert english_of("any other text") is None
    assert english_of(None) is None
    assert english_of(Said("Thank you", "Thank you")) is None  # the same words need no English line
    assert english_of(said + "!") is None  # joining makes a plain str: compose first, say last


def test_say_composes_her_language_then_english_from_the_same_facts():
    asked: list[str] = []

    def compose(code: str) -> str:
        asked.append(code)
        return f"{code}: 12 × cushion cover"

    said = say("ur", compose)

    assert (said, english_of(said), asked) == ("ur: 12 × cushion cover", "en: 12 × cushion cover", ["ur", "en"])
    assert english_of(say("en", compose)) is None  # already English: composed once, no line


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_welcome_and_the_thanks_carry_their_english(language):
    [welcome] = turn(None, True, "", [], Heard(), language=language)
    [thanks] = turn(None, False, "", VOICE_NOTE, Heard(texts=("her words",), language=language), language=language)

    assert (welcome.text, english_of(welcome.text)) == (WELCOMES[language], WELCOMES["en"])
    assert english_of(thanks.text) == THANKS["en"].format(what="your voice note")


def test_an_english_welcome_has_no_english_line():
    [welcome] = turn(None, True, "", [], Heard(), language="en")

    assert english_of(welcome.text) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_question_and_the_live_listing_carry_their_english(language):
    question = asking_reply(DRAFT, language, thanks=True)
    live = live_reply(language, "https://openstall.example/stall/s_new")

    assert english_of(question) == asking_reply(DRAFT, "en", thanks=True)
    assert "$18.00 each" in str(english_of(question))
    assert english_of(live) == live_reply("en", "https://openstall.example/stall/s_new")
