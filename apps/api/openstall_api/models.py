"""The tables from spec section 4, plus chat_messages, processed_webhooks and paypal_claims (see docs/decisions.md).

IDs are readable prefixed strings such as s_amina or ord_3f9a1c7e2b40. Events are the exception: their id is an
increasing integer, so the live feed can ask for "everything after event 41".
"""

import secrets
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from openstall_api.db import Money

# Fixed constraint names, so migrations can find them again on SQLite and Postgres alike.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def new_id(prefix: str) -> str:
    """A readable unique id such as ord_3f9a1c7e2b40."""
    return f"{prefix}_{secrets.token_hex(6)}"


def utcnow() -> datetime:
    return datetime.now(UTC)


def enum_type(enum: type[StrEnum], name: str) -> SAEnum:
    """Stored as text with a CHECK constraint: the same on SQLite and Postgres, and unknown values are refused."""
    return SAEnum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=32,
        values_callable=lambda members: [member.value for member in members],
    )


class DataSource(StrEnum):
    SEEDED_DEMO = "seeded_demo"  # made up for the demo, and labelled as such wherever it appears
    LIVE = "live"


class ProductStatus(StrEnum):
    DRAFT = "draft"
    LIVE = "live"
    PAUSED = "paused"


class ChatState(StrEnum):
    COLLECTING = "collecting"
    ASKING = "asking"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    LIVE = "live"


class Channel(StrEnum):
    WHATSAPP = "whatsapp"
    WEB = "web"


class Direction(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class OrderStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    AUTHORIZED = "authorized"  # the whole amount is reserved at PayPal; nothing is captured yet
    PARTLY_SHIPPED = "partly_shipped"
    SHIPPED = "shipped"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PartStatus(StrEnum):
    PENDING = "pending"
    AUTHORIZED = "authorized"  # her share is reserved
    CAPTURED = "captured"  # paid on proof: her tracking was confirmed
    DELIVERED = "delivered"
    RELEASED = "released"  # she dropped out and her authorization was voided


class ClaimState(StrEnum):
    PENDING = "pending"  # a request holds it and is calling PayPal (or its process stopped while doing so)
    DONE = "done"  # PayPal answered and the result is recorded
    UNKNOWN = "unknown"  # the holder is finished without PayPal's answer saved: it may have landed


class PayoutRailChoice(StrEnum):
    """How a maker is paid once her share is captured (spec 3.5a), the values of openstall_paypal's PayoutRail."""

    PAYPAL = "paypal"
    VENMO = "venmo"
    HYPERWALLET = "hyperwallet"  # prompt 52
    UNAVAILABLE = "unavailable"


class Base(DeclarativeBase):
    """Every foreign key also has a relationship(): SQLAlchemy orders inserts by relationships, so a seller and her
    passport can be saved together."""

    metadata = MetaData(naming_convention=NAMING)


class Seller(Base):
    __tablename__ = "sellers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("s"))
    name: Mapped[str] = mapped_column(String(120))
    language: Mapped[str | None] = mapped_column(String(16))  # ISO 639-1, set from her first voice note
    city: Mapped[str | None] = mapped_column(String(80))
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2, such as PK; decides how she is paid
    whatsapp_number: Mapped[str | None] = mapped_column(String(32), unique=True)
    # A seller who chats on /seller-chat instead: the random "demo phone" id her browser keeps.
    web_chat_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    paypal_merchant_id: Mapped[str | None] = mapped_column(String(64))
    paypal_email: Mapped[str | None] = mapped_column(String(254))
    # Her Venmo handle, in the US: she is then paid on the Venmo rail (spec 3.5a).
    venmo_handle: Mapped[str | None] = mapped_column(String(64))
    # An operator's choice of rail for her. None: her country decides (openstall_paypal.rails.rail_for).
    payout_rail: Mapped[PayoutRailChoice | None] = mapped_column(enum_type(PayoutRailChoice, "payout_rail"))
    policy_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    data_source: Mapped[DataSource] = mapped_column(enum_type(DataSource, "data_source"), default=DataSource.LIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    products: Mapped[list["Product"]] = relationship(back_populates="seller", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("capacity_per_week >= 0", name="capacity_not_negative"),
        CheckConstraint("ship_days >= 0", name="ship_days_not_negative"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("p"))
    seller_id: Mapped[str] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(80))
    variants_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    price_usd: Mapped[Decimal] = mapped_column(Money())
    capacity_per_week: Mapped[int] = mapped_column(Integer)
    ship_days: Mapped[int] = mapped_column(Integer)
    ship_from_city: Mapped[str] = mapped_column(String(80))
    photos_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_text: Mapped[str | None] = mapped_column(Text)  # the seller's own words, so a wrong reading can be traced
    status: Mapped[ProductStatus] = mapped_column(
        enum_type(ProductStatus, "product_status"), default=ProductStatus.DRAFT
    )
    data_source: Mapped[DataSource] = mapped_column(enum_type(DataSource, "data_source"), default=DataSource.LIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    seller: Mapped[Seller] = relationship(back_populates="products")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("cs"))
    seller_id: Mapped[str | None] = mapped_column(ForeignKey("sellers.id", ondelete="SET NULL"), index=True)
    channel: Mapped[Channel] = mapped_column(enum_type(Channel, "channel"))
    state: Mapped[ChatState] = mapped_column(enum_type(ChatState, "chat_state"), default=ChatState.COLLECTING)
    draft_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    seller: Mapped[Seller | None] = relationship()
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("cm"))
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    direction: Mapped[Direction] = mapped_column(enum_type(Direction, "direction"))
    channel: Mapped[Channel] = mapped_column(enum_type(Channel, "channel"))
    text: Mapped[str | None] = mapped_column(Text)
    media_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    transcript: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class Search(Base):
    __tablename__ = "searches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("sr"))
    query: Mapped[str] = mapped_column(Text)
    filters_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class QuoteRequest(Base):
    __tablename__ = "quote_requests"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("q"))
    items_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    quantity: Mapped[int] = mapped_column(Integer)
    max_unit_price: Mapped[Decimal] = mapped_column(Money())
    deadline: Mapped[date] = mapped_column(Date)
    ship_to: Mapped[str] = mapped_column(String(120))
    plan_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # the allocation plan (prompt 25)
    # How far the negotiation has got (prompt 24): makers asked, rounds run, and when the last round ended.
    asked: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rounds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("off"))
    request_id: Mapped[str] = mapped_column(ForeignKey("quote_requests.id", ondelete="CASCADE"), index=True)
    seller_id: Mapped[str] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"), index=True)
    # The listing it offers, which an order share needs (prompt 27). None only if the listing was deleted since.
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), index=True)
    unit_price: Mapped[Decimal] = mapped_column(Money())
    quantity: Mapped[int] = mapped_column(Integer)
    delivery_date: Mapped[date] = mapped_column(Date)
    message: Mapped[str | None] = mapped_column(Text)
    is_valid: Mapped[bool] = mapped_column(Boolean)
    rejection_reason: Mapped[str | None] = mapped_column(String(32))  # openstall_allocator.RejectionReason values
    round: Mapped[int] = mapped_column(Integer, default=1)
    # 1 to 3 within the round: a proposal the code check refuses is retried with the reason (spec 3.3).
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    request: Mapped[QuoteRequest] = relationship()
    seller: Mapped[Seller] = relationship()


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ord"))
    request_id: Mapped[str | None] = mapped_column(ForeignKey("quote_requests.id", ondelete="SET NULL"), index=True)
    # A top-up order from a self-healing re-plan points at the order it repairs (spec 3.10).
    parent_order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), index=True)
    status: Mapped[OrderStatus] = mapped_column(enum_type(OrderStatus, "order_status"), default=OrderStatus.DRAFT)
    total_usd: Mapped[Decimal] = mapped_column(Money())
    paypal_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    request: Mapped[QuoteRequest | None] = relationship()
    parts: Mapped[list["OrderPart"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderPart.reference_id"
    )


class OrderPart(Base):
    """One seller's share of an order: what she makes, what she is paid, and where it is in pay-on-proof."""

    __tablename__ = "order_parts"
    __table_args__ = (
        UniqueConstraint("order_id", "reference_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("op"))
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    seller_id: Mapped[str] = mapped_column(ForeignKey("sellers.id"), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    reference_id: Mapped[str] = mapped_column(String(64))  # op_001, op_002 ... within the order
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_usd: Mapped[Decimal] = mapped_column(Money())
    amount_usd: Mapped[Decimal] = mapped_column(Money())
    status: Mapped[PartStatus] = mapped_column(enum_type(PartStatus, "part_status"), default=PartStatus.PENDING)
    authorization_id: Mapped[str | None] = mapped_column(String(64))
    capture_id: Mapped[str | None] = mapped_column(String(64))
    tracking_number: Mapped[str | None] = mapped_column(String(64))
    carrier: Mapped[str | None] = mapped_column(String(64))
    delivery_date: Mapped[date | None] = mapped_column(Date)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="parts")
    seller: Mapped[Seller] = relationship()
    product: Mapped[Product | None] = relationship()


class Passport(Base):
    __tablename__ = "passports"

    seller_id: Mapped[str] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"), primary_key=True)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    signature: Mapped[str] = mapped_column(String(200))
    data_source: Mapped[DataSource] = mapped_column(enum_type(DataSource, "data_source"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    seller: Mapped[Seller] = relationship()


class Event(Base):
    """Everything that happens, in order. It feeds the /demo page and doubles as the audit log."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcessedWebhook(Base):
    """A verified webhook event, handled once: a repeat is ignored (spec section 7).

    It is kept, so what PayPal confirmed can be shown whatever order its events arrived in: an authorization that was
    confirmed before our side saved it still counts once it is saved.
    """

    __tablename__ = "processed_webhooks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("wh"))
    provider: Mapped[str] = mapped_column(String(32))
    event_id: Mapped[str] = mapped_column(String(128), unique=True)
    event_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64), index=True)  # PayPal's authorization, capture ...
    reference: Mapped[str | None] = mapped_column(String(64), index=True)  # our id PayPal echoes, such as a share's
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PayPalClaim(Base):
    """A PayPal write a caller can ask for twice (a checkout, a reserve, a share's capture or void), claimed here
    before the SDK call, so a concurrent second request is refused by this table's primary key (claims.py).

    `request_id` is the PayPal-Request-Id the call carries, kept beside the claim: an unknown claim is taken over at
    once only by a request carrying the same one. `holder` is the token of whoever holds it now, so a takeover of a
    stale or finished claim can only succeed once.
    """

    __tablename__ = "paypal_claims"

    key: Mapped[str] = mapped_column(String(96), primary_key=True)  # for example "capture:op_3f9a1c7e2b40"
    request_id: Mapped[str] = mapped_column(String(128))
    state: Mapped[ClaimState] = mapped_column(enum_type(ClaimState, "claim_state"))
    holder: Mapped[str] = mapped_column(String(32))
    result: Mapped[str | None] = mapped_column(String(64))  # PayPal's id for what the call made, once done
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
