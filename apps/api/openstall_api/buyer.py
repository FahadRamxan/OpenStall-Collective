"""The scripted buyer agent (spec section 2, steps 4 to 9): the story's request, played through the MCP storefront.

It does what a buyer's AI agent does, in order: search_products, request_quote (40 hand-embroidered cushion covers,
at most $30 each, due 30 days from today, to Chicago), create_collective_order, then checkout for the approval link a
person opens. It talks only MCP, so the same steps run over HTTP from scripts/run_demo_request.py and in process from
POST /api/demo/run. Like every buyer agent it cannot move money: a person approves on the link it gets.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from mcp import Client

from openstall_api.seed import DEMO_REQUEST

STORY_QUANTITY = 40
STORY_MAX_UNIT_PRICE = 30
STORY_CITY = "Chicago"
STORY_DAYS = 30

# The stepper on /demo: the names of the buyer agent's steps, in order.
STEPS = ("Search", "Quote", "Offers", "Allocation", "Approval")


class BuyerError(RuntimeError):
    """A step failed: the tool refused, or answered without what the next step needs. The message says which."""


@dataclass
class BuyerRun:
    """What the buyer agent did: each step's line, the order it drafted, and the link it got for its human."""

    lines: list[str] = field(default_factory=list)
    request_id: str | None = None
    order_id: str | None = None
    total_usd: str | None = None
    shares: list[tuple[str, int]] = field(default_factory=list)  # (maker, units) in the plan's order
    approval_url: str | None = None


Pause = Callable[[str], Awaitable[None]]


async def _no_pause(step: str) -> None:
    return None


async def run_story(
    client: Client, today: date, *, say: Callable[[str], None] = print, pause: Pause = _no_pause
) -> BuyerRun:
    """Play the story's request on a connected MCP client, saying each step as it goes."""
    run = BuyerRun()

    def step(line: str) -> None:
        run.lines.append(line)
        say(line)

    deadline = today + timedelta(days=STORY_DAYS)
    await pause("Search")
    found = await _call(client, "search_products", {"query": DEMO_REQUEST, "quantity": STORY_QUANTITY})
    results = found.get("result") or []
    step(f"1. Searched for “{DEMO_REQUEST}”: {len(results)} matching listings from {len({r['seller_id'] for r in results})} makers.")

    await pause("Quote")
    quote = await _call(
        client,
        "request_quote",
        {
            "items": [DEMO_REQUEST],
            "quantity": STORY_QUANTITY,
            "max_unit_price": STORY_MAX_UNIT_PRICE,
            "deadline": deadline.isoformat(),
            "ship_to": STORY_CITY,
        },
    )
    run.request_id = _text(quote, "request_id")
    offers = quote.get("offers") or []
    step(
        f"2. Asked for a quote: {STORY_QUANTITY} at most ${STORY_MAX_UNIT_PRICE}.00 each by "
        f"{deadline:%B} {deadline.day}, to {STORY_CITY}. {len(offers)} makers made valid offers in "
        f"{quote.get('rounds')} round(s):"
    )
    for offer in offers:
        step(f"   {offer['seller_name']}: {offer['quantity']} at ${offer['unit_price']} each")
    plan = quote.get("plan") or {}
    run.shares = [(line["seller_name"], int(line["quantity"])) for line in plan.get("lines") or []]
    shares = ", ".join(f"{name} {units}" for name, units in run.shares)
    step(f"3. The plan, cheapest first: {shares}, ${plan.get('total_cost')} in all.")
    if plan.get("explanation"):
        step(f"   In words: {plan['explanation']}")

    await pause("Approval")
    draft = await _call(client, "create_collective_order", {"request_id": run.request_id})
    run.order_id = _text(draft, "order_id")
    run.total_usd = _text(draft, "total_usd")
    step(f"4. Drafted order {run.order_id}: {draft.get('units')} units, ${run.total_usd}, worked out by OpenStall.")
    link = await _call(client, "checkout", {"order_id": run.order_id})
    run.approval_url = _text(link, "approval_url")
    step(f"5. Approval link for the human: {run.approval_url}")
    step("   Nothing is paid yet: the person approves there, and each maker is paid when she ships.")
    return run


async def _call(client: Client, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await client.call_tool(tool, arguments)
    if result.is_error:
        words = " ".join(getattr(block, "text", "") for block in result.content).strip()
        raise BuyerError(f"{tool} refused: {words}")
    content = result.structured_content
    if not isinstance(content, dict):
        raise BuyerError(f"{tool} answered without structured content")
    return content


def _text(content: dict[str, Any], key: str) -> str:
    value = content.get(key)
    if not isinstance(value, str) or not value:
        raise BuyerError(f"the answer had no {key}")
    return value
