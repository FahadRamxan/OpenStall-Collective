"""A draft listing from photos and words (spec 3.1, step 3): what a new seller sends is read into a draft listing kept
on her chat, told back to her with what it still needs. Her price, capacity, shipping time and city come only from
her own words; a maker already selling is never read for one."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from openstall_agents.adapters import LLMError
from openstall_agents.listing_reader import FACTS_OPEN
from openstall_api.chat.handler import WELCOME
from openstall_api.db import new_session
from openstall_api.events import EventType
from openstall_api.fixtures import SAMPLE_PRODUCT, fixture_photo, fixture_voice_note
from openstall_api.main import app
from openstall_api.models import ChatMessage, ChatSession, ChatState, Event, Seller
from openstall_api.seed import seed

client = TestClient(app)
DEMO_PHONE = "demo-1f4b0c9e"
SELLER = "Web seller 0C9E"
SAMPLES = [(fixture_photo(), "image/png"), (fixture_voice_note(), "audio/wav")]
SO_FAR = "Your listing so far: Hand-embroidered cushion cover, $18.00 each, 4 a week."
STILL_NEEDED = "Still needed: how many days delivery takes and the city it ships from."


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


def test_her_photo_and_voice_note_become_a_draft_with_her_own_words_for_the_numbers(db):
    sent = on_the_web("", SAMPLES)

    assert sent["replies"] == [WELCOME, f"{SO_FAR} {STILL_NEEDED}"]
    draft = chat_of(db, sent["seller_id"]).draft_json
    assert draft is not None
    assert {name: draft[name] for name in ("title", "description", "category", "variants")} == SAMPLE_PRODUCT
    assert (draft["price_usd"], draft["capacity_per_week"], draft["ship_days"], draft["ship_from_city"]) == (
        "18.00",
        4,
        None,
        None,
    )
    assert draft["words"] == {"price_usd": "اٹھارہ ڈالر", "capacity_per_week": "ہفتے میں چار"}
    assert draft["missing"] == ["ship_days", "ship_from_city"]
    assert len(draft["photos"]) == 1 and draft["photos"][0].startswith("/media/uploads/")
    assert "اٹھارہ ڈالر" in draft["source_text"]
    assert draft_events(db) == [
        f"{SELLER}'s listing draft: Hand-embroidered cushion cover, $18.00 each, 4 a week; still to ask: how many days "
        "delivery takes and the city it ships from"
    ]
    assert chat_of(db, sent["seller_id"]).state == ChatState.COLLECTING


def test_the_chat_api_gives_her_draft_with_her_conversation(db):
    sent = on_the_web("", SAMPLES)

    draft = client.get(f"/api/chats/{sent['seller_id']}").json()["draft"]

    assert draft["title"] == "Hand-embroidered cushion cover"
    assert draft["price_usd"] == "18.00"
    assert draft["words"]["capacity_per_week"] == "ہفتے میں چار"
    assert draft["missing"] == ["ship_days", "ship_from_city"]
    assert "source_text" not in draft


def test_what_she_says_next_fills_the_rest_and_keeps_what_she_said_before(db):
    on_the_web("", SAMPLES)

    sent = on_the_web("Delivery takes 9 days. It ships from Lahore.")

    assert sent["replies"] == [
        "Thank you, I have your message. Your listing so far: Hand-embroidered cushion cover, $18.00 each, 4 a week, "
        "arrives in 9 days, from Lahore. That is everything it needs."
    ]
    draft = chat_of(db, sent["seller_id"]).draft_json
    assert (draft["price_usd"], draft["ship_days"], draft["ship_from_city"], draft["missing"]) == (
        "18.00",
        9,
        "Lahore",
        [],
    )
    assert draft["words"]["ship_days"] == "Delivery takes 9 days"
    assert draft_events(db)[-1].startswith(f"{SELLER}'s listing draft has everything it needs: Hand-embroidered")


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
        }
    )

    sent = on_the_web("I make quilts, ask me the price.")

    draft = chat_of(db, sent["seller_id"]).draft_json
    assert draft["title"] == "Quilt"
    assert draft["price_usd"] is None
    assert "price_usd" in draft["missing"]
    assert draft["words"] == {}


def test_a_message_with_nothing_for_a_listing_starts_no_draft(db, fakes):
    sent = on_the_web("Hello")

    assert sent["replies"] == [WELCOME]
    assert chat_of(db, sent["seller_id"]).draft_json is None
    assert draft_events(db) == []
    assert listing_requests(fakes) == 1  # read, and found nothing


def test_a_message_that_changes_nothing_tells_her_the_listing_again_but_not_the_feed(db):
    on_the_web("", SAMPLES)

    sent = on_the_web("Hello again")

    assert sent["replies"] == [f"Thank you, I have your message. {SO_FAR} {STILL_NEEDED}"]
    assert len(draft_events(db)) == 1


def test_a_maker_already_selling_is_never_read_for_a_listing(db, fakes):
    seed(db, with_amina=True)
    db.commit()

    played = client.post("/api/dev/sellers/s_priya/messages", json={"text": "Namaste", "receipt": False})

    assert played.status_code == 201, played.text
    assert listing_requests(fakes) == 0
    assert db.scalars(select(ChatSession.draft_json).where(ChatSession.seller_id == "s_priya")).all() == [None]


def test_when_the_model_cannot_read_her_listing_her_message_is_still_kept(db, fakes, monkeypatch):
    def fail(*args, **kwargs):
        raise LLMError("the model took too long to answer")

    monkeypatch.setattr(fakes.llm, "generate_json", fail)

    sent = on_the_web("", SAMPLES)

    assert sent["replies"] == [WELCOME]
    db.expire_all()
    assert db.get(ChatMessage, sent["message_id"]) is not None
    assert chat_of(db, sent["seller_id"]).draft_json is None


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


def test_the_model_is_told_how_she_said_each_thing_and_who_she_is(db, fakes):
    sent = on_the_web("", SAMPLES)
    on_the_web("It ships from Lahore.")

    first, second = [call for call in fakes.llm.calls if FACTS_OPEN in call.prompt]
    assert '"maker": "a new seller"' in first.prompt  # her first message: she has no name yet
    assert '"how": "voice note", "language": "ur"' in first.prompt
    assert f'"maker": "{SELLER}"' in second.prompt
    assert '"how": "typed", "language": null, "words": "It ships from Lahore."' in second.prompt
    assert db.get(Seller, sent["seller_id"]).name == SELLER
