"""Confirming and publishing her listing (spec 3.1, steps 5 and 6): once nothing is left to ask, she is sent a summary
in her language and must reply "yes"; only then is her listing saved and published, with the limits her seller agent
keeps to (spec 3.3). Never before she confirms.

publish() runs in her message's transaction: the product goes live with the photos her chat kept and her own words
(Product.source_text, so a wrong reading can be traced), her seller policy is set from her limits, her chat moves to
live, and the live feed is told. Search reads live listings from the database, so it finds the listing as soon as the
transaction commits; the caller then forgets the cached /catalog.json (feeds.clear_catalog_cache).
"""

from decimal import ROUND_CEILING, Decimal
from typing import Any

from sqlalchemy.orm import Session

from openstall_api.chat.asking import described
from openstall_api.chat.voice import Heard
from openstall_api.events import EventType, record_event
from openstall_api.media import URL_PREFIX
from openstall_api.models import ChatSession, ChatState, DataSource, Product, ProductStatus, Seller
from openstall_api.offer_rules import seller_policy
from openstall_api.proof import is_yes
from openstall_api.settings import get_settings

CENT = Decimal("0.01")
HUNDRED = Decimal(100)
MEDIA = "/media/"


def said_yes(text: str, heard: Heard, photos: int) -> bool:
    """Whether her message is her "yes" to publishing, in any of the demo's languages: typed, or a voice note that
    says only that. A message with a photo is something to read, never a yes."""
    if photos:
        return False
    if text.strip():
        return not heard.texts and is_yes(text)
    return heard.transcript is not None and is_yes(heard.transcript)


def policy_of(seller_id: str, draft: dict[str, Any]) -> dict[str, Any]:
    """Her seller policy (spec 3.3) from her listing and her limits, money as strings so it stays exact. Her largest
    discount is the gap between her price and her lowest price, rounded up to a hundredth of a percent: the offer rules
    take the higher of her lowest price and her discounted price, so her lowest price is the one that holds."""
    price = Decimal(str(draft["price_usd"]))
    floor = Decimal(str(draft["floor_price_usd"]))
    discount = ((price - floor) * HUNDRED / price).quantize(CENT, rounding=ROUND_CEILING)
    return {
        "seller_id": seller_id,
        "floor_price_usd": str(floor),
        "max_discount_pct": str(min(discount, HUNDRED)),
        "capacity_per_week": int(draft["capacity_per_week"]),
        "min_lead_days": int(draft["min_lead_days"]),
    }


def kept_photo(url: str) -> str:
    """A chat photo as a product keeps it: "/media/uploads/a.png" becomes "uploads/a.png", which catalog.photo_path
    serves again."""
    return url.removeprefix(MEDIA) if url.startswith(URL_PREFIX) else url


def stall_url(seller: Seller) -> str:
    """Her stall page on the web app."""
    return f"{get_settings().WEB_BASE_URL}/stall/{seller.id}"


def publish(session: Session, chat: ChatSession, seller: Seller) -> Product:
    """Her listing, live, from her draft, with her seller policy, in the caller's transaction. Raises PolicyError if
    the offer rules would refuse her policy, so nothing is published that her agent could not quote."""
    draft: dict[str, Any] = dict(chat.draft_json or {})
    product = Product(
        seller_id=seller.id,
        title=draft["title"],
        description=draft.get("description") or "",
        category=draft["category"],
        variants_json=list(draft.get("variants") or []),
        price_usd=Decimal(str(draft["price_usd"])),
        capacity_per_week=int(draft["capacity_per_week"]),
        ship_days=int(draft["ship_days"]),
        ship_from_city=draft["ship_from_city"],
        photos_json=[kept_photo(url) for url in draft["photos"]],
        source_text=draft.get("source_text"),
        status=ProductStatus.LIVE,
        data_source=DataSource.LIVE,
    )
    seller.policy_json = policy_of(seller.id, draft)
    seller_policy(seller, product)  # the offer rules' own check of her policy
    seller.city = seller.city or draft["ship_from_city"]
    session.add(product)
    session.flush()
    chat.state = ChatState.LIVE
    chat.draft_json = {**draft, "asked": None, "published": product.id}
    record_event(
        session,
        EventType.LISTING_PUBLISHED,
        f"{seller.name}'s listing is live: {described(draft)}",
        entity_id=product.id,
        payload={"seller_id": seller.id, "chat_id": chat.id, "product_id": product.id, "title": product.title},
    )
    return product
