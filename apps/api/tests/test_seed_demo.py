"""The demo world from spec section 2: seeded exactly as the seed table says, labelled, signed, and repeatable."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from openstall_allocator import Listing, SellerPolicy, capacity_available, lowest_allowed_price
from openstall_api.models import Base, DataSource, Order, Passport, Product, ProductStatus, Seller
from openstall_api.passports import FAKE_MODE_KEY_B64, MissingSigningKey, signing_key
from openstall_api.seed import AMINA, GRACE, LUCIA, MAKERS, NOOR, PRIYA, seed
from openstall_trust import load_private_key, verify_passport

# Spec section 2, word for word: seller, city, language, list price, floor, makes per week, ship days, 30-day supply.
SEED_TABLE = {
    "s_amina": ("Lahore", "ur", "18.00", "15.00", 4, 9, 12),
    "s_priya": ("Jaipur", "hi", "16.00", "13.00", 4, 10, 11),
    "s_lucia": ("Oaxaca", "es", "22.00", "19.00", 3, 6, 10),
    "s_grace": ("Detroit", "en", "32.00", "27.00", 3, 3, 11),
    "s_noor": ("Manchester", "ur", "31.00", "28.50", 3, 5, 10),
}


def snapshot(db) -> dict[str, list]:
    """Every row of every table, as plain values, to compare two databases."""
    tables = {}
    for table in Base.metadata.sorted_tables:
        tables[table.name] = sorted(tuple(map(str, row)) for row in db.execute(select(table)))
    return tables


def counts(db) -> tuple[int, int, int]:
    return tuple(db.scalar(select(func.count()).select_from(model)) for model in (Seller, Product, Passport))


def test_without_amina_the_four_seeded_makers_are_there(db):
    seed(db)
    db.commit()

    assert {seller.id for seller in db.scalars(select(Seller))} == {"s_priya", "s_lucia", "s_grace", "s_noor"}
    assert counts(db) == (4, 4, 4)


def test_with_amina_all_five_makers_are_there(db):
    report = seed(db, with_amina=True)
    db.commit()

    assert (report.sellers, report.products, report.passports) == (5, 5, 5)
    assert {seller.id for seller in db.scalars(select(Seller))} == set(SEED_TABLE)


def test_seeding_twice_gives_exactly_the_same_database(db):
    seed(db, with_amina=True)
    db.commit()
    first = snapshot(db)

    seed(db, with_amina=True)
    db.commit()

    assert snapshot(db) == first


def test_every_seeded_number_matches_the_seed_table(db):
    seed(db, with_amina=True)
    db.commit()

    for seller_id, (city, language, price, floor, per_week, ship_days, _) in SEED_TABLE.items():
        seller = db.get(Seller, seller_id)
        product = db.scalars(select(Product).where(Product.seller_id == seller_id)).one()
        assert (seller.city, seller.language) == (city, language)
        assert product.price_usd == Decimal(price)
        assert product.capacity_per_week == per_week
        assert product.ship_days == ship_days
        assert product.status is ProductStatus.LIVE
        assert seller.policy_json == {
            "seller_id": seller_id,
            "floor_price_usd": floor,
            "max_discount_pct": 15,
            "capacity_per_week": per_week,
            "min_lead_days": 5,
            "free_shipping_min_qty": 3,
        }


def test_the_seed_gives_the_capacities_and_lowest_prices_the_story_needs(db):
    # Through the real offer rules: 12, 11, 10, 11 for the four makers, 10 for Noor, in a 30-day order.
    seed(db, with_amina=True)
    db.commit()
    today = date(2026, 11, 10)
    deadline = today + timedelta(days=30)

    supply, lowest = {}, {}
    for maker in MAKERS:
        seller = db.get(Seller, maker.id)
        product = db.scalars(select(Product).where(Product.seller_id == maker.id)).one()
        policy = SellerPolicy(**seller.policy_json)
        listing = Listing(
            seller_id=maker.id,
            product_id=product.id,
            price_usd=product.price_usd,
            ship_days=product.ship_days,
        )
        supply[maker.id] = capacity_available(policy, listing, today, deadline)
        lowest[maker.id] = lowest_allowed_price(policy, listing)

    assert supply == {seller_id: row[6] for seller_id, row in SEED_TABLE.items()}
    first_four = [supply[m.id] for m in (AMINA, PRIYA, LUCIA, GRACE)]
    assert sum(first_four) == 44
    assert max(sum(first_four) - one for one in first_four) < 40  # no three of them can fill 40
    assert all(price <= Decimal("30.00") for price in lowest.values())  # every floor is below the buyer's cap
    assert lowest == {
        "s_amina": Decimal("15.30"),
        "s_priya": Decimal("13.60"),
        "s_lucia": Decimal("19.00"),
        "s_grace": Decimal("27.20"),
        "s_noor": Decimal("28.50"),
    }


def test_everything_seeded_is_labelled_as_demo_data(db):
    seed(db, with_amina=True)
    db.commit()

    for model in (Seller, Product, Passport):
        assert {row.data_source for row in db.scalars(select(model))} == {DataSource.SEEDED_DEMO}
    assert {row.metrics_json["data_source"] for row in db.scalars(select(Passport))} == {"seeded_demo"}


def test_the_seeded_passports_are_signed_and_verify(db):
    seed(db, with_amina=True)
    db.commit()
    public = load_private_key(FAKE_MODE_KEY_B64).public_key()

    for passport in db.scalars(select(Passport)):
        signed = {**passport.metrics_json, "signature": passport.signature}
        assert passport.signature.startswith("ed25519:")
        assert verify_passport(signed, public)
        assert not verify_passport({**signed, "on_time_rate": 1.0}, public)  # one changed number breaks it


def test_reset_empties_everything_else_first(db):
    seed(db)
    db.add(Order(total_usd=Decimal("10.00")))
    db.add(Seller(id="s_extra", name="Somebody else"))
    db.commit()

    seed(db, reset=True)
    db.commit()

    assert db.scalar(select(func.count()).select_from(Order)) == 0
    assert db.get(Seller, "s_extra") is None
    assert counts(db) == (4, 4, 4)


def test_seeding_without_reset_keeps_other_rows(db):
    db.add(Seller(id="s_extra", name="Somebody else"))
    db.commit()

    seed(db)
    db.commit()

    assert db.get(Seller, "s_extra") is not None


def test_sandbox_mode_needs_a_real_signing_key(use_settings):
    use_settings(OPENSTALL_MODE="sandbox")

    with pytest.raises(MissingSigningKey, match="make_signing_key"):
        signing_key()


def test_a_configured_signing_key_is_used_instead_of_the_fake_one(use_settings):
    from openstall_trust import generate_keypair

    private_b64, public_b64 = generate_keypair()
    use_settings(PASSPORT_SIGNING_KEY=private_b64)

    from openstall_trust import public_key_b64

    assert public_key_b64(signing_key()) == public_b64


def test_the_seed_script_migrates_seeds_and_respects_if_empty(capsys):
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[3] / "scripts" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("seed_demo", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.main(["--reset", "--with-amina"]) == 0
    assert "5 sellers" in capsys.readouterr().out
    assert module.main(["--if-empty"]) == 0
    assert "nothing was seeded" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        module.main(["--reset", "--if-empty"])
