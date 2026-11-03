"""Feeds for agents without MCP: /catalog.json (checked against docs/catalog.schema.json, kept for 60 seconds),
/catalog/{product_id}.json, /llms.txt, and the photos they point at, served with caching headers."""

import asyncio
import copy
import json

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, ValidationError

from openstall_api import feeds
from openstall_api.adapters import reset_app_state
from openstall_api.db import REPO_ROOT
from openstall_api.main import app
from openstall_api.media import get_media_store
from openstall_api.models import DataSource, Passport, Product, ProductStatus
from openstall_api.seed import seed
from openstall_api.storefront import storefront
from openstall_trust import canonical_json

# No `with` block: that would run the app's lifespan, and the MCP session manager can only start once per process.
client = TestClient(app)

SCHEMA = json.loads((REPO_ROOT / "docs" / "catalog.schema.json").read_text(encoding="utf-8"))
SEEDED_PRODUCTS = ["p_amina_cushion", "p_grace_cushion", "p_lucia_cushion", "p_noor_cushion", "p_priya_cushion"]


@pytest.fixture(autouse=True)
def seeded(db):
    """The seeded demo world, Amina included, in this test's own database."""
    seed(db, with_amina=True)
    db.commit()
    return db


@pytest.fixture
def clock(monkeypatch):
    """The catalog's clock, moved forward by hand: clock.now += 59."""

    class Clock:
        now = 1_000.0

    monkeypatch.setattr(feeds, "monotonic", lambda: Clock.now)
    return Clock


def validate(catalog: dict) -> None:
    Draft202012Validator(SCHEMA, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(catalog)


def product_ids(response) -> list[str]:
    return [entry["product_id"] for entry in response.json()["products"]]


# ---------- /catalog.json against its schema ----------


def test_the_catalog_validates_against_the_json_schema_in_docs():
    Draft202012Validator.check_schema(SCHEMA)

    validate(client.get("/catalog.json").json())


def test_a_listing_whose_maker_has_no_passport_still_validates(seeded):
    seeded.delete(seeded.get(Passport, "s_noor"))
    seeded.commit()

    catalog = client.get("/catalog.json").json()

    validate(catalog)
    noor = next(entry for entry in catalog["products"] if entry["seller_id"] == "s_noor")
    assert (noor["trust"], noor["trust_card_url"]) == (None, None)


@pytest.mark.parametrize(
    ("change", "path"),
    [
        (lambda entry: entry.update(price_usd="31.00"), "price_usd"),  # a number, as search_products gives it
        (lambda entry: entry["photos"].append("/media/seed/noor-cushion-1.svg"), "photos"),  # full URLs only
        (lambda entry: entry.pop("data_source"), "data_source"),
        (lambda entry: entry.update(data_source="real_looking"), "data_source"),
        (lambda entry: entry["trust"].update(score=1.5), "score"),
        (lambda entry: entry.update(paypal_account_verified=True), "paypal_account_verified"),
    ],
)
def test_the_schema_refuses_a_catalog_that_breaks_it(change, path):
    catalog = copy.deepcopy(client.get("/catalog.json").json())
    change(catalog["products"][0])

    with pytest.raises(ValidationError) as refused:
        validate(catalog)
    assert path in str(refused.value)


# ---------- what the catalog holds ----------


def test_the_catalog_lists_every_live_listing_with_what_an_agent_needs(use_settings):
    use_settings(PUBLIC_BASE_URL="https://api.openstall.example", WEB_BASE_URL="https://openstall.example")

    response = client.get("/catalog.json")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    catalog = response.json()
    assert catalog["name"] == "OpenStall Collective"
    assert (catalog["mcp_url"], catalog["llms_txt_url"]) == (
        "https://api.openstall.example/mcp",
        "https://api.openstall.example/llms.txt",
    )
    assert product_ids(response) == SEEDED_PRODUCTS  # oldest first; the seed's are all as old, so by id
    priya = next(entry for entry in catalog["products"] if entry["seller_id"] == "s_priya")
    assert (priya["seller_name"], priya["price_usd"], priya["capacity_per_week"], priya["ship_days"]) == (
        "Priya",
        16.0,
        4,
        10,
    )
    assert priya["photos"] == [
        "https://api.openstall.example/media/seed/priya-cushion-1.svg",
        "https://api.openstall.example/media/seed/priya-cushion-2.svg",
    ]
    assert priya["trust"]["score"] == 0.96  # 0.4 x 0.97 + 0.3 x 0.99 + 0.3 x 0.93 = 0.964
    assert {entry["data_source"] for entry in catalog["products"]} == {"seeded_demo"}
    assert {entry["trust"]["data_source"] for entry in catalog["products"]} == {"seeded_demo"}


@pytest.mark.parametrize("status", [ProductStatus.PAUSED, ProductStatus.DRAFT])
def test_listings_that_are_not_live_are_left_out(seeded, status):
    seeded.get(Product, "p_grace_cushion").status = status
    seeded.commit()

    assert "p_grace_cushion" not in product_ids(client.get("/catalog.json"))


def test_a_live_sellers_uploaded_photo_gets_a_full_url_that_serves_it(seeded, use_settings):
    use_settings(PUBLIC_BASE_URL="http://testserver")
    stored = get_media_store().save(b"\xff\xd8\xff\xe0 a made-up jpeg", "image/jpeg")
    product = seeded.get(Product, "p_amina_cushion")
    product.photos_json = [f"uploads/{stored.key}"]  # photos are stored relative to /media/, like the seed's
    product.data_source = DataSource.LIVE
    seeded.commit()

    [amina] = [entry for entry in client.get("/catalog.json").json()["products"] if entry["seller_id"] == "s_amina"]

    assert amina["photos"] == [f"http://testserver/media/uploads/{stored.key}"]
    assert amina["data_source"] == "live"
    photo = client.get(amina["photos"][0])
    assert photo.status_code == 200
    assert photo.headers["cache-control"] == "public, max-age=31536000, immutable"


# ---------- kept for 60 seconds ----------


def test_the_catalog_is_kept_for_60_seconds_and_says_how_long_is_left(seeded, clock):
    first = client.get("/catalog.json")
    assert first.headers["cache-control"] == "public, max-age=60"

    seeded.get(Product, "p_grace_cushion").status = ProductStatus.PAUSED
    seeded.commit()
    clock.now += 45
    kept = client.get("/catalog.json")
    assert kept.content == first.content  # the same copy, Grace still in it
    assert kept.headers["cache-control"] == "public, max-age=15"  # never more than 60 seconds old in all

    clock.now += 15
    fresh = client.get("/catalog.json")
    assert "p_grace_cushion" not in product_ids(fresh)
    assert fresh.headers["cache-control"] == "public, max-age=60"


def test_part_of_a_second_counts_as_a_whole_one_so_no_copy_is_kept_past_60_seconds(clock):
    first = client.get("/catalog.json")

    clock.now += 0.5
    assert client.get("/catalog.json").headers["cache-control"] == "public, max-age=59"
    clock.now += 59.4  # 59.9 seconds old: still served, but a cache must not keep it
    last = client.get("/catalog.json")
    assert last.content == first.content
    assert last.headers["cache-control"] == "public, max-age=0"


def test_clearing_the_cache_builds_the_catalog_again_at_once(seeded, clock):
    client.get("/catalog.json")
    seeded.get(Product, "p_grace_cushion").status = ProductStatus.PAUSED
    seeded.commit()

    feeds.clear_catalog_cache()
    assert "p_grace_cushion" not in product_ids(client.get("/catalog.json"))

    # reset_app_state() forgets it too: a copy built from one test's settings and database never reaches the next.
    seeded.get(Product, "p_grace_cushion").status = ProductStatus.LIVE
    seeded.commit()
    reset_app_state()
    assert "p_grace_cushion" in product_ids(client.get("/catalog.json"))


def test_one_entry_is_read_afresh_and_may_be_kept_for_a_minute(seeded, clock):
    client.get("/catalog.json")
    seeded.get(Product, "p_noor_cushion").title = "Chain-stitch cushion cover, new title"
    seeded.commit()

    entry = client.get("/catalog/p_noor_cushion.json")

    assert entry.status_code == 200
    assert entry.json()["title"] == "Chain-stitch cushion cover, new title"
    assert entry.headers["cache-control"] == "public, max-age=60"


def test_an_unknown_entry_is_a_404_that_says_why():
    response = client.get("/catalog/p_nobody.json")

    assert response.status_code == 404
    assert response.json()["detail"].startswith("There is no live listing called 'p_nobody'.")
    assert "cache-control" not in response.headers
    assert client.get("/catalog/p_noor_cushion").status_code == 404  # an entry's address ends in .json


# ---------- /llms.txt ----------


def test_llms_txt_names_every_tool():
    tools = asyncio.run(storefront.list_tools())

    text = client.get("/llms.txt").text

    assert {tool.name for tool in tools} >= {"search_products", "get_product", "get_trust_card"}
    for tool in tools:
        assert f"- {tool.name}(" in text, tool.name
    assert "- search_products(query, max_price, ship_to, deadline, quantity): " in text
    assert "- get_product(product_id): One live listing in full." in text
    assert "- get_trust_card(seller_id): A maker's trust passport." in text


def test_llms_txt_says_what_openstall_is_where_to_connect_and_how_payment_works(use_settings):
    use_settings(PUBLIC_BASE_URL="https://api.openstall.example")

    response = client.get("/llms.txt")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["cache-control"] == "public, max-age=3600"
    text = response.text
    assert text.startswith("# OpenStall Collective\n\n> Handmade goods from home makers who sell over WhatsApp")
    # Only what works today.
    assert "Agents can search the makers' live listings, and read each listing in full and each maker's trust" in text
    assert "- MCP server: https://api.openstall.example/mcp (Streamable HTTP, no sign-in)" in text
    assert "Its tools (none of them spends money):" in text
    assert "The buyer's human approves one PayPal authorization for the whole order." in text
    assert "Each maker's share is captured only when she proves she shipped" in text
    assert "- No MCP tool captures, refunds or moves money." in text
    assert "[Catalog](https://api.openstall.example/catalog.json)" in text
    assert "`https://api.openstall.example/catalog/{product_id}.json`" in text
    assert "`https://api.openstall.example/passport/{seller_id}`" in text
    assert 'data_source "seeded_demo"' in text
    # How passports are checked, and that for now they cannot be.
    assert "To check a trust card's signature, verify it with Ed25519 over the card's canonical JSON" in text
    assert "every trust card's \"signature\" reads \"pending\": treat its numbers as unverified." in text


def test_llms_txt_says_how_ordering_works_only_while_an_mcp_tool_takes_orders():
    """llms.txt claims only what works: how to order, as long as create_collective_order exists (prompt 27)."""
    tools = {tool.name for tool in asyncio.run(storefront.list_tools())}

    text = " ".join(client.get("/llms.txt").text.split())

    takes_orders = "create_collective_order" in tools
    assert ("create_collective_order turns that plan into a draft order" in text) is takes_orders, (
        "llms.txt says how ordering works while an MCP tool takes orders, and not otherwise: see feeds.ORDERING"
    )
    assert "Ordering through agents is still being built" not in text


def test_following_llms_txt_rebuilds_exactly_the_bytes_a_trust_card_signature_covers():
    """An agent that follows llms.txt's steps in Python gets what packages/trust's canonical_json signs. Without the
    rule for whole-number floats it would write Noor's dispute_rate as 0.0, where the signer writes 0."""
    text = client.get("/llms.txt").text
    assert (
        'every field but "signature", keys sorted at every level, no whitespace, UTF-8 text rather than \\u escapes, '
        "and whole-number floats up to 2**53 written as integers (0.0 as 0, 1.0 as 1)"
    ) in text

    def as_llms_txt_says(value):
        if isinstance(value, float) and value.is_integer() and abs(value) <= 2**53:
            return int(value)
        return value

    for seller_id in ("s_amina", "s_grace", "s_lucia", "s_noor", "s_priya"):
        card = client.get(f"/passport/{seller_id}").json()
        fields = {key: as_llms_txt_says(value) for key, value in card.items() if key != "signature"}
        rebuilt = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        assert rebuilt == canonical_json(card), seller_id
    noor = client.get("/passport/s_noor").json()
    assert noor["dispute_rate"] == 0.0
    assert b'"dispute_rate":0,' in canonical_json(noor)


def test_llms_txt_says_payments_are_simulated_in_fake_mode(use_settings):
    fake = client.get("/llms.txt").text
    use_settings(OPENSTALL_MODE="sandbox")
    sandbox = client.get("/llms.txt").text

    assert "This server runs in fake mode: PayPal, WhatsApp and the AI models are simulated" in fake
    assert "Payments here run in PayPal's sandbox: no real money moves." in sandbox
    assert "Confirmed by PayPal" not in fake


# ---------- photos with caching headers ----------


def test_seed_photos_are_served_with_caching_headers_and_revalidate(settings):
    noor = client.get("/catalog/p_noor_cushion.json").json()
    path = noor["photos"][0].removeprefix(settings.PUBLIC_BASE_URL)

    photo = client.get(path)

    assert photo.status_code == 200
    assert photo.headers["content-type"].startswith("image/svg+xml")
    assert photo.headers["cache-control"] == "public, max-age=3600"
    assert photo.headers["x-content-type-options"] == "nosniff"
    unchanged = client.get(path, headers={"If-None-Match": photo.headers["etag"]})
    assert unchanged.status_code == 304
    assert unchanged.headers["cache-control"] == "public, max-age=3600"
    assert client.get("/media/seed/not-a-photo.svg").status_code == 404
