"""Confirming and publishing a listing (spec 3.1, steps 5 and 6): once nothing is left to ask, the seller gets a summary
in her language and must reply "yes"; only then is her listing published, with her seller policy (spec 3.3). Search
and the catalog find it at once, and the offer rules take her policy."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from openstall_agents.listing_reader import FACTS_OPEN
from openstall_allocator import lowest_allowed_price
from openstall_api.events import EventType
from openstall_api.fixtures import fixture_photo, fixture_voice_note
from openstall_api.main import app
from openstall_api.models import ChatSession, ChatState, Event, Product, ProductStatus, Seller
from openstall_api.offer_rules import listing_of, seller_policy
from openstall_api.search import SearchFilters, find_products
from openstall_api.settings import get_settings

client = TestClient(app)
DEMO_PHONE = "demo-5e7d2a10"
SELLER = "Web seller 2A10"
PHOTO = (fixture_photo(), "image/png")
EVERYTHING = "Cushion covers, $18 each, 4 a week. Delivery takes 9 days. It ships from Lahore."
LISTING = (
    "Hand-embroidered cushion cover, $18.00 each, 4 a week, arrives in 9 days, from Lahore, lowest $15.00 for a big "
    "order, 5 days to make an order"
)
CONFIRM = "Reply YES to publish it, or tell me what to change."


def on_the_web(text: str, files: list[tuple[bytes, str]] | None = None) -> dict:
    uploads = [("files", (f"file{index}", data, kind)) for index, (data, kind) in enumerate(files or [])]
    response = client.post(
        "/api/seller-chat/messages", data={"sender": DEMO_PHONE, "text": text}, files=uploads or None
    )
    assert response.status_code == 200, response.text
    return response.json()


def ready_to_confirm() -> dict:
    """A seller who has given her whole listing and her limits, typed in English."""
    on_the_web(EVERYTHING, [PHOTO])
    on_the_web("15")
    return on_the_web("5")


def chat_of(db, seller_id: str) -> ChatSession:
    db.expire_all()
    return db.scalars(select(ChatSession).where(ChatSession.seller_id == seller_id)).one()


def products_of(db, seller_id: str) -> list[Product]:
    db.expire_all()
    return list(db.scalars(select(Product).where(Product.seller_id == seller_id)))


def listing_requests(fakes) -> int:
    return sum(1 for call in fakes.llm.calls if FACTS_OPEN in call.prompt)


def test_once_nothing_is_missing_she_gets_her_listing_back_and_must_reply_yes(db):
    sent = ready_to_confirm()

    assert sent["replies"] == [f"Thank you. Here is your listing: {LISTING}. {CONFIRM}"]
    assert chat_of(db, sent["seller_id"]).state == ChatState.AWAITING_CONFIRMATION
    assert products_of(db, sent["seller_id"]) == []  # never published before she confirms


def test_her_yes_publishes_her_listing_with_her_words_her_photos_and_her_policy(db, fakes):
    sent = ready_to_confirm()
    read_before = listing_requests(fakes)

    yes = on_the_web("Yes!")

    seller = db.get(Seller, sent["seller_id"])
    stall = f"{get_settings().WEB_BASE_URL}/stall/{seller.id}"
    assert yes["replies"] == [f"Your listing is live! AI shopping agents can find it now. Your stall: {stall}"]
    assert listing_requests(fakes) == read_before  # her yes is not read for a listing
    [product] = products_of(db, seller.id)
    assert (product.status, product.data_source.value) == (ProductStatus.LIVE, "live")
    assert (product.title, product.category, product.variants_json) == (
        "Hand-embroidered cushion cover",
        "home textiles",
        ["red", "teal", "mustard"],
    )
    assert (product.price_usd, product.capacity_per_week, product.ship_days, product.ship_from_city) == (
        Decimal("18.00"),
        4,
        9,
        "Lahore",
    )
    assert len(product.photos_json) == 1 and product.photos_json[0].startswith("uploads/")
    assert client.get(f"/media/{product.photos_json[0]}").content == fixture_photo()
    assert product.source_text is not None and EVERYTHING in product.source_text
    assert seller.policy_json == {
        "seller_id": seller.id,
        "floor_price_usd": "15.00",
        "max_discount_pct": "16.67",
        "capacity_per_week": 4,
        "min_lead_days": 5,
    }
    assert lowest_allowed_price(seller_policy(seller, product), listing_of(product)) == Decimal("15.00")
    assert seller.city == "Lahore"
    assert chat_of(db, seller.id).state == ChatState.LIVE
    published = db.scalars(select(Event).where(Event.type == EventType.LISTING_PUBLISHED)).one()
    assert published.payload_json["summary"] == f"{SELLER}'s listing is live: {LISTING}"
    assert published.entity_id == product.id


def test_search_and_the_catalog_find_it_at_once(db):
    ready_to_confirm()
    before = client.get("/catalog.json").json()  # built and kept for a minute

    on_the_web("yes")

    [product] = db.scalars(select(Product).where(Product.data_source == "live"))
    after = client.get("/catalog.json").json()
    assert product.id not in str(before) and product.id in str(after)
    found = find_products(db, "embroidered cushion cover", SearchFilters(), date(2026, 11, 6))
    assert product.id in [result.product_id for result in found]


@pytest.mark.parametrize("yes", ["ہاں", "ji haan", "👍"])
def test_she_says_yes_in_her_own_words(db, yes):
    ready_to_confirm()

    on_the_web(yes)

    assert db.scalar(select(Product.status).where(Product.data_source == "live")) == ProductStatus.LIVE


def test_after_her_urdu_voice_note_she_confirms_in_urdu(db):
    on_the_web("", [PHOTO, (fixture_voice_note(), "audio/wav")])
    for answer in ("9", "Lahore", "15"):
        on_the_web(answer)

    summary = on_the_web("5")
    live = on_the_web("ہاں")

    seller_id = live["seller_id"]
    assert summary["replies"] == [
        "شکریہ۔ یہ آپ کی لسٹنگ ہے: Hand-embroidered cushion cover، 18.00 ڈالر فی عدد، ہفتے میں 4، 9 دن میں پہنچتا ہے، "
        "Lahore سے، بڑے آرڈر پر کم سے کم 15.00 ڈالر، آرڈر تیار کرنے میں 5 دن۔ اسے شائع کرنے کے لیے \"ہاں\" لکھیں، یا "
        "بتائیں کیا بدلنا ہے۔"
    ]
    assert live["replies"] == [
        "آپ کی لسٹنگ اب لائیو ہے! AI شاپنگ ایجنٹ اب اسے ڈھونڈ سکتے ہیں۔ آپ کا اسٹال: "
        f"{get_settings().WEB_BASE_URL}/stall/{seller_id}"
    ]


def test_a_change_instead_of_yes_is_read_and_she_gets_her_listing_back_again(db):
    ready_to_confirm()

    changed = on_the_web("Make it $20 each")

    assert changed["replies"] == [
        f"Thank you. Here is your listing: {LISTING.replace('$18.00', '$20.00')}. {CONFIRM}"
    ]
    assert products_of(db, changed["seller_id"]) == []
    assert chat_of(db, changed["seller_id"]).state == ChatState.AWAITING_CONFIRMATION


def test_a_no_publishes_nothing(db):
    ready_to_confirm()

    no = on_the_web("No")

    assert no["replies"] == [f"Thank you. Here is your listing: {LISTING}. {CONFIRM}"]
    assert products_of(db, no["seller_id"]) == []


def test_a_change_that_leaves_something_missing_goes_back_to_asking(db):
    ready_to_confirm()

    lowered = on_the_web("Sorry, my price is $14 each")  # now below her lowest price, which is asked again

    assert lowered["replies"][0].endswith(
        "For a big order, what is the lowest price you would take for one, in US dollars?"
    )
    assert chat_of(db, lowered["seller_id"]).state == ChatState.ASKING


def test_once_live_her_messages_are_not_read_for_a_listing_and_she_is_told_where_it_is(db, fakes):
    ready_to_confirm()
    on_the_web("yes")
    read_before = listing_requests(fakes)

    later = on_the_web("Thank you!")

    stall = f"{get_settings().WEB_BASE_URL}/stall/{later['seller_id']}"
    assert later["replies"] == [f"Thank you. Your listing is live: {stall}"]
    assert listing_requests(fakes) == read_before
    assert len(products_of(db, later["seller_id"])) == 1


def test_the_chat_api_shows_her_live_listing_instead_of_the_draft(db):
    confirming = ready_to_confirm()
    waiting = client.get(f"/api/chats/{confirming['seller_id']}").json()

    on_the_web("yes")
    live = client.get(f"/api/chats/{confirming['seller_id']}").json()

    assert (waiting["draft"]["confirming"], waiting["listing"]) == (True, None)
    assert live["draft"] is None
    [product] = products_of(db, confirming["seller_id"])
    assert live["listing"] == {
        "product_id": product.id,
        "title": "Hand-embroidered cushion cover",
        "price_usd": "18.00",
        "stall_path": f"/stall/{confirming['seller_id']}",
    }
