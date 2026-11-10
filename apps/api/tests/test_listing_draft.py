"""A draft listing from photos and words (spec 3.1, steps 3 and 4): what a new seller sends is read into a draft listing
kept on her chat, and each answer tells her the listing so far and asks one short question, in her language, for what
is still missing, then for her limits (spec 3.3). Her price, capacity, shipping time, city and limits come only from
her own words; a maker already selling is never read for one."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from openstall_agents.adapters import LLMError
from openstall_agents.listing_reader import FACTS_OPEN, QUESTIONS
from openstall_api.chat.handler import WELCOME, WELCOMES
from openstall_api.db import new_session
from openstall_api.events import EventType
from openstall_api.fixtures import SAMPLE_PRODUCT, fixture_photo, fixture_voice_note
from openstall_api.main import app
from openstall_api.models import ChatMessage, ChatSession, ChatState, Event, Seller
from openstall_api.seed import seed

client = TestClient(app)
DEMO_PHONE = "demo-1f4b0c9e"
SELLER = "Web seller 0C9E"
PHOTO = (fixture_photo(), "image/png")
SAMPLES = [PHOTO, (fixture_voice_note(), "audio/wav")]
# Her photo and her words typed in English: she is answered in English.
TYPED = "Cushion covers, $18 each, 4 a week."
SO_FAR = "Your listing so far: Hand-embroidered cushion cover, $18.00 each, 4 a week"
# The sample voice note is Amina's Urdu: her language is saved, and she is answered in Urdu from then on.
# Her item is named in Urdu too: her words are Urdu, so the reader gives its title in Urdu beside the English one.
SO_FAR_UR = "اب تک آپ کا اشتہار: ہاتھ کی کڑھائی والا کشن کور، 18.00 ڈالر فی عدد، ہفتے میں 4"
ASK_DAYS_UR = "آپ کا پارسل امریکہ میں خریدار تک کتنے دن میں پہنچتا ہے؟"
STILL_TO_ASK = (
    "how many days delivery takes, the city it ships from, her lowest price and the days she needs to make an order"
)


def on_the_web(text: str, files: list[tuple[bytes, str]] | None = None) -> dict:
    uploads = [("files", (f"file{index}", data, kind)) for index, (data, kind) in enumerate(files or [])]
    response = client.post(
        "/api/seller-chat/messages", data={"sender": DEMO_PHONE, "text": text}, files=uploads or None
    )
    assert response.status_code == 200, response.text
    return response.json()


def chat_of(db, seller_id: str) -> ChatSession:
    db.expire_all()
    return db.scalars(select(ChatSession).where(ChatSession.seller_id == seller_id)).one()


def draft_events(db) -> list[str]:
    db.expire_all()
    events = db.scalars(select(Event).where(Event.type == EventType.LISTING_DRAFT_UPDATED).order_by(Event.id))
    return [event.payload_json["summary"] for event in events]


def listing_requests(fakes) -> int:
    return sum(1 for call in fakes.llm.calls if FACTS_OPEN in call.prompt)


def test_her_photo_and_voice_note_become_a_draft_and_she_is_asked_one_question_in_urdu(db):
    sent = on_the_web("", SAMPLES)

    assert sent["replies"] == [WELCOMES["ur"], f"{SO_FAR_UR}۔ {ASK_DAYS_UR}"]
    chat = chat_of(db, sent["seller_id"])
    draft = chat.draft_json
    assert draft is not None
    shown = {name: SAMPLE_PRODUCT[name] for name in ("title", "description", "category", "variants")}
    assert {name: draft[name] for name in shown} == shown
    assert draft["title_local"] == SAMPLE_PRODUCT["titles"]["ur"]  # her words are Urdu: her item is named in Urdu
    assert (draft["price_usd"], draft["capacity_per_week"], draft["ship_days"], draft["ship_from_city"]) == (
        "18.00",
        4,
        None,
        None,
    )
    assert draft["words"] == {"price_usd": "اٹھارہ ڈالر", "capacity_per_week": "ہفتے میں چار"}
    assert draft["missing"] == ["ship_days", "ship_from_city", "floor_price_usd", "min_lead_days"]
    assert draft["asked"] == "ship_days"
    assert len(draft["photos"]) == 1 and draft["photos"][0].startswith("/media/uploads/")
    assert "اٹھارہ ڈالر" in draft["source_text"]
    assert draft_events(db) == [
        f"{SELLER}'s listing draft: Hand-embroidered cushion cover, $18.00 each, 4 a week; still to ask: {STILL_TO_ASK}"
    ]
    assert chat.state == ChatState.ASKING


def test_the_chat_api_gives_her_draft_with_her_conversation(db):
    sent = on_the_web("", SAMPLES)

    draft = client.get(f"/api/chats/{sent['seller_id']}").json()["draft"]

    assert draft["title"] == "Hand-embroidered cushion cover"
    assert draft["price_usd"] == "18.00"
    assert draft["words"]["capacity_per_week"] == "ہفتے میں چار"
    assert draft["missing"] == ["ship_days", "ship_from_city", "floor_price_usd", "min_lead_days"]
    assert (draft["asked"], draft["floor_price_usd"], draft["min_lead_days"]) == ("ship_days", None, None)
    assert "source_text" not in draft and "answers" not in draft


def test_she_answers_one_question_at_a_time_and_her_limits_come_last(db):
    first = on_the_web(TYPED, [PHOTO])

    answered = [on_the_web(answer)["replies"] for answer in ("9", "Lahore", "15", "5")]

    assert first["replies"] == [WELCOME, f"{SO_FAR}. {QUESTIONS['ship_days']}"]
    assert answered == [
        [f"Thank you. {SO_FAR}, arrives in 9 days. {QUESTIONS['ship_from_city']}"],
        [f"Thank you. {SO_FAR}, arrives in 9 days, from Lahore. {QUESTIONS['floor_price_usd']}"],
        [
            f"Thank you. {SO_FAR}, arrives in 9 days, from Lahore, lowest $15.00 for a big order. "
            f"{QUESTIONS['min_lead_days']}"
        ],
        [  # nothing left to ask: all of it, and her yes asked for (prompt 19)
            "Thank you. Here is your listing: Hand-embroidered cushion cover, $18.00 each, 4 a week, arrives in 9 days, "
            "from Lahore, lowest $15.00 for a big order, 5 days to make an order. Reply YES to publish it, or tell me "
            "what to change."
        ],
    ]
    draft = chat_of(db, first["seller_id"]).draft_json
    assert draft["words"] == {
        "price_usd": "$18",
        "capacity_per_week": "4 a week",
        "ship_days": "9",
        "ship_from_city": "Lahore",
        "floor_price_usd": "15",
        "min_lead_days": "5",
    }
    assert (draft["floor_price_usd"], draft["min_lead_days"], draft["missing"], draft["asked"]) == ("15.00", 5, [], None)
    assert list(draft["answers"].values()) == ["ship_days", "ship_from_city", "floor_price_usd", "min_lead_days"]
    assert draft_events(db)[-1] == (
        f"{SELLER}'s listing draft has everything it needs: Hand-embroidered cushion cover, $18.00 each, 4 a week, "
        "arrives in 9 days, from Lahore, lowest $15.00 for a big order, 5 days to make an order"
    )


def test_after_her_urdu_voice_note_she_is_asked_in_urdu_whatever_she_types(db):
    on_the_web("", SAMPLES)

    sent = on_the_web("9")

    assert sent["replies"] == [f"شکریہ۔ {SO_FAR_UR}، 9 دن میں پہنچتا ہے۔ پارسل کس شہر سے بھیجا جائے گا؟"]


@pytest.mark.parametrize(
    ("language", "reply"),
    [
        (
            "hi",
            "धन्यवाद। आपकी लिस्टिंग अब तक: Hand-embroidered cushion cover, $18.00 प्रति पीस, हफ़्ते में 4, 9 दिन में "
            "पहुँचता है। पार्सल किस शहर से भेजा जाएगा?",
        ),
        (
            "es",
            "¡Gracias! Tu anuncio hasta ahora: Hand-embroidered cushion cover, US$18.00 cada uno, 4 por semana, llega "
            "en 9 días. ¿Desde qué ciudad lo envías?",
        ),
    ],
)
def test_she_is_asked_in_her_own_language(db, language, reply):
    first = on_the_web(TYPED, [PHOTO])
    db.get(Seller, first["seller_id"]).language = language
    db.commit()

    sent = on_the_web("9")

    assert sent["replies"] == [reply]


def test_without_a_photo_she_is_asked_for_one_first(db):
    sent = on_the_web("I make quilts, $45 each, 3 a week.")

    assert sent["replies"] == [
        WELCOME,
        f"Your listing so far: your item, not named yet, $45.00 each, 3 a week. {QUESTIONS['photos']}",
    ]


def test_a_lowest_price_above_her_price_is_asked_again(db):
    on_the_web("Cushion covers, $18 each, 4 a week. Delivery takes 9 days. It ships from Lahore.", [PHOTO])
    too_high = on_the_web("20")
    on_the_web("15")

    lowered = on_the_web("Sorry, my price is $14 each")

    assert too_high["replies"][0].endswith(QUESTIONS["floor_price_usd"])
    assert lowered["replies"] == [
        "Thank you. Your listing so far: Hand-embroidered cushion cover, $14.00 each, 4 a week, arrives in 9 days, "
        f"from Lahore. {QUESTIONS['floor_price_usd']}"
    ]
    draft = chat_of(db, lowered["seller_id"]).draft_json
    assert (draft["price_usd"], draft["floor_price_usd"], draft["asked"]) == ("14.00", None, "floor_price_usd")
    assert "floor_price_usd" not in draft["words"]


def test_a_price_she_never_said_is_not_listed(db, fakes):
    fakes.llm.queue(
        {
            "title": "Quilt",
            "description": "A hand-stitched quilt.",
            "category": "home textiles",
            "variants": [],
            "price_usd": 25,
            "price_words": "25 dollars",
            "capacity_per_week": 0,
            "capacity_words": "",
            "ship_days": 0,
            "ship_days_words": "",
            "ship_from_city": "",
            "ship_from_city_words": "",
            "floor_price_usd": 20,
            "floor_price_words": "I make quilts",
            "min_lead_days": 0,
            "min_lead_days_words": "",
        }
    )

    sent = on_the_web("I make quilts, ask me the price.")

    draft = chat_of(db, sent["seller_id"]).draft_json
    assert draft["title"] == "Quilt"
    assert (draft["price_usd"], draft["floor_price_usd"]) == (None, None)
    assert {"price_usd", "floor_price_usd"} <= set(draft["missing"])
    assert draft["words"] == {}


def test_a_message_with_nothing_for_a_listing_starts_no_draft(db, fakes):
    sent = on_the_web("Hello")

    assert sent["replies"] == [WELCOME]
    assert chat_of(db, sent["seller_id"]).draft_json is None
    assert draft_events(db) == []
    assert listing_requests(fakes) == 1  # read, and found nothing


def test_a_message_that_changes_nothing_asks_the_same_question_again_but_does_not_tell_the_feed(db):
    on_the_web(TYPED, [PHOTO])

    sent = on_the_web("Hello again")

    assert sent["replies"] == [f"Thank you. {SO_FAR}. {QUESTIONS['ship_days']}"]
    assert len(draft_events(db)) == 1


def test_a_maker_already_selling_is_never_read_for_a_listing(db, fakes):
    seed(db, with_amina=True)
    db.commit()

    played = client.post("/api/dev/sellers/s_priya/messages", json={"text": "Namaste", "receipt": False})

    assert played.status_code == 201, played.text
    assert listing_requests(fakes) == 0
    assert db.scalars(select(ChatSession.draft_json).where(ChatSession.seller_id == "s_priya")).all() == [None]


def fail(*args, **kwargs):
    raise LLMError("the model took too long to answer")


def test_when_the_model_cannot_read_her_listing_her_message_is_still_kept(db, fakes, monkeypatch):
    monkeypatch.setattr(fakes.llm, "generate_json", fail)

    sent = on_the_web("", SAMPLES)

    assert sent["replies"] == [WELCOMES["ur"]]  # her voice note was still heard, in Urdu
    db.expire_all()
    assert db.get(ChatMessage, sent["message_id"]) is not None
    assert chat_of(db, sent["seller_id"]).draft_json is None


def test_when_the_model_cannot_read_her_answer_she_is_asked_again_and_it_is_read_next_time(db, fakes, monkeypatch):
    on_the_web(TYPED, [PHOTO])
    answer = fakes.llm.generate_json
    monkeypatch.setattr(fakes.llm, "generate_json", fail)

    unread = on_the_web("9")
    monkeypatch.setattr(fakes.llm, "generate_json", answer)  # the model answers again
    read = on_the_web("Lahore")

    assert unread["replies"] == [f"Thank you. {SO_FAR}. {QUESTIONS['ship_days']}"]
    # "9" was kept as her answer about delivery, so the next reading counts it; "Lahore" answered the same question.
    assert read["replies"] == [f"Thank you. {SO_FAR}, arrives in 9 days. {QUESTIONS['ship_from_city']}"]
    last = [call for call in fakes.llm.calls if FACTS_OPEN in call.prompt][-1]
    assert f'"words": "9", "answering": "{QUESTIONS["ship_days"]}"' in last.prompt


def test_her_listing_is_read_before_her_message_is_stored(db, fakes, monkeypatch):
    stored_while_reading: list[int] = []
    answer = fakes.llm.generate_json

    def generate_json(prompt, **kwargs):
        if FACTS_OPEN in prompt:
            with new_session() as other:
                stored_while_reading.append(other.scalar(select(func.count()).select_from(ChatMessage)) or 0)
        return answer(prompt, **kwargs)

    monkeypatch.setattr(fakes.llm, "generate_json", generate_json)

    on_the_web("", SAMPLES)

    assert stored_while_reading == [0]


def test_her_earlier_photos_are_read_again_and_listed_once_each(db, fakes):
    first = on_the_web("", [(fixture_photo(), "image/png")])
    on_the_web("Here it is again, $18 each", [(fixture_photo(), "image/png"), (b"\x89PNG another photo", "image/png")])

    draft = chat_of(db, first["seller_id"]).draft_json
    assert len(draft["photos"]) == 2
    last = [call for call in fakes.llm.calls if FACTS_OPEN in call.prompt][-1]
    assert len(last.images) == 3  # her earlier photo, then this message's two
    assert draft["price_usd"] == "18.00"


def test_the_model_is_told_how_she_said_each_thing_who_she_is_and_what_she_was_asked(db, fakes):
    sent = on_the_web("", SAMPLES)
    on_the_web("It ships from Lahore.")

    first, second = [call for call in fakes.llm.calls if FACTS_OPEN in call.prompt]
    assert '"maker": "a new seller"' in first.prompt  # her first message: she has no name yet
    assert '"how": "voice note", "language": "ur"' in first.prompt
    assert '"answering": null' in first.prompt
    assert f'"maker": "{SELLER}"' in second.prompt
    # She was asked about delivery and answered with her city: the model is told both.
    assert (
        f'"how": "typed", "language": null, "words": "It ships from Lahore.", "answering": "{QUESTIONS["ship_days"]}"'
        in second.prompt
    )
    assert db.get(Seller, sent["seller_id"]).name == SELLER
