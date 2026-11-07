"""The PayPal ops agent (prompt 55): an operator's question about OpenStall's money, answered by an AI agent that
reads PayPal through PayPal's own MCP server.

The agent is offered only the server's tools that read (`openstall_paypal.paypal_mcp.OPS_TOOLS`), and the caller
refuses any other call before it reaches PayPal: it cannot pay, refund, accept a dispute's claim or change anything.
It runs on the buyer agent's loop (buyer_agent.run_buyer_agent) with its own instructions, so the same models serve:
Claude's conversation (adapters/claude.py, ClaudeBuyer) in sandbox mode, and FakeOpsAgent in test mode, which reads the
order it is told about, then the disputes, and says what PayPal answered.
"""

import json
import re
from collections.abc import Sequence
from typing import Any

from openstall_agents.buyer_agent import AgentRun, AgentTurn, BuyerModel, Call, ToolCall, ToolResult, ToolSpec
from openstall_agents.buyer_agent import run_buyer_agent

MAX_TURNS = 6

SYSTEM = (
    "You are OpenStall's PayPal operations agent. OpenStall sells home makers' goods as one collective: each order is "
    "one PayPal order with intent AUTHORIZE, whose authorization holds the buyer's money; each maker's share is "
    "captured from it when she ships, and whatever is left is voided. You read PayPal only through the tools of "
    "PayPal's own MCP server you are given, all of which only read. You cannot pay, refund, accept a dispute's claim "
    "or change anything, and must not try. Answer the operator's question in two or three plain sentences: what PayPal "
    "says, with the PayPal ids you read, and plainly when PayPal answered with an error."
)

# A PayPal order id: PayPal's own (17 capitals and digits), or test mode's simulated PayPal's (FAKE- and 16 more).
ORDER_ID = re.compile(r"\b(FAKE-[0-9A-F]{16}|[A-Z0-9]{17})\b")


async def run_ops_agent(
    model: BuyerModel, question: str, tools: Sequence[ToolSpec], call: Call, *, max_turns: int = MAX_TURNS
) -> AgentRun:
    """Let the agent answer `question` with `tools`, each call run through `call`, until it stops."""
    return await run_buyer_agent(model, question, tools, call, max_turns=max_turns, system=SYSTEM)


def order_words(order: dict[str, Any]) -> str:
    """What PayPal said of an order, in a sentence: its status, the amount, the hold and the captures."""
    unit = (order.get("purchase_units") or [{}])[0]
    payments = unit.get("payments") or {}
    holds = payments.get("authorizations") or []
    captures = payments.get("captures") or []
    captured = sum(float((capture.get("amount") or {}).get("value", 0)) for capture in captures)
    held = (unit.get("amount") or {}).get("value", "?")
    hold = f"authorization {holds[0].get('id')} is {holds[0].get('status')}" if holds else "no authorization yet"
    return (
        f"PayPal says order {order.get('id')} is {order.get('status')}, for ${held}: {hold}, with "
        f"{len(captures)} capture{'s' if len(captures) != 1 else ''} (${captured:,.2f} taken)."
    )


class FakeOpsAgent:
    """Test mode's stand-in for the ops agent: it reads the order the question names, then the disputes, and says
    what PayPal answered."""

    label = "Test mode's stand-in for the ops agent"

    def conversation(self) -> "FakeOpsConversation":
        return FakeOpsConversation()


class FakeOpsConversation:
    def __init__(self) -> None:
        self.order: str | None = None
        self.said: list[str] = []

    def begin(self, system: str, request: str, tools: Sequence[ToolSpec]) -> AgentTurn:
        offered = {tool.name for tool in tools}
        found = ORDER_ID.search(request)
        if found and "get_order" in offered:
            return self._call(f"I read order {found[1]} at PayPal.", "get_order", {"id": found[1]})
        return self._call("I read the disputes at PayPal.", "list_disputes", {})

    def answer(self, results: Sequence[ToolResult]) -> AgentTurn:
        result = results[-1]
        content = result.content or {}
        if result.is_error:
            self.said.append(f"PayPal refused {result.call.name}: {result.text[:160]}")
        elif result.call.name == "get_order":
            self.said.append(order_words(content))
        elif result.call.name == "list_disputes":
            items = content.get("items") or []
            self.said.append(
                f"{len(items)} dispute{'s are' if len(items) != 1 else ' is'} open at PayPal"
                + (": " + ", ".join(str(item.get("dispute_id")) for item in items[:3]) if items else ".")
            )
        if result.call.name == "get_order":
            return self._call("Now the disputes.", "list_disputes", {})
        return AgentTurn(said=" ".join(self.said))

    def _call(self, said: str, name: str, arguments: dict[str, Any]) -> AgentTurn:
        return AgentTurn(said="", calls=(ToolCall(id=f"call_{name}", name=name, arguments=arguments),))


def result_text(content: dict[str, Any] | None) -> str:
    return json.dumps(content or {}, ensure_ascii=False)[:4000]
