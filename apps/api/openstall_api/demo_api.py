"""The /demo page's own API: GET /api/demo/limits, what the offer rules allow each live maker (spec 3.3).

The numbers come from the allocator core through offer_rules.py, the same rules every offer is checked against, so
viewers see each maker's limits before the offers arrive. POST /api/demo/run plays the story with the scripted buyer
agent (buyer.py), POST /api/demo/run-agent plays it with a buyer's AI agent that chooses the tools itself
(prompt 30), and POST /api/demo/reset puts the demo world back as seeded: always in fake mode, and in sandbox mode
only with the DEMO_RUN_TOKEN header.
"""

import hmac
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from mcp import Client
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from openstall_agents.adapters import LLMError
from openstall_agents.buyer_agent import ToolCall, ToolResult, ToolSpec, run_buyer_agent, tool_text
from openstall_allocator import Clock, SystemClock
from openstall_api import quotes
from openstall_api.adapters import AdapterRegistry, AdapterUnavailable, get_registry
from openstall_api.buyer import STORY_CITY, STORY_DAYS, STORY_MAX_UNIT_PRICE, BuyerError, run_story
from openstall_api.db import get_session
from openstall_api.events import EventType, record_event
from openstall_api.models import DataSource
from openstall_api.offer_rules import MakerLimits, default_deadline, limits_by_deadline
from openstall_api.seed import DEMO_ORDER_ID, DEMO_REQUEST, reset_demo_world
from openstall_api.settings import Settings, get_settings
from openstall_api.storefront import storefront

router = APIRouter(prefix="/api/demo", tags=["demo"])

# Where "today" comes from: UTC, like the offer rules and search. Tests fix it with a FixedClock.
clock: Clock = SystemClock()


class MakerLimitsOut(BaseModel):
    """One live listing's maker, and what the offer rules let her agent offer by the deadline."""

    seller_id: str
    seller_name: str
    city: str | None
    product_id: str
    product_title: str
    list_price_usd: Decimal  # sent as a string such as "18.00", so it stays exact
    floor_price_usd: Decimal
    max_discount_pct: Decimal
    lowest_price_usd: Decimal = Field(
        description="The lowest unit price her agent may offer: her floor, or her list price less her maximum "
        "discount, whichever is higher."
    )
    capacity_per_week: int
    ship_days: int
    min_lead_days: int
    committed_units: int = Field(description="Units she has promised to reserved orders and not shipped yet.")
    capacity_by_deadline: int = Field(
        description="Units she can still make and ship by the deadline, after her committed units."
    )
    data_source: DataSource

    @classmethod
    def of(cls, limits: MakerLimits) -> "MakerLimitsOut":
        product, policy = limits.product, limits.policy
        return cls(
            seller_id=product.seller_id,
            seller_name=product.seller.name,
            city=product.seller.city,
            product_id=product.id,
            product_title=product.title,
            list_price_usd=product.price_usd,
            floor_price_usd=policy.floor_price_usd,
            max_discount_pct=policy.max_discount_pct,
            lowest_price_usd=limits.lowest_price,
            capacity_per_week=policy.capacity_per_week,
            ship_days=product.ship_days,
            min_lead_days=policy.min_lead_days,
            committed_units=limits.committed,
            capacity_by_deadline=limits.capacity,
            data_source=product.seller.data_source,
        )


class LimitsOut(BaseModel):
    """Every live maker's limits by one deadline."""

    today: date = Field(description="Today in UTC, the day capacity is counted from.")
    deadline: date
    makers: list[MakerLimitsOut] = Field(description="One row per live listing, oldest listing first.")
    unreadable: list[str] = Field(
        description="Live makers left out because their limits cannot be read, each said in words."
    )


@router.get("/limits")
def get_limits(
    session: Annotated[Session, Depends(get_session)],
    deadline: Annotated[
        date | None, Query(description="The date an order must arrive by, YYYY-MM-DD. 30 days from today if left out.")
    ] = None,
) -> LimitsOut:
    """What the offer rules allow each live maker by the deadline: the lowest price her agent may offer, and how many
    she can still make and ship by then. This only reads."""
    today = clock.today()
    deadline = deadline or default_deadline(today)
    if deadline <= today:
        raise HTTPException(
            status_code=422,
            detail=f"The deadline {deadline.isoformat()} must be after today, {today.isoformat()} (UTC).",
        )
    makers, unreadable = limits_by_deadline(session, today, deadline)
    return LimitsOut(
        today=today,
        deadline=deadline,
        makers=[MakerLimitsOut.of(limits) for limits in makers],
        unreadable=unreadable,
    )


# The header that unlocks the demo controls in sandbox mode, where DEMO_RUN_TOKEN is set.
TOKEN_HEADER = "X-Demo-Run-Token"


def demo_controls_allowed(
    settings: Annotated[Settings, Depends(get_settings)],
    token: Annotated[str | None, Header(alias=TOKEN_HEADER)] = None,
) -> None:
    """Fake mode: always. Sandbox mode: only with the DEMO_RUN_TOKEN header, so strangers cannot run up model calls
    or wipe the hosted demo. Without a DEMO_RUN_TOKEN set, sandbox mode keeps the controls off."""
    if settings.OPENSTALL_MODE == "fake":
        return
    expected = settings.DEMO_RUN_TOKEN.get_secret_value() if settings.DEMO_RUN_TOKEN else None
    if expected is None:
        raise HTTPException(status_code=403, detail="The demo controls are off: DEMO_RUN_TOKEN is not set.")
    if token is None or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail=f"The demo controls need the {TOKEN_HEADER} header.")


class DemoRun(BaseModel):
    """What the scripted buyer agent did."""

    steps: list[str] = Field(description="Each step, as scripts/run_demo_request.py prints it.")
    request_id: str
    order_id: str
    total_usd: Decimal
    shares: list[tuple[str, int]] = Field(description="(maker, units) in the plan's order, cheapest first.")
    approval_url: str


class DemoReset(BaseModel):
    sellers: int
    products: int
    passports: int
    order_id: str


@router.post("/run", dependencies=[Depends(demo_controls_allowed)])
async def run_demo(session: Annotated[Session, Depends(get_session)]) -> DemoRun:
    """The scripted buyer agent runs the story's request through the real MCP storefront, in process, as
    scripts/run_demo_request.py does over HTTP: search, quote, draft, approval link. /demo follows it live."""
    record_event(session, EventType.DEMO_RUN, "The scripted buyer agent started the story's request")
    session.commit()
    try:
        async with Client(storefront) as client:
            run = await run_story(client, quotes.clock.today(), say=lambda line: None)
    except BuyerError as error:
        raise HTTPException(status_code=409, detail=f"The buyer agent stopped: {error}") from None
    assert run.request_id and run.order_id and run.total_usd and run.approval_url
    return DemoRun(
        steps=run.lines,
        request_id=run.request_id,
        order_id=run.order_id,
        total_usd=Decimal(run.total_usd),
        shares=run.shares,
        approval_url=run.approval_url,
    )


class AgentStepOut(BaseModel):
    tool: str
    arguments: dict[str, Any]
    ok: bool
    summary: str


class DemoAgentRun(BaseModel):
    """What the buyer's AI agent did: each tool it chose, what it said, and what it got for its person."""

    agent: str = Field(description="Who the agent is: Claude and its model, or test mode's stand-in.")
    request: str = Field(description="The person's request, in words, as the agent got it.")
    steps: list[AgentStepOut]
    said: list[str] = Field(description="What the agent said, turn by turn; the last is its answer.")
    finished: bool
    request_id: str | None
    order_id: str | None
    total_usd: Decimal | None
    approval_url: str | None


def story_request_words(today: date) -> str:
    """The story's request as a person would give it to their AI agent, in words."""
    deadline = today + timedelta(days=STORY_DAYS)
    return (
        f"Please buy {DEMO_REQUEST}, at most ${STORY_MAX_UNIT_PRICE}.00 each, delivered to {STORY_CITY} by "
        f"{deadline.isoformat()}. Get me the approval link: I approve the payment myself."
    )


@router.post("/run-agent", dependencies=[Depends(demo_controls_allowed)])
async def run_agent(
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[AdapterRegistry, Depends(get_registry)],
) -> DemoAgentRun:
    """The story's request, played by a buyer's AI agent (prompt 30): the person's request in words, and the
    agent chooses the MCP storefront's tools itself, in process, until it has the approval link. Claude in sandbox
    mode (LLM_MODEL, needing ANTHROPIC_API_KEY); test mode's stand-in otherwise. /demo follows it live."""
    try:
        buyer = registry.buyer_agent
    except AdapterUnavailable as error:
        raise HTTPException(status_code=503, detail=f"The buyer's AI agent is not available: {error}") from None
    request = story_request_words(quotes.clock.today())
    record_event(
        session,
        EventType.AGENT_STARTED,
        f"A buyer's AI agent ({buyer.label}) got a person's request: “{request}”",
        payload={"agent": buyer.label, "request": request},
    )
    session.commit()
    try:
        async with Client(storefront) as client:
            listed = (await client.list_tools()).tools
            tools = [ToolSpec(tool.name, tool.description or "", dict(tool.input_schema)) for tool in listed]

            async def call(made: ToolCall) -> ToolResult:
                result = await client.call_tool(made.name, made.arguments)
                words = " ".join(getattr(block, "text", "") for block in result.content).strip()
                if result.is_error:
                    return ToolResult(made, None, words or "The tool refused.", is_error=True)
                content = result.structured_content if isinstance(result.structured_content, dict) else None
                return ToolResult(made, content, tool_text(content, words))

            run = await run_buyer_agent(buyer, request, tools, call)
    except LLMError as error:
        record_event(session, EventType.AGENT_FINISHED, f"The buyer's AI agent stopped: {error}")
        session.commit()
        raise HTTPException(status_code=502, detail=f"The buyer's AI agent stopped: {error}") from None
    record_event(
        session,
        EventType.AGENT_FINISHED,
        f"The buyer's AI agent drafted order {run.order_id} (${run.total_usd}) and got its person the approval link"
        if run.approval_url
        else "The buyer's AI agent stopped without an approval link",
        entity_id=run.order_id,
        payload={"agent": run.agent, "steps": [step.tool for step in run.steps], "said": run.said[-1:]},
    )
    session.commit()
    return DemoAgentRun(
        agent=run.agent,
        request=run.request,
        steps=[AgentStepOut(**step.__dict__) for step in run.steps],
        said=run.said,
        finished=run.finished,
        request_id=run.request_id,
        order_id=run.order_id,
        total_usd=Decimal(run.total_usd) if run.total_usd else None,
        approval_url=run.approval_url,
    )


@router.post("/reset", dependencies=[Depends(demo_controls_allowed)])
def reset_demo(session: Annotated[Session, Depends(get_session)]) -> DemoReset:
    """The demo world as seeded: the five makers, their listings and passports, and the story's draft order. Every
    other row goes, except the live feed's events, so pages that are open keep following it."""
    report = reset_demo_world(session, quotes.clock.today())
    record_event(
        session,
        EventType.DEMO_RESET,
        "The demo was reset: the seeded makers and the story's draft order are back, and nothing else",
    )
    session.commit()
    return DemoReset(
        sellers=report.sellers, products=report.products, passports=report.passports, order_id=DEMO_ORDER_ID
    )
