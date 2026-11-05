"""The storefront's read-only tools: get_product and get_trust_card give agents exactly what the API's feeds give
(GET /catalog/{product_id}.json and GET /passport/{seller_id}), agree with the stall pages' API, change nothing, and
say clearly when an id is unknown."""

import asyncio
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from sqlalchemy import func, select

from openstall_api.main import app
from openstall_api.models import Event, Passport, Product, ProductStatus, Search
from openstall_api.seed import MAKERS, seed
from openstall_api.storefront import storefront

# No `with` block: that would run the app's lifespan, and the MCP session manager can only start once per process.
client = TestClient(app)

SELLER_OF = {maker.product_id: maker.id for maker in MAKERS}
NOOR_CARD = {
    "seller_id": "s_noor",
    "issued_at": "2026-11-01T00:00:00Z",
    "orders_delivered": 25,
    "on_time_rate": 0.96,
    "dispute_rate": 0.0,
    "photo_originality": 0.94,
    "score": 0.97,  # 0.4 x 0.96 + 0.3 x 1.00 + 0.3 x 0.94 = 0.966
    "data_source": "seeded_demo",
    "live_deliveries": 0,  # none of her orders went through OpenStall yet
    "live_on_time": 0,
}


@pytest.fixture(autouse=True)
def seeded(db):
    """The seeded demo world, Amina included, in this test's own database."""
    seed(db, with_amina=True)
    db.commit()
    return db


async def _call(target, tool: str, arguments: dict):
    async with Client(target) as mcp:
        return await mcp.call_tool(tool, arguments)


def call(target, tool: str, **arguments) -> dict:
    """Call a tool on an in-process server or a URL; return what it gave."""
    result = asyncio.run(_call(target, tool, arguments))
    assert not result.is_error, result.content
    return result.structured_content


def refusal(target, tool: str, **arguments) -> str:
    """Call a tool expecting it to refuse; return what it said."""
    result = asyncio.run(_call(target, tool, arguments))
    assert result.is_error
    return result.content[0].text


# ---------- the same data as the REST API ----------


def test_get_product_gives_exactly_what_the_catalog_serves():
    catalog = {entry["product_id"]: entry for entry in client.get("/catalog.json").json()["products"]}

    assert set(catalog) == set(SELLER_OF)
    for product_id in SELLER_OF:
        from_tool = call(storefront, "get_product", product_id=product_id)
        assert from_tool == client.get(f"/catalog/{product_id}.json").json() == catalog[product_id]


def test_get_product_agrees_with_the_stall_pages_api(settings):
    for product_id, seller_id in SELLER_OF.items():
        from_tool = call(storefront, "get_product", product_id=product_id)
        stall = client.get(f"/api/sellers/{seller_id}").json()
        [listing] = stall["products"]

        assert from_tool["product_id"] == listing["id"] == product_id
        assert (from_tool["seller_id"], from_tool["seller_name"]) == (seller_id, stall["name"])
        for field in ("title", "description", "category", "variants", "capacity_per_week", "ship_days"):
            assert from_tool[field] == listing[field], field
        assert from_tool["ship_from_city"] == listing["ship_from_city"]
        assert Decimal(str(from_tool["price_usd"])) == Decimal(listing["price_usd"])  # a number for agents
        assert from_tool["photos"] == [settings.PUBLIC_BASE_URL + path for path in listing["photos"]]
        assert from_tool["data_source"] == listing["data_source"] == "seeded_demo"
        trust = stall["trust"]
        assert Decimal(str(from_tool["trust"]["score"])) == Decimal(trust["score"])
        assert from_tool["trust"]["orders_delivered"] == trust["orders_delivered"]
        assert from_tool["trust"]["on_time_rate"] == trust["on_time_rate"]


def test_get_trust_card_gives_exactly_what_the_passport_endpoint_serves():
    for seller_id in SELLER_OF.values():
        assert call(storefront, "get_trust_card", seller_id=seller_id) == client.get(f"/passport/{seller_id}").json()


def test_the_trust_card_is_her_signed_passport_with_its_score(seeded):
    card = call(storefront, "get_trust_card", seller_id="s_noor")

    assert {key: value for key, value in card.items() if key != "signature"} == NOOR_CARD
    # It is the signed passport itself: OpenStall's key signed exactly these fields (prompt 35).
    assert card["signature"].startswith("ed25519:")
    assert client.post("/passport/verify", json=card).json()["valid"] is True
    # Her stored passport's own numbers, and the same record her stall page shows.
    stored = seeded.get(Passport, "s_noor").metrics_json
    for field in ("seller_id", "issued_at", "orders_delivered", "on_time_rate", "dispute_rate", "data_source"):
        assert card[field] == stored[field], field
    trust = client.get("/api/sellers/s_noor").json()["trust"]
    assert Decimal(str(card["score"])) == Decimal(trust["score"])
    assert card["photo_originality"] == trust["photo_originality"]
    # Signing for agents comes later, and nothing checks a PayPal account, so the card claims neither.
    assert seeded.get(Passport, "s_noor").signature.startswith("ed25519:")
    assert "paypal_account_verified" not in card


def test_get_product_gives_the_full_listing_with_full_photo_urls_and_links(use_settings):
    use_settings(PUBLIC_BASE_URL="https://api.openstall.example/", WEB_BASE_URL="https://openstall.example")

    noor = call(storefront, "get_product", product_id="p_noor_cushion")

    assert noor == {
        "product_id": "p_noor_cushion",
        "seller_id": "s_noor",
        "seller_name": "Noor",
        "title": "Chain-stitch embroidered cushion cover",
        "description": "Cotton cover, 16 by 16 inches, with paisleys in fine chain stitch.",
        "category": "home textiles",
        "variants": ["rose", "forest"],
        "price_usd": 31.0,
        "capacity_per_week": 3,
        "ship_days": 5,
        "ship_from_city": "Manchester",
        "data_source": "seeded_demo",
        "trust": {
            "score": 0.97,
            "orders_delivered": 25,
            "on_time_rate": 0.96,
            "dispute_rate": 0.0,
            "data_source": "seeded_demo",
            "summary": "Trust score 0.97 from 25 delivered orders: 96% on time, 0% disputed (seeded demo numbers)",
        },
        "photos": [
            "https://api.openstall.example/media/seed/noor-cushion-1.svg",
            "https://api.openstall.example/media/seed/noor-cushion-2.svg",
        ],
        "stall_url": "https://openstall.example/stall/s_noor",
        "trust_card_url": "https://api.openstall.example/passport/s_noor",
    }


# ---------- unknown ids ----------


@pytest.mark.parametrize(
    ("tool", "arguments", "message", "path"),
    [
        (
            "get_product",
            {"product_id": "p_nobody"},
            "There is no live listing called 'p_nobody'. search_products and /catalog.json give each live listing's "
            "product_id.",
            "/catalog/p_nobody.json",
        ),
        (
            "get_trust_card",
            {"seller_id": "s_nobody"},
            "There is no trust card for 's_nobody'. Each listing's seller_id names its maker; a maker who is new to "
            "OpenStall has no trust card yet.",
            "/passport/s_nobody",
        ),
        # Not an id at all: never looked up (Postgres would refuse the NUL), and said the same way.
        (
            "get_product",
            {"product_id": "p_noor\x00"},
            "There is no live listing called 'p_noor\\x00'.",
            "/catalog/p_noor%00.json",
        ),
        ("get_trust_card", {"seller_id": "s noor"}, "There is no trust card for 's noor'.", "/passport/s noor"),
    ],
)
def test_an_unknown_id_is_a_clear_tool_error_and_the_same_404_on_the_api(tool, arguments, message, path):
    said = refusal(storefront, tool, **arguments)

    assert said.startswith(f"Error executing tool {tool}: ")
    assert message in said
    response = client.get(path)
    assert response.status_code == 404
    assert message in response.json()["detail"]


@pytest.mark.parametrize(
    ("tool", "arguments", "problem"),
    [
        ("get_product", {"product_id": ""}, "at least 1 character"),
        ("get_product", {"product_id": "p" * 65}, "at most 64 characters"),
        ("get_trust_card", {"seller_id": ""}, "at least 1 character"),
        ("get_trust_card", {}, "Field required"),
    ],
)
def test_an_id_that_breaks_the_schema_is_refused_with_the_reason(tool, arguments, problem):
    assert problem in refusal(storefront, tool, **arguments)


@pytest.mark.parametrize("status", [ProductStatus.PAUSED, ProductStatus.DRAFT])
def test_a_listing_that_is_not_live_is_not_found(seeded, status):
    seeded.get(Product, "p_grace_cushion").status = status
    seeded.commit()

    assert "There is no live listing called 'p_grace_cushion'." in refusal(
        storefront, "get_product", product_id="p_grace_cushion"
    )
    assert client.get("/catalog/p_grace_cushion.json").status_code == 404
    # Her trust card is about her, not one listing, so it is still there.
    assert call(storefront, "get_trust_card", seller_id="s_grace")["seller_id"] == "s_grace"


def test_a_maker_without_a_passport_has_no_trust_card_and_her_listing_says_so(seeded):
    seeded.delete(seeded.get(Passport, "s_noor"))
    seeded.commit()

    assert "There is no trust card for 's_noor'." in refusal(storefront, "get_trust_card", seller_id="s_noor")
    noor = call(storefront, "get_product", product_id="p_noor_cushion")
    assert (noor["trust"], noor["trust_card_url"]) == (None, None)


# ---------- read-only ----------


def test_reading_a_listing_or_a_trust_card_changes_nothing(seeded):
    call(storefront, "get_product", product_id="p_noor_cushion")
    call(storefront, "get_trust_card", seller_id="s_noor")
    refusal(storefront, "get_product", product_id="p_nobody")

    # Unlike search_products, nothing is logged: no search row and no event.
    for model in (Search, Event):
        assert seeded.scalar(select(func.count()).select_from(model)) == 0


def test_over_http_the_tools_are_read_only_say_they_never_spend_money_and_refuse_unknown_ids(server_url):
    async def go():
        async with Client(server_url) as mcp:
            tools = {tool.name: tool for tool in (await mcp.list_tools()).tools}
            unknown = await mcp.call_tool("get_product", {"product_id": "p_nobody"})
            return tools, unknown

    tools, unknown = asyncio.run(go())

    for name in ("get_product", "get_trust_card"):
        annotations = tools[name].annotations
        assert (annotations.read_only_hint, annotations.destructive_hint) == (True, False), name
        assert (annotations.idempotent_hint, annotations.open_world_hint) == (True, False), name
        assert "It only reads: it never spends money and changes no order." in tools[name].description
        assert tools[name].output_schema["type"] == "object"  # agents get structured results
    signature = tools["get_trust_card"].output_schema["properties"]["signature"]["description"]
    assert "/passport/public-key" in signature and "/verify" in signature
    assert unknown.is_error
    assert "There is no live listing called 'p_nobody'." in unknown.content[0].text
    # Over the wire, the result is still exactly the API's own entry.
    assert call(server_url, "get_product", product_id="p_amina_cushion") == client.get(
        "/catalog/p_amina_cushion.json"
    ).json()
