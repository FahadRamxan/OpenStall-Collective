"""What the stalls sell, read from the database: listings for the web app and for the agent storefront.

Agents read a listing in full the same way everywhere: the MCP tool get_product, GET /catalog/{product_id}.json and
each entry of GET /catalog.json are all a CatalogEntry made by catalog_entry() or catalog_entries().
"""

import re
from decimal import Decimal
from typing import Any, Self
from urllib.parse import quote

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from openstall_api.models import DataSource, Passport, Product, ProductStatus, Seller
from openstall_api.settings import Settings
from openstall_trust import trust_score

# What our ids look like (s_amina, p_3f9a1c7e2b40). Anything else is not looked up: it cannot be one, and Postgres
# would refuse some characters (NUL) with an error instead of "not found".
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


class NotFound(LookupError):
    """No live listing or trust card has that id. The message says so in words an agent or a person can act on."""


def photo_path(stored: str) -> str:
    """Where the API serves a stored photo. Seed photos live in assets/seed and are served under /media/seed/."""
    if stored.startswith(("http://", "https://")):
        return stored
    return "/media/" + stored.lstrip("/")


def public_url(settings: Settings, path: str) -> str:
    """A path on the API as a full URL from outside (PUBLIC_BASE_URL). A full URL is returned as it is."""
    if path.startswith(("http://", "https://")):
        return path
    return settings.PUBLIC_BASE_URL + "/" + path.lstrip("/")


class ProductOut(BaseModel):
    id: str
    seller_id: str
    title: str
    description: str
    category: str
    variants: list[str]
    price_usd: Decimal  # sent as a string such as "16.00", so it stays exact
    capacity_per_week: int
    ship_days: int
    ship_from_city: str
    photos: list[str]  # paths on the API, such as /media/seed/priya-cushion-1.svg
    data_source: DataSource

    @classmethod
    def of(cls, product: Product) -> "ProductOut":
        return cls(
            id=product.id,
            seller_id=product.seller_id,
            title=product.title,
            description=product.description,
            category=product.category,
            variants=list(product.variants_json),
            price_usd=product.price_usd,
            capacity_per_week=product.capacity_per_week,
            ship_days=product.ship_days,
            ship_from_city=product.ship_from_city,
            photos=[photo_path(photo) for photo in product.photos_json],
            data_source=product.data_source,
        )


class TrustSummary(BaseModel):
    orders_delivered: int
    on_time_rate: float
    dispute_rate: float
    photo_originality: float
    score: Decimal  # spec 3.7: 0.4 on time + 0.3 (1 - disputes) + 0.3 photo originality
    data_source: DataSource
    issued_at: str
    # Of her orders delivered, those a buyer confirmed through OpenStall (prompt 36); the rest are her history.
    live_deliveries: int = 0

    @classmethod
    def of(cls, passport: Passport) -> "TrustSummary":
        metrics = passport.metrics_json
        return cls(
            orders_delivered=metrics["orders_delivered"],
            on_time_rate=metrics["on_time_rate"],
            dispute_rate=metrics["dispute_rate"],
            photo_originality=metrics["photo_originality"],
            score=trust_score(metrics["on_time_rate"], metrics["dispute_rate"], metrics["photo_originality"]),
            data_source=passport.data_source,
            issued_at=metrics["issued_at"],
            live_deliveries=int(metrics.get("live_deliveries", 0)),
        )


class SellerCard(BaseModel):
    """A stall as the home page lists it."""

    id: str
    name: str
    city: str | None
    country: str | None
    language: str | None
    data_source: DataSource
    headline: str  # the title of her first listing
    from_price_usd: Decimal
    cover_photo: str | None


class SellerDetail(BaseModel):
    """A stall page: the maker, what she sells, and her trust record."""

    id: str
    name: str
    city: str | None
    country: str | None
    language: str | None
    data_source: DataSource
    products: list[ProductOut]
    trust: TrustSummary | None


def _live(products: list[Product]) -> list[Product]:
    return sorted((p for p in products if p.status is ProductStatus.LIVE), key=lambda p: (p.created_at, p.id))


def live_products(session: Session, seller_id: str | None = None) -> list[Product]:
    query = select(Product).where(Product.status == ProductStatus.LIVE).options(selectinload(Product.seller))
    if seller_id is not None:
        query = query.where(Product.seller_id == seller_id)
    return list(session.scalars(query.order_by(Product.created_at, Product.id)))


def seller_cards(session: Session) -> list[SellerCard]:
    """Every seller with at least one live listing, by name."""
    sellers = session.scalars(select(Seller).options(selectinload(Seller.products)).order_by(Seller.name))
    cards = []
    for seller in sellers:
        products = _live(seller.products)
        if not products:
            continue
        first = products[0]
        cards.append(
            SellerCard(
                id=seller.id,
                name=seller.name,
                city=seller.city,
                country=seller.country,
                language=seller.language,
                data_source=seller.data_source,
                headline=first.title,
                from_price_usd=min(p.price_usd for p in products),
                cover_photo=photo_path(first.photos_json[0]) if first.photos_json else None,
            )
        )
    return cards


def seller_detail(session: Session, seller_id: str) -> SellerDetail | None:
    seller = session.get(Seller, seller_id, options=[selectinload(Seller.products)])
    if seller is None:
        return None
    passport = session.get(Passport, seller_id)
    return SellerDetail(
        id=seller.id,
        name=seller.name,
        city=seller.city,
        country=seller.country,
        language=seller.language,
        data_source=seller.data_source,
        products=[ProductOut.of(product) for product in _live(seller.products)],
        trust=TrustSummary.of(passport) if passport else None,
    )


class AgentTrust(BaseModel):
    """A maker's trust record in brief, as the agent storefront returns it (spec 3.7)."""

    score: float = Field(
        description="From 0 to 1: 0.4 x on-time rate + 0.3 x (1 - dispute rate) + 0.3 x photo originality."
    )
    orders_delivered: int
    on_time_rate: float
    dispute_rate: float
    data_source: str = Field(description='Where the numbers come from: "seeded_demo" marks made-up demo numbers.')
    summary: str = Field(description="The record in one line.")

    @classmethod
    def of(cls, passport: Passport) -> "AgentTrust":
        trust = TrustSummary.of(passport)
        through = (
            f", {trust.live_deliveries} of them through OpenStall"
            if trust.live_deliveries and trust.data_source is DataSource.SEEDED_DEMO
            else ""
        )
        demo = f" (seeded demo numbers{through})" if trust.data_source is DataSource.SEEDED_DEMO else ""
        return cls(
            score=float(trust.score),
            orders_delivered=trust.orders_delivered,
            on_time_rate=trust.on_time_rate,
            dispute_rate=trust.dispute_rate,
            data_source=trust.data_source.value,
            summary=(
                f"Trust score {trust.score} from {trust.orders_delivered} delivered orders: "
                f"{trust.on_time_rate:.0%} on time, {trust.dispute_rate:.0%} disputed{demo}"
            ),
        )


class ProductListing(BaseModel):
    """A listing as the agent storefront (MCP) returns it."""

    product_id: str
    seller_id: str
    seller_name: str
    title: str
    description: str
    category: str
    variants: list[str] = Field(description="The colours or styles she offers.")
    price_usd: float = Field(description="List price per unit, in USD.")
    capacity_per_week: int = Field(description="Units she makes in a week.")
    ship_days: int = Field(description="Days in transit to the buyer. For now these are days to a US city.")
    ship_from_city: str
    data_source: str = Field(description='"seeded_demo" marks a made-up demo listing; "live" a real one.')
    trust: AgentTrust | None = Field(description="The maker's trust record in brief; null until she has one.")

    @classmethod
    def of(cls, product: Product, passport: Passport | None, **extra: Any) -> Self:
        """The listing, with her trust record when she has a passport. `extra` fills a subclass's own fields."""
        return cls(
            product_id=product.id,
            seller_id=product.seller_id,
            seller_name=product.seller.name,
            title=product.title,
            description=product.description,
            category=product.category,
            variants=list(product.variants_json),
            price_usd=float(product.price_usd),
            capacity_per_week=product.capacity_per_week,
            ship_days=product.ship_days,
            ship_from_city=product.ship_from_city,
            data_source=product.data_source.value,
            trust=AgentTrust.of(passport) if passport else None,
            **extra,
        )


class CatalogEntry(ProductListing):
    """A live listing in full, as agents read it: get_product, GET /catalog/{product_id}.json and each entry of
    GET /catalog.json. docs/catalog.schema.json describes it."""

    photos: list[str] = Field(description="Her photos as full URLs, the main one first.")
    stall_url: str = Field(description="Her stall page on OpenStall's website, for people.")
    trust_card_url: str | None = Field(
        description="Her trust card as JSON, the same as the MCP tool get_trust_card gives; null until she has one."
    )

    @classmethod
    def at(cls, product: Product, passport: Passport | None, settings: Settings) -> "CatalogEntry":
        """The entry with its links made from the API's and the website's public addresses."""
        seller = quote(product.seller_id, safe="")
        return cls.of(
            product,
            passport,
            photos=[public_url(settings, photo_path(photo)) for photo in product.photos_json],
            stall_url=f"{settings.WEB_BASE_URL}/stall/{seller}",
            trust_card_url=public_url(settings, f"/passport/{seller}") if passport else None,
        )


def _passports(session: Session, seller_ids: set[str]) -> dict[str, Passport]:
    if not seller_ids:
        return {}
    rows = session.scalars(select(Passport).where(Passport.seller_id.in_(seller_ids)))
    return {passport.seller_id: passport for passport in rows}


def catalog_entries(session: Session, settings: Settings) -> list[CatalogEntry]:
    """Every live listing as agents read it, oldest first. This only reads."""
    products = live_products(session)
    passports = _passports(session, {product.seller_id for product in products})
    return [CatalogEntry.at(product, passports.get(product.seller_id), settings) for product in products]


def catalog_entry(session: Session, product_id: str, settings: Settings) -> CatalogEntry:
    """One live listing as agents read it. A draft or paused listing is not found, like one that never existed: it is
    not for sale. Raises NotFound with a message for the agent. This only reads."""
    product = (
        session.get(Product, product_id, options=[selectinload(Product.seller)])
        if ID_PATTERN.fullmatch(product_id)
        else None
    )
    if product is None or product.status is not ProductStatus.LIVE:
        raise NotFound(
            f"There is no live listing called {product_id!r}. search_products and /catalog.json give each live "
            "listing's product_id."
        )
    return CatalogEntry.at(product, session.get(Passport, product.seller_id), settings)
