"""The tables from spec section 4: every model round-trips, enums refuse unknown values, money stays exact."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, StatementError

from openstall_api.db import REPO_ROOT, database_url
from openstall_api.models import (
    ChatMessage,
    ChatSession,
    ChatState,
    Channel,
    DataSource,
    Direction,
    Event,
    Offer,
    Order,
    OrderPart,
    OrderStatus,
    PartStatus,
    Passport,
    ProcessedWebhook,
    Product,
    ProductStatus,
    QuoteRequest,
    Search,
    Seller,
    new_id,
)


def amina(**overrides) -> Seller:
    values = dict(
        id="s_amina",
        name="Amina",
        language="ur",
        city="Lahore",
        whatsapp_number="whatsapp:+923001234567",
        policy_json={"floor_price_usd": "15.00", "max_discount_pct": 15, "min_lead_days": 5},
    )
    return Seller(**(values | overrides))


def cushion(seller_id: str = "s_amina", **overrides) -> Product:
    values = dict(
        seller_id=seller_id,
        title="Hand-embroidered cushion cover",
        category="home textiles",
        variants_json=["red", "teal", "mustard"],
        price_usd=Decimal("18.00"),
        capacity_per_week=4,
        ship_days=9,
        ship_from_city="Lahore",
        photos_json=["media/amina-1.jpg"],
        source_text="Embroidered cushion covers, 3 colours, 18 dollars, I can make 4 a week.",
    )
    return Product(**(values | overrides))


def test_a_seller_and_her_product_round_trip(db):
    db.add_all([amina(), cushion()])
    db.commit()
    db.expunge_all()

    seller = db.get(Seller, "s_amina")
    product = db.scalars(select(Product)).one()

    assert seller.language == "ur"
    assert seller.policy_json["max_discount_pct"] == 15
    assert seller.data_source is DataSource.LIVE
    assert seller.created_at is not None
    assert product.seller.name == "Amina"
    assert product.variants_json == ["red", "teal", "mustard"]
    assert product.price_usd == Decimal("18.00")
    assert product.status is ProductStatus.DRAFT
    assert product.source_text.startswith("Embroidered")


def test_a_chat_session_keeps_its_messages_in_order(db):
    db.add(amina())
    session = ChatSession(seller_id="s_amina", channel=Channel.WHATSAPP)
    session.messages = [
        ChatMessage(direction=Direction.INBOUND, channel=Channel.WHATSAPP, text="Salaam", language="ur"),
        ChatMessage(
            direction=Direction.INBOUND,
            channel=Channel.WHATSAPP,
            media_json=[{"id": "m_1", "content_type": "audio/ogg"}],
            transcript="کڑھائی والے کشن کور",
        ),
    ]
    db.add(session)
    db.commit()
    db.expunge_all()

    loaded = db.scalars(select(ChatSession)).one()

    assert loaded.state is ChatState.COLLECTING
    assert [message.text for message in loaded.messages] == ["Salaam", None]
    assert loaded.messages[1].transcript == "کڑھائی والے کشن کور"
    assert loaded.messages[1].media_json[0]["content_type"] == "audio/ogg"


def test_a_quote_its_offers_and_an_order_with_parts_round_trip(db):
    db.add_all([amina(), cushion(id="p_amina")])
    quote = QuoteRequest(
        items_json=[{"query": "hand-embroidered cushion covers"}],
        quantity=40,
        max_unit_price=Decimal("30.00"),
        deadline=date(2026, 12, 10),
        ship_to="Chicago",
    )
    db.add(quote)
    db.flush()
    db.add(
        Offer(
            request_id=quote.id,
            seller_id="s_amina",
            unit_price=Decimal("17.50"),
            quantity=12,
            delivery_date=date(2026, 12, 10),
            message="Twelve covers, ready to ship by the 1st.",
            is_valid=True,
        )
    )
    order = Order(request_id=quote.id, total_usd=Decimal("210.00"))
    order.parts = [
        OrderPart(
            seller_id="s_amina",
            product_id="p_amina",
            reference_id="op_001",
            quantity=12,
            unit_price_usd=Decimal("17.50"),
            amount_usd=Decimal("210.00"),
            delivery_date=date(2026, 12, 10),
        )
    ]
    db.add(order)
    db.commit()
    db.expunge_all()

    offer = db.scalars(select(Offer)).one()
    loaded = db.scalars(select(Order)).one()

    assert offer.round == 1 and offer.is_valid and offer.rejection_reason is None
    assert loaded.status is OrderStatus.DRAFT
    assert loaded.total_usd == Decimal("210.00")
    assert loaded.parent_order_id is None
    assert len(loaded.parts) == 1
    part = loaded.parts[0]
    assert part.status is PartStatus.PENDING
    assert part.authorization_id is None and part.capture_id is None
    assert part.amount_usd == Decimal("210.00")


def test_a_top_up_order_points_at_the_order_it_repairs(db):
    original = Order(total_usd=Decimal("815.00"), status=OrderStatus.AUTHORIZED)
    db.add(original)
    db.flush()
    db.add(Order(total_usd=Decimal("293.00"), parent_order_id=original.id))
    db.commit()

    top_up = db.scalars(select(Order).where(Order.parent_order_id.is_not(None))).one()

    assert top_up.parent_order_id == original.id


def test_passports_searches_events_and_webhooks_round_trip(db):
    db.add(amina())
    db.add(
        Passport(
            seller_id="s_amina",
            metrics_json={"orders_delivered": 42, "on_time_rate": 0.95},
            signature="ed25519:" + "A" * 86,
            data_source=DataSource.SEEDED_DEMO,
        )
    )
    db.add(Search(query="ceramic mugs", filters_json={"max_price": 20}, result_count=0))
    db.add(Event(type="order.authorized", entity_id="ord_1", payload_json={"total": "815.00"}))
    db.add(ProcessedWebhook(provider="paypal", event_id="WH-1"))
    db.commit()
    db.expunge_all()

    assert db.get(Passport, "s_amina").data_source is DataSource.SEEDED_DEMO
    assert db.scalars(select(Search)).one().result_count == 0
    assert db.scalars(select(Event)).one().payload_json == {"total": "815.00"}
    assert db.scalars(select(ProcessedWebhook)).one().event_id == "WH-1"


def test_events_get_increasing_whole_number_ids(db):
    db.add_all([Event(type=f"test.{n}") for n in range(3)])
    db.commit()

    ids = db.scalars(select(Event.id).order_by(Event.id)).all()

    assert ids == sorted(ids) and len(set(ids)) == 3
    assert all(isinstance(event_id, int) for event_id in ids)


def test_ids_are_readable_and_prefixed(db):
    db.add(Seller(name="Priya"))
    db.add(Order(total_usd=Decimal("1.00")))
    db.commit()

    seller_id = db.scalars(select(Seller.id)).one()
    order_id = db.scalars(select(Order.id)).one()

    assert seller_id.startswith("s_") and len(seller_id) == len("s_") + 12
    assert order_id.startswith("ord_")
    assert new_id("op") != new_id("op")


# ---------- enums ----------


@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        (Order, "status", "approved"),  # the old status, before pay-on-proof
        (Order, "status", "paid"),
        (OrderPart, "status", "refunded"),
        (ChatSession, "state", "closed"),
    ],
)
def test_an_unknown_enum_value_is_refused(db, model, field, value):
    db.add(amina())
    if model is Order:
        row = Order(total_usd=Decimal("1.00"))
    elif model is OrderPart:
        order = Order(total_usd=Decimal("1.00"))
        db.add(order)
        db.flush()
        row = OrderPart(
            order_id=order.id,
            seller_id="s_amina",
            reference_id="op_001",
            quantity=1,
            unit_price_usd=Decimal("1.00"),
            amount_usd=Decimal("1.00"),
        )
    else:
        row = ChatSession(channel=Channel.WEB)
    setattr(row, field, value)
    db.add(row)

    with pytest.raises((StatementError, LookupError)):
        db.flush()


def test_the_database_itself_refuses_an_unknown_enum_value(db):
    # Even a raw insert that skips the Python models is stopped by the CHECK constraint.
    with pytest.raises(IntegrityError):
        db.execute(
            text("INSERT INTO orders (id, status, total_usd, created_at) VALUES ('ord_x', 'paid', 100, '2026-11-01')")
        )


def test_every_order_and_part_status_from_the_spec_is_known():
    assert [status.value for status in OrderStatus] == [
        "draft",
        "awaiting_approval",
        "authorized",
        "partly_shipped",
        "shipped",
        "completed",
        "cancelled",
    ]
    assert [status.value for status in PartStatus] == ["pending", "authorized", "captured", "delivered", "released"]


# ---------- money ----------


@pytest.mark.parametrize(
    ("stored", "read_back"),
    [
        (Decimal("28.99"), Decimal("28.99")),
        (Decimal("12"), Decimal("12.00")),
        ("216.00", Decimal("216.00")),
        (29.5, Decimal("29.50")),
        (Decimal("99999999.99"), Decimal("99999999.99")),
    ],
)
def test_money_keeps_exactly_two_decimal_places(db, stored, read_back):
    db.add(Order(id="ord_m", total_usd=stored))
    db.commit()
    db.expunge_all()

    total = db.get(Order, "ord_m").total_usd

    assert total == read_back
    assert total.as_tuple().exponent == -2


@pytest.mark.parametrize("bad", [Decimal("28.995"), Decimal("-1.00"), Decimal("NaN")])
def test_money_refuses_sub_cent_negative_and_non_finite_amounts(db, bad):
    db.add(Order(total_usd=bad))

    with pytest.raises(StatementError):
        db.flush()


def test_money_compares_correctly_inside_the_database(db):
    # Cheaper than 9.50: on SQLite these are whole cents, so 10.00 must not sort before 9.00 as text would.
    db.add(amina())
    db.add_all(
        [cushion(id=f"p_{n}", price_usd=Decimal(price)) for n, price in enumerate(["9.00", "10.00", "9.50", "100.00"])]
    )
    db.commit()

    cheap = db.scalars(select(Product.price_usd).where(Product.price_usd <= Decimal("9.50")).order_by(Product.price_usd))

    assert list(cheap) == [Decimal("9.00"), Decimal("9.50")]


# ---------- integrity ----------


def test_foreign_keys_are_enforced(db):
    db.add(cushion(seller_id="s_nobody"))

    with pytest.raises(IntegrityError):
        db.flush()


def test_a_part_reference_is_unique_within_its_order(db):
    db.add(amina())
    order = Order(total_usd=Decimal("2.00"))
    order.parts = [
        OrderPart(
            seller_id="s_amina",
            reference_id="op_001",
            quantity=1,
            unit_price_usd=Decimal("1.00"),
            amount_usd=Decimal("1.00"),
        )
        for _ in range(2)
    ]
    db.add(order)

    with pytest.raises(IntegrityError):
        db.flush()


# ---------- DATABASE_URL ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://u:p@db.example:5432/openstall", "postgresql+psycopg://u:***@db.example:5432/openstall"),
        ("postgresql://u:p@db.example/openstall", "postgresql+psycopg://u:***@db.example/openstall"),
        ("postgresql+psycopg://u:p@db.example/openstall", "postgresql+psycopg://u:***@db.example/openstall"),
        ("sqlite://", "sqlite://"),
    ],
)
def test_database_urls_are_normalised(raw, expected):
    assert database_url(raw).render_as_string(hide_password=True) == expected


def test_the_hosts_postgres_driver_is_the_one_sqlalchemy_uses():
    pytest.importorskip("psycopg")  # installed with pip install -e ".[postgres]", as render.yaml does
    from sqlalchemy import create_engine

    engine = create_engine(database_url("postgres://u:p@db.example:5432/openstall"))

    assert (engine.dialect.name, engine.dialect.driver) == ("postgresql", "psycopg")


def test_a_relative_sqlite_path_is_taken_from_the_repo_root_and_its_folder_is_made(tmp_path, monkeypatch):
    import openstall_api.db as db_module

    monkeypatch.setattr(db_module, "REPO_ROOT", tmp_path)

    url = database_url("sqlite:///./data/openstall.db")

    assert url.database == str(tmp_path / "data" / "openstall.db")
    assert (tmp_path / "data").is_dir()
    assert REPO_ROOT.name  # the real constant still points at the repo
