"""A real AI agent as the buyer (spec 3.2, prompt 30): a model reads a person's request in words and chooses the MCP
storefront's tools itself, turn by turn, until it has the link the person opens to approve the order.

The tools are the storefront's own, as any MCP client lists them; the caller runs each call through its MCP client and
hands the answer back. No tool can move money, so the agent cannot either: it ends with an approval link for a person.
The run keeps every step (the tool, its arguments, what it answered) and what the agent said, and picks out the quote,
the order and the link from the tools' own answers, never from the agent's words.

ClaudeBuyer (adapters/claude.py) is the real agent, in sandbox mode. FakeBuyer stands in for it in test mode: the same
loop and tools, but fixed choices worked out from the tools' answers (search, quote, draft, checkout), so offline demos
and tests behave like the real thing.
"""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

MAX_TURNS = 12  # an agent that has not finished by then is stopped, and the run says so

SYSTEM = (
    "You are a purchasing agent working for one person. You buy through OpenStall's MCP storefront, a collective of "
    "home makers who sell handmade goods. Use its tools to find what the person asks for, check the makers, ask for a "
    "quote within the person's limits, draft the collective order, and get the approval link for it. You cannot pay "
    "and should not try: the person approves the order themselves at the link, and each maker is paid only when she "
    "ships. When you have the approval link, stop and tell the person in two or three plain sentences what you found: "
    "the total, the makers and their units, and the link."
)


@dataclass(frozen=True)
class ToolSpec:
    """One storefront tool, as MCP lists it."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """A tool's answer to one call: its structured content when it gave one, and its words as text."""

    call: ToolCall
    content: dict[str, Any] | None
    text: str
    is_error: bool = False


@dataclass(frozen=True)
class AgentTurn:
    """What the agent said this turn, and the tools it calls now; none when it has finished."""

    said: str
    calls: tuple[ToolCall, ...] = ()


class BuyerConversation(Protocol):
    def begin(self, system: str, request: str, tools: Sequence[ToolSpec]) -> AgentTurn:
        """The agent's first turn on the person's request."""
        ...

    def answer(self, results: Sequence[ToolResult]) -> AgentTurn:
        """The agent's next turn, given the answers to the calls it made."""
        ...


class BuyerModel(Protocol):
    """A buyer's AI agent: a fresh conversation for each request."""

    label: str  # who the agent is, for people: "Claude (claude-sonnet-5-5)"

    def conversation(self) -> BuyerConversation: ...


@dataclass(frozen=True)
class AgentStep:
    """One tool call the agent made, and how it went, in a line for people."""

    tool: str
    arguments: dict[str, Any]
    ok: bool
    summary: str


@dataclass
class AgentRun:
    agent: str
    request: str
    steps: list[AgentStep] = field(default_factory=list)
    said: list[str] = field(default_factory=list)
    finished: bool = False  # the agent stopped on its own, with no tool call left
    request_id: str | None = None
    order_id: str | None = None
    total_usd: str | None = None
    approval_url: str | None = None


Call = Callable[[ToolCall], Awaitable[ToolResult]]


async def run_buyer_agent(
    model: BuyerModel,
    request: str,
    tools: Sequence[ToolSpec],
    call: Call,
    *,
    max_turns: int = MAX_TURNS,
    system: str = SYSTEM,
) -> AgentRun:
    """Let the agent work on `request` with `tools`, running each call it makes through `call`, until it stops or
    `max_turns` have passed. The model's own requests run in a thread: they take seconds. `system`: the agent's
    instructions; the PayPal ops agent (ops_agent.py) runs on this loop with its own."""
    run = AgentRun(agent=model.label, request=request)
    conversation = model.conversation()
    turn = await asyncio.to_thread(conversation.begin, system, request, tools)
    for _ in range(max_turns):
        if turn.said.strip():
            run.said.append(turn.said.strip())
        if not turn.calls:
            run.finished = True
            break
        results = [await call(made) for made in turn.calls]
        for result in results:
            run.steps.append(_step(result))
            _keep(run, result)
        turn = await asyncio.to_thread(conversation.answer, results)
    return run


def _step(result: ToolResult) -> AgentStep:
    name, content = result.call.name, result.content or {}
    if result.is_error:
        summary = f"Refused: {result.text[:200]}"
    elif name == "search_products":
        found = content.get("result") or []
        summary = f"{len(found)} listings found"
    elif name == "request_quote":
        summary = f"Quote {content.get('request_id')}: {len(content.get('offers') or [])} valid offers"
    elif name == "create_collective_order":
        summary = f"Order {content.get('order_id')} drafted: ${content.get('total_usd')}"
    elif name == "checkout":
        summary = "Approval link for the person"
    else:
        summary = "Answered"
    return AgentStep(tool=name, arguments=dict(result.call.arguments), ok=not result.is_error, summary=summary)


def _keep(run: AgentRun, result: ToolResult) -> None:
    """The quote, the order and the link, from the tools' own answers."""
    content = result.content or {}
    if result.is_error:
        return
    if result.call.name == "request_quote" and isinstance(content.get("request_id"), str):
        run.request_id = content["request_id"]
    elif result.call.name == "create_collective_order" and isinstance(content.get("order_id"), str):
        run.order_id = content["order_id"]
        run.total_usd = str(content.get("total_usd"))
    elif result.call.name == "checkout" and isinstance(content.get("approval_url"), str):
        run.approval_url = content["approval_url"]


# Test mode's stand-in


@dataclass(frozen=True)
class Wanted:
    """What the person asked for, read from the request the way the stand-in needs it."""

    items: str
    quantity: int
    max_unit_price: int
    deadline: str
    ship_to: str


REQUEST_SHAPE = re.compile(
    r"(?P<quantity>\d+) (?P<items>.+?), at most \$(?P<price>\d+)(?:\.00)? each, delivered to (?P<city>[^,]+?) by "
    r"(?P<deadline>\d{4}-\d{2}-\d{2})"
)


def wanted(request: str) -> Wanted | None:
    match = REQUEST_SHAPE.search(request)
    if match is None:
        return None
    return Wanted(
        items=match["items"],
        quantity=int(match["quantity"]),
        max_unit_price=int(match["price"]),
        deadline=match["deadline"],
        ship_to=match["city"].strip(),
    )


class FakeBuyer:
    """Test mode's stand-in for the buyer's AI agent. Each conversation searches, asks for a quote within the request's
    limits, drafts the order from the quote and gets its approval link, choosing from the tools' answers."""

    label = "test mode's stand-in for Claude"

    def conversation(self) -> "FakeBuyerConversation":
        return FakeBuyerConversation()


class FakeBuyerConversation:
    def __init__(self) -> None:
        self.wanted: Wanted | None = None
        self.calls = 0
        self.makers: list[str] = []

    def begin(self, system: str, request: str, tools: Sequence[ToolSpec]) -> AgentTurn:
        self.wanted = wanted(request)
        if self.wanted is None or "search_products" not in {tool.name for tool in tools}:
            return AgentTurn("I could not tell what to buy from that request. Please say what, how many and by when.")
        return self._call(
            "I'll look for makers who can make these first.",
            "search_products",
            {"query": self.wanted.items, "quantity": self.wanted.quantity},
        )

    def answer(self, results: Sequence[ToolResult]) -> AgentTurn:
        last = results[-1]
        content = last.content or {}
        if last.is_error:
            return AgentTurn(f"I stopped: {last.call.name} refused ({last.text[:160]}).")
        assert self.wanted is not None
        if last.call.name == "search_products":
            found = content.get("result") or []
            makers = len({row.get("seller_id") for row in found if isinstance(row, dict)})
            return self._call(
                f"{makers} makers sell something like this. I'll ask them for a quote within your limits.",
                "request_quote",
                {
                    "items": [self.wanted.items],
                    "quantity": self.wanted.quantity,
                    "max_unit_price": self.wanted.max_unit_price,
                    "deadline": self.wanted.deadline,
                    "ship_to": self.wanted.ship_to,
                },
            )
        if last.call.name == "request_quote":
            plan = content.get("plan") or {}
            self.makers = [f"{line['seller_name']} {line['quantity']}" for line in plan.get("lines") or []]
            return self._call(
                f"The quote is in, split across {len(self.makers)} makers. I'll draft the order.",
                "create_collective_order",
                {"request_id": content.get("request_id")},
            )
        if last.call.name == "create_collective_order":
            self.total = content.get("total_usd")
            self.order_id = content.get("order_id")
            return self._call("Drafted. Now the approval link for you.", "checkout", {"order_id": self.order_id})
        if last.call.name == "checkout":
            return AgentTurn(
                f"Order {self.order_id} is drafted: ${self.total} for {self.wanted.quantity}, from "
                f"{', '.join(self.makers)}. Approve it here, and PayPal only holds the money until each maker "
                f"ships: {content.get('approval_url')}"
            )
        return AgentTurn("I have what I need.")

    def _call(self, said: str, name: str, arguments: dict[str, Any]) -> AgentTurn:
        self.calls += 1
        return AgentTurn(said, (ToolCall(f"call_{self.calls}", name, arguments),))


def tool_text(content: dict[str, Any] | None, words: str) -> str:
    """A tool's answer as the model reads it: its structured content as JSON, else its words."""
    return json.dumps(content, ensure_ascii=False, separators=(",", ":")) if content is not None else words
