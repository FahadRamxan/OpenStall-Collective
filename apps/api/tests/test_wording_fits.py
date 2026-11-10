"""Every message OpenStall writes to a maker in Urdu or Hindi fits any maker, a man as well as a woman, and reads
properly aloud.

Urdu and Hindi verbs carry the speaker's gender ("آپ بناتی ہیں" is said to a woman, "آپ بناتے ہیں" to a man). The
templates once spoke to every maker as a woman, and a man testing on WhatsApp was told "آپ ہفتے میں کتنے بنا سکتی
ہیں". So each template is put so that its verb agrees with the item, the parcel or the price, never with the maker.
And Urdu says "اشتہار", not "لسٹنگ": the voice that speaks a reply read that English word as "listening".

The templates are found, not listed: every module-level mapping that has a template for each language (LOCALES).
"""

import dataclasses
from collections.abc import Iterator, Mapping
from types import ModuleType

import pytest

from openstall_api import advance, delivery, disputes, healing, notices, proof, radar, wording
from openstall_api.chat import asking, handler, publish, voice
from openstall_api.wording import LOCALES

MODULES: tuple[ModuleType, ...] = (advance, delivery, disputes, healing, notices, proof, radar, wording, asking,
                                   handler, publish, voice)

# Verb forms that speak to the maker as a woman: present ("you make"), "can", wants, and the future.
SAID_TO_A_WOMAN = {
    "ur": ("بناتی ہیں", "سکتی ہیں", "بھیجتی ہیں", "چاہتی ہیں", "کرتی ہیں", "بیچتی ہیں", "لیتی ہیں", "دیتی ہیں",
           "لیں گی", "سکیں گی", "کریں گی", "بھیجیں گی", "چاہیں گی"),
    "hi": ("बनाती हैं", "सकती हैं", "भेजती हैं", "चाहती हैं", "करती हैं", "बेचती हैं", "लेती हैं", "देती हैं",
           "लेंगी", "सकेंगी", "करेंगी", "भेजेंगी", "चाहेंगी"),
}
# Words the voice reads wrongly, with what to say instead.
MISREAD = {"ur": {"لسٹنگ": "اشتہار"}}


def strings(value: object) -> Iterator[str]:
    """Every text in a template: itself, or each text in a mapping, a sequence or a dataclass of them."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            yield from strings(item)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            yield from strings(getattr(value, field.name))


def templates(language: str) -> list[tuple[str, str]]:
    """Each template text in a language, with where it is: every module-level mapping with a template for every
    language."""
    found = []
    for module in MODULES:
        for name, value in vars(module).items():
            if isinstance(value, Mapping) and set(LOCALES) <= set(value):
                found += [(f"{module.__name__}.{name}", text) for text in strings(value[language])]
    return found


def test_the_templates_are_found():
    places = {place for place, _ in templates("ur")}

    assert {"openstall_api.chat.handler.WELCOMES", "openstall_api.chat.asking.QUESTIONS",
            "openstall_api.chat.asking.PARTS", "openstall_api.healing.PHRASES"} <= places
    assert len(templates("ur")) >= 60


@pytest.mark.parametrize("language", sorted(SAID_TO_A_WOMAN))
def test_no_template_speaks_to_the_maker_as_a_woman_only(language):
    wrong = [
        (place, form, text)
        for place, text in templates(language)
        for form in SAID_TO_A_WOMAN[language]
        if form in text
    ]

    assert wrong == [], "put it so that the verb agrees with the item, not the maker: " + repr(wrong[:3])


def test_urdu_uses_words_the_voice_reads_rightly():
    wrong = [(place, word) for place, text in templates("ur") for word in MISREAD["ur"] if word in text]

    assert wrong == [], f"say {MISREAD['ur']} instead: {wrong[:3]}"


BUTTONS = {
    "publish": asking.PUBLISH_BUTTONS,
    "receipt": proof.CONFIRM_BUTTONS,
    "drop": healing.DROP_BUTTONS,
    "advance": advance.ADVANCE_BUTTONS,
}


@pytest.mark.parametrize("name", sorted(BUTTONS))
def test_each_button_fits_whatsapp_and_is_read_as_the_answer_it_says(name):
    """Meta's reply buttons take at most 3 under a message, each title up to 20 characters (Whapi's 25), and a tap
    sends the title back as her message: the first button is her yes, the second her no, in every language."""
    for language, titles in BUTTONS[name].items():
        assert 1 <= len(titles) <= 3, (name, language)
        assert all(len(title) <= 20 for title in titles), (name, language, titles)
        assert proof.is_yes(titles[0]), (name, language, titles[0])
        assert all(proof.is_no(title) for title in titles[1:]), (name, language, titles)


def test_the_voice_reads_a_message_without_its_formatting():
    welcome = handler.WELCOMES["ur"]

    spoken = wording.speakable(welcome)

    assert "*" not in spoken and "\n" not in spoken
    assert spoken.startswith("OpenStall میں خوش آمدید! اپنا سامان بیچنے کے لیے: 1. اپنے ہاتھ سے بنی چیز کی تصویر بھیجیں۔")
    assert wording.speakable("Here is your listing:\n• Clay mug\n• $12.00 each") == (
        "Here is your listing: Clay mug. $12.00 each."
    )


def test_a_message_carries_its_buttons_and_its_english():
    said = wording.say("ur", lambda code: {"ur": "تیار؟", "en": "Ready?"}[code], {"ur": ("ہاں",), "en": ("Yes",)})

    assert (str(said), wording.english_of(said), wording.buttons_of(said)) == ("تیار؟", "Ready?", ("ہاں",))
    assert wording.buttons_of("plain text") == ()


def test_her_listing_is_told_back_in_urdu_with_its_name_in_urdu():
    draft = {"title": "Hand-embroidered cushion cover", "title_local": "ہاتھ کی کڑھائی والا کشن کور",
             "price_usd": "18.00", "capacity_per_week": 4}

    told = asking.described(draft, "ur")

    assert told.startswith("ہاتھ کی کڑھائی والا کشن کور، ")
    assert "cushion" not in told
    assert asking.described(draft, "en").startswith("Hand-embroidered cushion cover, $18.00 each")
    # Before the reader gives one, the English title stands in.
    assert asking.described({"title": "Clay mug"}, "ur") == "Clay mug"
