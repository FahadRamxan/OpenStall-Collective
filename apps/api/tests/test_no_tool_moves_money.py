"""Spec section 7: "No MCP tool can capture a payment" (prompt 28), and more: none can reserve, capture, pay out or
release money. Every registered tool is called, with arguments that work, while the payment gateway is a spy that
fails the test the moment anything asks it to move money."""

import asyncio
from datetime import date, timedelta

import pytest
from mcp import Client

from openstall_allocator import FixedClock
from openstall_api import quotes
from openstall_api.adapters import get_registry
from openstall_api.seed import DEMO_ORDER_ID, DEMO_REQUEST, seed, seed_demo_order
from openstall_api.storefront import storefront

TODAY = date(2026, 11, 10)


class SpyGateway:
    """A payment gateway that lets nothing through: each method records its name, and moving money fails the test."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _never(self, name: str):
        self.calls.append(name)
        pytest.fail(f"an MCP tool reached PaymentGateway.{name}")

    def create_checkout(self, request):
        return self._never("create_checkout")

    def get_order(self, paypal_order_id):
        return self._never("get_order")

    def reserve(self, paypal_order_id):
        return self._never("reserve")

    def pay_share(self, share):
        return self._never("pay_share")

    def release_share(self, share):
        return self._never("release_share")

    def add_tracking(self, tracking):
        return self._never("add_tracking")


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(quotes, "clock", FixedClock(TODAY))


@pytest.fixture
def spy(db):
    seed(db, with_amina=True)
    seed_demo_order(db, TODAY)
    db.commit()
    registry = get_registry()
    gateway = SpyGateway()
    registry._made["payment_gateway"] = gateway
    return gateway


def call_every_tool(arguments: dict[str, dict]) -> dict[str, object]:
    async def go():
        async with Client(storefront) as client:
            listed = (await client.list_tools()).tools
            missing = {tool.name for tool in listed} - set(arguments)
            assert not missing, f"add arguments for the new tools {sorted(missing)} to this test"
            return {tool.name: await client.call_tool(tool.name, arguments[tool.name]) for tool in listed}

    return asyncio.run(go())


def test_no_mcp_tool_reaches_a_payment(spy):
    deadline = (TODAY + timedelta(days=30)).isoformat()
    quote = {"items": [DEMO_REQUEST], "quantity": 40, "max_unit_price": 30, "deadline": deadline, "ship_to": "Chicago"}

    results = call_every_tool(
        {
            "search_products": {"query": "cushion covers"},
            "get_product": {"product_id": "p_priya_cushion"},
            "get_trust_card": {"seller_id": "s_priya"},
            "request_quote": quote,
            "create_collective_order": {"request_id": "q_demo"},
            "checkout": {"order_id": DEMO_ORDER_ID},
            "get_order_status": {"order_id": DEMO_ORDER_ID},
        }
    )

    assert spy.calls == []
    # Each tool did its job: the guard means something only if the tools ran.
    assert not [name for name, result in results.items() if result.is_error]
