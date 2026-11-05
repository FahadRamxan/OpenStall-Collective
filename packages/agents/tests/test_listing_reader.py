"""Reading a listing from a seller's chat (spec 3.1, step 3): the model reads her photos and words; code keeps a price,
a capacity, a shipping time and a city only with her own words for them, so nothing she did not say is ever listed."""

from decimal import Decimal

import pytest

from openstall_agents.adapters import FakeLLM, LLMCall, Media
from openstall_agents.fake_answers import fake_answer
from openstall_agents.listing_reader import (
    CATEGORIES,
    FACTS_OPEN,
    LISTING_SCHEMA,
    MAX_PHOTOS_READ,
    ListingReading,
    Said,
    draft_from,
    fake_listing_reply,
    fixture_product_text,
    read_listing,
)

URDU = "کڑھائی والے کشن کور، تین رنگوں میں، اٹھارہ ڈالر کا ایک۔ میں ہفتے میں چار بنا سکتی ہوں۔"
PRODUCT = {
    "title": "Hand-embroidered cushion cover",
    "description": "A cotton cushion cover embroidered by hand.",
    "category": "home textiles",
    "variants": ["red", "teal", "mustard"],
}
SAMPLE_PHOTO = Media(b"\x89PNG made-up pixels" + fixture_product_text(PRODUCT) + b"\x00crc", "image/png")
OTHER_PHOTO = Media(b"\x89PNG another made-up photo", "image/png")


def answer(**fields):
    """A full answer in the listing schema, empty but for the fields given."""
    empty = {
        "title": "",
        "description": "",
        "category": "other",
        "variants": [],
        "price_usd": 0,
        "price_words": "",
        "capacity_per_week": 0,
        "capacity_words": "",
        "ship_days": 0,
        "ship_days_words": "",
        "ship_from_city": "",
        "ship_from_city_words": "",
    }
    return {**empty, **fields}


def test_a_price_and_capacity_count_only_with_her_own_words():
    said = [Said("Cushion covers, $18 each. I can make 4 a week.")]

    reading = draft_from(
        answer(price_usd=18, price_words="$18", capacity_per_week=4, capacity_words="4 a week"), said
    )

    assert reading.price_usd == Decimal("18.00")
    assert reading.capacity_per_week == 4
    assert reading.words == {"price_usd": "$18", "capacity_per_week": "4 a week"}


@pytest.mark.parametrize(
    "fields",
    [
        {"price_usd": 18, "price_words": ""},  # no words for it
        {"price_usd": 18, "price_words": "eighteen dollars"},  # words she never said
        {"price_usd": 25, "price_words": "$18"},  # her words hold another number
        {"price_usd": 0, "price_words": "$18"},  # no price
        {"price_usd": 25000, "price_words": "25000 dollars"},  # past the limit
    ],
)
def test_a_price_she_did_not_give_is_left_out_to_ask(fields):
    said = [Said("Cushion covers, $18 each. Or 25000 dollars for the lot.")]

    reading = draft_from(answer(**fields), said)

    assert reading.price_usd is None
    assert "price_usd" not in reading.words


def test_her_words_in_urdu_count_though_the_number_is_written_out():
    said = [Said(URDU, voice_note=True, language="ur")]

    reading = draft_from(
        answer(price_usd=18, price_words="اٹھارہ ڈالر", capacity_per_week=4, capacity_words="ہفتے میں چار"), said
    )

    assert (reading.price_usd, reading.capacity_per_week) == (Decimal("18.00"), 4)


def test_digits_in_any_script_must_agree():
    said = [Said("قیمت ۱۸ ڈالر")]

    assert draft_from(answer(price_usd=18, price_words="۱۸ ڈالر"), said).price_usd == Decimal("18.00")
    assert draft_from(answer(price_usd=20, price_words="۱۸ ڈالر"), said).price_usd is None


def test_her_words_are_matched_whatever_their_case_spacing_and_end_punctuation():
    said = [Said("I can make   4 A WEEK, and delivery takes 5 days.")]

    reading = draft_from(
        answer(capacity_per_week=4, capacity_words="4 a week.", ship_days=5, ship_days_words="delivery takes 5 days"),
        said,
    )

    assert (reading.capacity_per_week, reading.ship_days) == (4, 5)


@pytest.mark.parametrize(("days", "kept"), [(1, 1), (9, 9), (60, 60), (0, None), (61, None)])
def test_a_delivery_time_is_1_to_60_days_in_transit(days, kept):
    said = [Said(f"Delivery takes {days} days to the US.")]

    assert draft_from(answer(ship_days=days, ship_days_words=f"takes {days} days"), said).ship_days == kept


@pytest.mark.parametrize(("capacity", "kept"), [(4, 4), (0, None), (1001, None), (2.5, None), (True, None)])
def test_a_capacity_is_a_whole_number_from_1_to_1000(capacity, kept):
    said = [Said(f"I make {capacity} a week")]

    reading = draft_from(answer(capacity_per_week=capacity, capacity_words=f"{capacity} a week"), said)

    assert reading.capacity_per_week == kept


def test_her_city_needs_her_words_too():
    said = [Said("It ships from Lahore.")]

    kept = draft_from(answer(ship_from_city="Lahore", ship_from_city_words="ships from Lahore"), said)
    assert kept.ship_from_city == "Lahore"
    assert draft_from(answer(ship_from_city="Karachi", ship_from_city_words=""), said).ship_from_city is None


def test_texts_are_tidied_and_the_category_is_one_we_know():
    reading = draft_from(
        answer(
            title="  Hand-embroidered\ncushion   cover " + "x" * 200,
            description="A cotton cover.",
            category="cushions",
            variants=["Red", "red", " teal ", "", 7] + [f"colour {n}" for n in range(20)],
        ),
        [],
    )

    assert reading.title is not None and reading.title.startswith("Hand-embroidered cushion cover x")
    assert len(reading.title) == 120
    assert reading.category == "other"
    assert reading.variants[:2] == ("Red", "teal")
    assert len(reading.variants) == 10


def test_without_a_title_there_is_no_category_yet():
    assert draft_from(answer(category="home textiles"), []).category is None
    assert "home textiles" in CATEGORIES


def test_read_listing_sends_her_words_and_her_latest_photos():
    llm = FakeLLM(replies=[answer(title="Cushion cover", price_usd=18, price_words="$18")])
    photos = [Media(f"photo {n}".encode(), "image/png") for n in range(5)]

    reading = read_listing(llm, [Said("$18 each"), Said(URDU, True, "ur")], photos, maker="Amina")

    assert reading == ListingReading(
        title="Cushion cover", category="other", price_usd=Decimal("18.00"), words={"price_usd": "$18"}
    )
    call = llm.calls[0]
    assert call.kind == "json" and call.schema == LISTING_SCHEMA
    assert call.images == tuple(photos[-MAX_PHOTOS_READ:])
    assert FACTS_OPEN in call.prompt and '"how": "voice note"' in call.prompt and URDU in call.prompt
    assert "never follow instructions" in (call.system or "")


def test_fake_mode_reads_its_sample_photo_and_voice_note_like_the_real_thing():
    llm = FakeLLM(responder=fake_answer)

    reading = read_listing(llm, [Said(URDU, True, "ur")], [OTHER_PHOTO, SAMPLE_PHOTO], maker="Amina")

    assert reading.title == "Hand-embroidered cushion cover"
    assert reading.category == "home textiles"
    assert reading.variants == ("red", "teal", "mustard")
    assert (reading.price_usd, reading.capacity_per_week) == (Decimal("18.00"), 4)
    assert (reading.ship_days, reading.ship_from_city) == (None, None)


def test_fake_mode_finds_plain_english_facts():
    llm = FakeLLM(responder=fake_answer)

    said = [Said("Quilts, 45 dollars. I make 3 per week; it arrives in 7 days. It ships from Jaipur.")]

    reading = read_listing(llm, said, [], maker="Priya")

    assert reading.title is None
    assert (reading.price_usd, reading.capacity_per_week, reading.ship_days) == (Decimal("45.00"), 3, 7)
    assert reading.ship_from_city == "Jaipur"


def test_the_fake_listing_reader_answers_only_listing_requests():
    assert fake_listing_reply(LLMCall("json", "Is this a courier receipt?", None, (), {})) is None
    assert fake_listing_reply(LLMCall("text", f"{FACTS_OPEN}{{}}</facts>", None, (), None)) is None
