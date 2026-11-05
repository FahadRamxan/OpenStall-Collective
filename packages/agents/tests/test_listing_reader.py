"""Reading a listing from a seller's chat (spec 3.1, steps 3 and 4): the model reads her photos and words; code keeps a
price, a capacity, a shipping time, a city and her limits only with her own words for them, so nothing she did not
say is ever listed."""

from decimal import Decimal

import pytest

from openstall_agents.adapters import FakeLLM, LLMCall, Media
from openstall_agents.fake_answers import fake_answer
from openstall_agents.listing_reader import (
    CATEGORIES,
    FACTS_OPEN,
    LISTING_SCHEMA,
    MAX_PHOTOS_READ,
    QUESTIONS,
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
        "floor_price_usd": 0,
        "floor_price_words": "",
        "min_lead_days": 0,
        "min_lead_days_words": "",
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


# Prompt 18: her words must name what a number counts, unless they answer its question; and her limits.


def test_words_that_name_nothing_never_carry_a_number():
    said = [Said("Cushion covers, embroidered by hand. Price is 18 dollars.")]

    assert draft_from(answer(price_usd=18, price_words="Cushion covers"), said).price_usd is None
    assert draft_from(answer(price_usd=18, price_words="18 dollars"), said).price_usd == Decimal("18.00")


@pytest.mark.parametrize(
    ("said", "fields", "kept"),
    [
        ("I make 15 a week", {"capacity_per_week": 15, "capacity_words": "15 a week"}, 15),
        ("Main hafte mein 15 banati hun", {"capacity_per_week": 15, "capacity_words": "hafte mein 15"}, 15),
        ("Hago 15 por semana", {"capacity_per_week": 15, "capacity_words": "15 por semana"}, 15),
        ("मैं हफ़्ते में 15 बनाती हूँ", {"capacity_per_week": 15, "capacity_words": "हफ़्ते में 15"}, 15),
        ("I can make 15", {"capacity_per_week": 15, "capacity_words": "make 15"}, None),
        ("Parcel 9 din mein pohanchta hai", {"ship_days": 9, "ship_days_words": "9 din"}, 9),
        ("It takes 9 days from today", {"ship_days": 9, "ship_days_words": "9 days"}, 9),
        ("It goes out today, 9", {"ship_days": 9, "ship_days_words": "today, 9"}, None),
        ("US$18 cada uno", {"price_usd": 18, "price_words": "US$18"}, Decimal("18.00")),
        ("Price 18 each", {"price_usd": 18, "price_words": "18 each"}, None),  # rupees, or dollars? Ask.
    ],
)
def test_her_words_for_a_number_name_what_it_counts_in_her_language(said, fields, kept):
    reading = draft_from(answer(**fields), [Said(said)])

    fact = next(name for name in ("price_usd", "capacity_per_week", "ship_days") if name in fields)
    assert getattr(reading, fact) == kept


def test_a_bare_number_counts_only_as_the_answer_to_its_own_question():
    said = [Said("Cushion covers, $18"), Said("9", asked="ship_days")]

    as_asked = draft_from(answer(ship_days=9, ship_days_words="9"), said)
    misplaced = draft_from(answer(capacity_per_week=9, capacity_words="9"), said)

    assert (as_asked.ship_days, as_asked.words) == (9, {"ship_days": "9"})
    assert misplaced.capacity_per_week is None


def test_a_number_is_matched_as_a_whole_number_not_part_of_another():
    said = [Said("19", asked="ship_days"), Said("18.50", asked="price_usd")]

    assert draft_from(answer(ship_days=9, ship_days_words="9"), said).ship_days is None
    assert draft_from(answer(price_usd=18, price_words="18"), said).price_usd is None
    assert draft_from(answer(price_usd=18.5, price_words="18.50"), said).price_usd == Decimal("18.50")


def test_a_number_written_out_counts_as_the_answer_to_its_question():
    said = [Said("نو", voice_note=True, language="ur", asked="min_lead_days")]

    assert draft_from(answer(min_lead_days=9, min_lead_days_words="نو"), said).min_lead_days == 9


def test_her_lowest_price_is_never_above_her_price():
    said = [Said("$18 each. For a big order my lowest is 15 dollars, or 20 dollars.")]

    kept = draft_from(answer(price_usd=18, price_words="$18", floor_price_usd=15, floor_price_words="15 dollars"), said)
    above = draft_from(answer(price_usd=18, price_words="$18", floor_price_usd=20, floor_price_words="20 dollars"), said)

    assert (kept.floor_price_usd, kept.words["floor_price_usd"]) == (Decimal("15.00"), "15 dollars")
    assert above.floor_price_usd is None
    assert "floor_price_usd" not in above.words


@pytest.mark.parametrize(("days", "kept"), [(1, 1), (5, 5), (90, 90), (0, None), (91, None)])
def test_the_fewest_days_to_make_an_order_is_1_to_90(days, kept):
    said = [Said(f"I need {days} days to make an order.")]

    assert draft_from(answer(min_lead_days=days, min_lead_days_words=f"{days} days"), said).min_lead_days == kept


def test_the_model_is_told_which_question_each_answer_answers():
    llm = FakeLLM(replies=[answer()])

    read_listing(llm, [Said("Cushion covers"), Said("9", asked="ship_days")], [], maker="Amina")

    prompt = llm.calls[0].prompt
    assert '"words": "Cushion covers", "answering": null' in prompt
    assert f'"words": "9", "answering": "{QUESTIONS["ship_days"]}"' in prompt
    assert QUESTIONS["ship_days"] == "How many days does your parcel take to reach a buyer in the US?"
    assert "answering" in (llm.calls[0].system or "")


def test_fake_mode_reads_a_bare_answer_as_the_answer_to_its_question():
    llm = FakeLLM(responder=fake_answer)
    answers = [
        Said("9", asked="ship_days"),
        Said("Lahore", asked="ship_from_city"),
        Said("15", asked="floor_price_usd"),
        Said("5.", asked="min_lead_days"),
    ]

    reading = read_listing(llm, [Said(URDU, True, "ur"), *answers], [SAMPLE_PHOTO], maker="Amina")

    assert (reading.price_usd, reading.capacity_per_week) == (Decimal("18.00"), 4)
    assert (reading.ship_days, reading.ship_from_city) == (9, "Lahore")
    assert (reading.floor_price_usd, reading.min_lead_days) == (Decimal("15.00"), 5)
    assert reading.words["min_lead_days"] == "5"


def test_fake_mode_finds_her_limits_in_plain_english_and_keeps_them_apart_from_her_price():
    llm = FakeLLM(responder=fake_answer)
    said = [Said("Quilts, 45 dollars."), Said("My lowest is 40 dollars, and I need 6 days to make an order.")]

    reading = read_listing(llm, said, [], maker="Priya")

    assert (reading.price_usd, reading.floor_price_usd, reading.min_lead_days) == (Decimal("45.00"), Decimal("40.00"), 6)
