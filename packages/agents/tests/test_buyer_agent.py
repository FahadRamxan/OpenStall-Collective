"""The buyer's AI agent (prompt 30): the loop that lets a model choose the storefront's tools, test mode's stand-in, and
ClaudeBuyer against a fake transport (nothing here reaches Anthropic's API)."""

import asyncio
import json

import anthropic
import httpx2
import pytest

from openstall_agents.adapters import LLMError
from openstall_agents.adapters.claude import FALLBACK_BETA, ClaudeBuyer
from openstall_agents.buyer_agent import (
    SYSTEM,
    AgentTurn,
    FakeBuyer,
    ToolCall,
    ToolResult,
    ToolSpec,
    run_buyer_agent,
    tool_text,
    wanted,
)

REQUEST = (
    "Please buy 40 hand-embroidered cushion covers for corporate gifts, at most $30.00 each, delivered to Chicago by "
    "2026-12-10. Get me the approval link: I approve the payment myself."
)
TOOLS = [
    ToolSpec(name, f"The {name} tool.", {"type": "object", "properties": {}})
    for name in ("search_products", "request_quote", "create_collective_order", "checkout", "get_order_status")
]
ANSWERS = {
    "search_products": {"result": [{"seller_id": "s_amina"}, {"seller_id": "s_priya"}, {"seller_id": "s_priya"}]},
    "request_quote": {
        "request_id": "q_1",
        "offers": [{}, {}],
        "plan": {"lines": [{"seller_name": "Amina", "quantity": 28}, {"seller_name": "Priya", "quantity": 12}]},
    },
    "create_collective_order": {"order_id": "ord_1", "total_usd": "696.00"},
    "checkout": {"approval_url": "http://web.test/approve/ord_1"},
}


def storefront(refuse: str | None = None):
    """The storefront's answers to each call, as an MCP client would hand them back. `refuse` names a tool that
    fails."""
    made: list[ToolCall] = []

    async def call(tool_call: ToolCall) -> ToolResult:
        made.append(tool_call)
        if tool_call.name == refuse:
            return ToolResult(tool_call, None, "The deadline has passed.", is_error=True)
        content = ANSWERS[tool_call.name]
        return ToolResult(tool_call, content, tool_text(content, ""))

    return call, made


def test_the_request_is_read_the_way_the_stand_in_needs_it():
    asked = wanted(REQUEST)

    assert asked is not None
    assert asked.items == "hand-embroidered cushion covers for corporate gifts"
    assert (asked.quantity, asked.max_unit_price) == (40, 30)
    assert (asked.deadline, asked.ship_to) == ("2026-12-10", "Chicago")
    assert wanted("buy something nice") is None


def test_the_stand_in_searches_quotes_drafts_and_gets_the_link_choosing_from_the_answers():
    call, made = storefront()

    run = asyncio.run(run_buyer_agent(FakeBuyer(), REQUEST, TOOLS, call))

    tools = [step.tool for step in run.steps]
    assert tools == ["search_products", "request_quote", "create_collective_order", "checkout"]
    assert made[1].arguments == {
        "items": ["hand-embroidered cushion covers for corporate gifts"],
        "quantity": 40,
        "max_unit_price": 30,
        "deadline": "2026-12-10",
        "ship_to": "Chicago",
    }
    assert made[2].arguments == {"request_id": "q_1"} and made[3].arguments == {"order_id": "ord_1"}
    assert run.finished and (run.request_id, run.order_id, run.total_usd) == ("q_1", "ord_1", "696.00")
    assert run.approval_url == "http://web.test/approve/ord_1"
    assert run.said[-1].endswith("http://web.test/approve/ord_1") and "Amina 28, Priya 12" in run.said[-1]
    assert [step.summary for step in run.steps] == [
        "3 listings found",
        "Quote q_1: 2 valid offers",
        "Order ord_1 drafted: $696.00",
        "Approval link for the person",
    ]
    assert run.agent == "test mode's stand-in for Claude"


def test_a_tool_that_refuses_ends_the_run_in_words():
    call, _ = storefront(refuse="request_quote")

    run = asyncio.run(run_buyer_agent(FakeBuyer(), REQUEST, TOOLS, call))

    assert run.finished and run.order_id is None and run.approval_url is None
    assert run.steps[-1].ok is False and run.steps[-1].summary == "Refused: The deadline has passed."
    assert run.said[-1] == "I stopped: request_quote refused (The deadline has passed.)."


class Stubborn:
    """An agent that never stops calling tools."""

    label = "stubborn"

    def conversation(self):
        return self

    def begin(self, system, request, tools):
        return AgentTurn("Searching.", (ToolCall("c", "search_products", {}),))

    def answer(self, results):
        return AgentTurn("Searching again.", (ToolCall("c", "search_products", {}),))


def test_an_agent_that_never_stops_is_stopped():
    call, made = storefront()

    run = asyncio.run(run_buyer_agent(Stubborn(), REQUEST, TOOLS, call, max_turns=3))

    assert not run.finished and len(made) == 3


# ClaudeBuyer, against a fake transport


def answer(content: list[dict], stop_reason: str) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 40},
    }


class FakeAnthropic:
    def __init__(self, *responses: httpx2.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.responses.pop(0)

    def body(self, index: int) -> dict:
        return json.loads(self.requests[index].content)


def buyer(fake: FakeAnthropic) -> ClaudeBuyer:
    client = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(fake))
    return ClaudeBuyer("sk-ant-made-up", "claude-sonnet-5-5", max_retries=0, http_client=client)


def test_claude_chooses_the_tools_and_each_answer_goes_back_whole():
    thinking = {"type": "thinking", "thinking": "", "signature": "sig-made-up"}
    fake = FakeAnthropic(
        httpx2.Response(
            200,
            json=answer(
                [
                    thinking,
                    {"type": "text", "text": "I'll search first."},
                    {"type": "tool_use", "id": "toolu_1", "name": "search_products", "input": {"query": "covers"}},
                ],
                "tool_use",
            ),
        ),
        httpx2.Response(200, json=answer([{"type": "text", "text": "Here is your link."}], "end_turn")),
    )
    conversation = buyer(fake).conversation()

    first = conversation.begin(SYSTEM, REQUEST, TOOLS[:1])
    result = ToolResult(first.calls[0], {"result": []}, '{"result":[]}')
    second = conversation.answer([result])

    assert first == AgentTurn("I'll search first.", (ToolCall("toolu_1", "search_products", {"query": "covers"}),))
    assert second == AgentTurn("Here is your link.")
    sent = fake.body(0)
    assert FALLBACK_BETA in fake.requests[0].headers["anthropic-beta"] and sent["fallbacks"] == "default"
    assert sent["model"] == "claude-sonnet-5-5" and sent["system"] == SYSTEM
    assert sent["tools"] == [
        {
            "name": "search_products",
            "description": "The search_products tool.",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
    assert sent["output_config"] == {"effort": "medium"}
    assert "tool_choice" not in sent and not {"thinking", "temperature", "top_p", "top_k"} & set(sent)
    assert sent["messages"] == [{"role": "user", "content": REQUEST}]
    # The whole first answer goes back unchanged, thinking block and all, then every tool answer in one message.
    followed = fake.body(1)["messages"]
    assert followed[1]["role"] == "assistant"
    assert followed[1]["content"][0] == thinking
    assert followed[1]["content"][2] == {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "search_products",
        "input": {"query": "covers"},
    }
    assert followed[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"result":[]}', "is_error": False}],
    }


def test_a_refusal_stops_the_agent_in_words():
    fake = FakeAnthropic(httpx2.Response(200, json=answer([], "refusal")))

    with pytest.raises(LLMError, match="declined"):
        buyer(fake).conversation().begin(SYSTEM, REQUEST, TOOLS)
