"""What the stalls sell, read from the database: listings for the web app and for the agent storefront."""

from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from openstall_api.models import DataSource, Passport, Product, ProductStatus, Seller
from openstall_trust import trust_score


def photo_path(stored: str) -> str:
    """Where the API serves a stored photo. Seed photos live in assets/seed and are served under /media/seed/."""
    if stored.startswith(("http://", "https://")):
        return stored
    return "/media/" + stored.lstrip("/")


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


class ProductListing(BaseModel):
    """A listing as the agent storefront (MCP) returns it."""

    product_id: str
    seller_id: str
    seller_name: str
    title: str
    category: str
    variants: list[str]
    price_usd: float
    capacity_per_week: int
    ship_days: int
    ship_from_city: str
    data_source: str

    @classmethod
    def of(cls, product: Product) -> "ProductListing":
        return cls(
            product_id=product.id,
            seller_id=product.seller_id,
            seller_name=product.seller.name,
            title=product.title,
            category=product.category,
            variants=list(product.variants_json),
            price_usd=float(product.price_usd),
            capacity_per_week=product.capacity_per_week,
            ship_days=product.ship_days,
            ship_from_city=product.ship_from_city,
            data_source=product.data_source.value,
        )
