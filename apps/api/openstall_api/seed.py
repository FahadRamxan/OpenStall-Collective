"""The demo world from spec section 2: five makers, one listing each, and their trust records.

All of it is made up for the demo and marked seeded_demo wherever it appears. Amina normally joins live over
WhatsApp, so she is seeded only when asked (with_amina): for tests, and for recording parts of the video out of
order. Seeding is idempotent: the same input gives the same rows, signatures included.

Payout rails (spec 3.5a): Grace has a fictional Venmo handle, so she is paid on the Venmo rail. In sandbox mode only,
Priya, Lucía and Noor get the sandbox PayPal accounts named in PAYPAL_SANDBOX_PAYEE_PRIYA, _LUCIA and _NOOR; without
one, a maker's rail is "not connected yet" there. Fake mode simulates every payout and needs no account.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from openstall_api.models import (
    Base,
    DataSource,
    Order,
    Passport,
    Product,
    ProductStatus,
    QuoteRequest,
    Seller,
    new_id,
)
from openstall_api.orders import DraftPart, create_draft_order
from openstall_api.passports import issue_passport
from openstall_api.settings import Settings, get_settings

MAX_DISCOUNT_PCT = 15
MIN_LEAD_DAYS = 5
FREE_SHIPPING_MIN_QTY = 3
CATEGORY = "home textiles"
# A fixed issue time, so seeding twice signs exactly the same passports.
SEEDED_AT = datetime(2026, 11, 1, tzinfo=UTC)


@dataclass(frozen=True)
class SeedMaker:
    id: str
    name: str
    city: str
    country: str
    language: str
    list_price: Decimal
    floor: Decimal
    per_week: int
    ship_days: int  # to Chicago, where the story's buyer is
    product_id: str
    title: str
    description: str
    variants: tuple[str, ...]
    photos: tuple[str, ...]
    trust: dict[str, Any] = field(default_factory=dict)
    source_text: str | None = None
    venmo_handle: str | None = None  # fictional, like every seeded maker
    sandbox_payee_setting: str | None = None  # the setting naming her sandbox PayPal account, in sandbox mode

    def policy(self) -> dict[str, Any]:
        """The seller policy JSON from spec 3.3. Money as strings, so it stays exact."""
        return {
            "seller_id": self.id,
            "floor_price_usd": str(self.floor),
            "max_discount_pct": MAX_DISCOUNT_PCT,
            "capacity_per_week": self.per_week,
            "min_lead_days": MIN_LEAD_DAYS,
            "free_shipping_min_qty": FREE_SHIPPING_MIN_QTY,
        }


def _photos(seller: str) -> tuple[str, ...]:
    return (f"seed/{seller}-cushion-1.svg", f"seed/{seller}-cushion-2.svg")


# The seed table in spec section 2. Keep its three rules if you change a number: no three of the first four makers
# can fill a 40-unit order in 30 days, every floor is below the buyer's $30 cap, and Noor's offer stays above Grace's.
AMINA = SeedMaker(
    id="s_amina",
    name="Amina",
    city="Lahore",
    country="PK",
    language="ur",
    list_price=Decimal("18.00"),
    floor=Decimal("15.00"),
    per_week=4,
    ship_days=9,
    product_id="p_amina_cushion",
    title="Hand-embroidered cushion cover",
    description="Cotton cover, 16 by 16 inches, with a floral motif embroidered by hand in three colours.",
    variants=("red", "teal", "mustard"),
    photos=_photos("amina"),
    trust={"orders_delivered": 42, "on_time_rate": 0.95, "dispute_rate": 0.02, "photo_originality": 0.91},
    source_text="Embroidered cushion covers, 3 colours, 18 dollars, I can make 4 a week.",
)
PRIYA = SeedMaker(
    id="s_priya",
    name="Priya",
    city="Jaipur",
    country="IN",
    language="hi",
    list_price=Decimal("16.00"),
    floor=Decimal("13.00"),
    per_week=4,
    ship_days=10,
    product_id="p_priya_cushion",
    title="Mirror-work embroidered cushion cover",
    description="Cotton cover, 16 by 16 inches, with small mirrors stitched in by hand in the Rajasthani style.",
    variants=("indigo", "saffron"),
    photos=_photos("priya"),
    trust={"orders_delivered": 67, "on_time_rate": 0.97, "dispute_rate": 0.01, "photo_originality": 0.93},
    sandbox_payee_setting="PAYPAL_SANDBOX_PAYEE_PRIYA",
)
LUCIA = SeedMaker(
    id="s_lucia",
    name="Lucía",
    city="Oaxaca",
    country="MX",
    language="es",
    list_price=Decimal("22.00"),
    floor=Decimal("19.00"),
    per_week=3,
    ship_days=6,
    product_id="p_lucia_cushion",
    title="Oaxacan embroidered cushion cover",
    description="Cotton manta cover, 16 by 16 inches, with a band of flowers in Oaxacan satin stitch.",
    variants=("white", "black"),
    photos=_photos("lucia"),
    trust={"orders_delivered": 38, "on_time_rate": 0.92, "dispute_rate": 0.03, "photo_originality": 0.95},
    sandbox_payee_setting="PAYPAL_SANDBOX_PAYEE_LUCIA",
)
GRACE = SeedMaker(
    id="s_grace",
    name="Grace",
    city="Detroit",
    country="US",
    language="en",
    list_price=Decimal("32.00"),
    floor=Decimal("27.00"),
    per_week=3,
    ship_days=3,
    product_id="p_grace_cushion",
    title="Hand-embroidered linen cushion cover",
    description="Washed linen cover, 16 by 16 inches, with a leaf sprig worked in crewel wool.",
    variants=("natural", "sage"),
    photos=_photos("grace"),
    trust={"orders_delivered": 120, "on_time_rate": 0.98, "dispute_rate": 0.01, "photo_originality": 0.89},
    venmo_handle="grace-detroit-demo",
)
NOOR = SeedMaker(
    id="s_noor",
    name="Noor",
    city="Manchester",
    country="GB",
    language="ur",
    list_price=Decimal("31.00"),
    floor=Decimal("28.50"),
    per_week=3,
    ship_days=5,
    product_id="p_noor_cushion",
    title="Chain-stitch embroidered cushion cover",
    description="Cotton cover, 16 by 16 inches, with paisleys in fine chain stitch.",
    variants=("rose", "forest"),
    photos=_photos("noor"),
    trust={"orders_delivered": 25, "on_time_rate": 0.96, "dispute_rate": 0.0, "photo_originality": 0.94},
    sandbox_payee_setting="PAYPAL_SANDBOX_PAYEE_NOOR",
)

MAKERS = (AMINA, PRIYA, LUCIA, GRACE, NOOR)


@dataclass(frozen=True)
class SeedReport:
    sellers: int
    products: int
    passports: int


def reset_all(session: Session) -> None:
    """Empty every table, children first."""
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(delete(table))


def seed(
    session: Session, *, with_amina: bool = False, reset: bool = False, settings: Settings | None = None
) -> SeedReport:
    """Add the seeded makers, or bring them back to their seeded state. Other rows are kept unless reset is set.
    `settings` (the app's, by default) decide whether the sandbox PayPal payees are linked."""
    settings = settings or get_settings()
    if reset:
        reset_all(session)
    for maker in MAKERS:
        if maker is AMINA and not with_amina:
            continue
        _seed_maker(session, maker, settings)
    session.flush()
    return SeedReport(
        sellers=session.scalar(select(func.count()).select_from(Seller)) or 0,
        products=session.scalar(select(func.count()).select_from(Product)) or 0,
        passports=session.scalar(select(func.count()).select_from(Passport)) or 0,
    )


def sandbox_payee(maker: SeedMaker, settings: Settings) -> str | None:
    """Her sandbox PayPal account's email, in sandbox mode only. Fake mode never links one."""
    if settings.OPENSTALL_MODE != "sandbox" or maker.sandbox_payee_setting is None:
        return None
    value: str | None = getattr(settings, maker.sandbox_payee_setting)
    return value or None


def _seed_maker(session: Session, maker: SeedMaker, settings: Settings) -> None:
    session.merge(
        Seller(
            id=maker.id,
            name=maker.name,
            language=maker.language,
            city=maker.city,
            country=maker.country,
            paypal_email=sandbox_payee(maker, settings),
            venmo_handle=maker.venmo_handle,
            policy_json=maker.policy(),
            data_source=DataSource.SEEDED_DEMO,
            created_at=SEEDED_AT,
        )
    )
    session.merge(
        Product(
            id=maker.product_id,
            seller_id=maker.id,
            title=maker.title,
            description=maker.description,
            category=CATEGORY,
            variants_json=list(maker.variants),
            price_usd=maker.list_price,
            capacity_per_week=maker.per_week,
            ship_days=maker.ship_days,
            ship_from_city=maker.city,
            photos_json=list(maker.photos),
            source_text=maker.source_text,
            status=ProductStatus.LIVE,
            data_source=DataSource.SEEDED_DEMO,
            created_at=SEEDED_AT,
        )
    )
    signed = issue_passport(
        maker.id,
        {**maker.trust, "paypal_account_verified": True},
        DataSource.SEEDED_DEMO.value,
        SEEDED_AT,
    )
    session.merge(
        Passport(
            seller_id=maker.id,
            metrics_json={key: value for key, value in signed.items() if key != "signature"},
            signature=signed["signature"],
            data_source=DataSource.SEEDED_DEMO,
            issued_at=SEEDED_AT,
        )
    )


# The story's order (spec section 2, step 7) as a draft, so the approval page can be shown before the allocator runs.
# Grace's $29 is her negotiated price: her $32 list price is over the buyer's $30 cap.
DEMO_ORDER_ID = "ord_demo"
DEMO_REQUEST_ID = "q_demo"
DEMO_REQUEST = "40 hand-embroidered cushion covers for corporate gifts"
DEMO_SPLIT = ((AMINA, 12, "18.00"), (PRIYA, 11, "16.00"), (LUCIA, 10, "22.00"), (GRACE, 7, "29.00"))


def seed_demo_order(session: Session, today: date) -> Order:
    """A fresh draft of the story's order, due 30 days from `today`. An earlier demo order is replaced."""
    for model, row_id in ((Order, DEMO_ORDER_ID), (QuoteRequest, DEMO_REQUEST_ID)):
        existing = session.get(model, row_id)
        if existing is not None:
            session.delete(existing)
    session.flush()
    return story_order(session, today, order_id=DEMO_ORDER_ID, request_id=DEMO_REQUEST_ID)


def story_order(session: Session, today: date, *, order_id: str | None = None, request_id: str | None = None) -> Order:
    """A draft of the story's order with its own request, due 30 days from `today`. Without ids it gets new ones, so
    UI tests can each pay for an order of their own."""
    request_id = request_id or new_id("q")
    deadline = today + timedelta(days=30)
    session.add(
        QuoteRequest(
            id=request_id,
            items_json=[{"query": DEMO_REQUEST}],
            quantity=40,
            max_unit_price=Decimal("30.00"),
            deadline=deadline,
            ship_to="Chicago",
        )
    )
    session.flush()
    parts = [DraftPart(maker.id, maker.product_id, quantity, price, deadline) for maker, quantity, price in DEMO_SPLIT]
    return create_draft_order(session, parts, order_id=order_id, request_id=request_id)
