"""PayPal's own MCP server (prompt 55): started with npx and a token in its environment only, its answers read as data
(PayPal's errors arrive as "ok": false, not as MCP errors), and every tool that writes refused before anything is sent."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from openstall_paypal import PaymentError
from openstall_paypal.paypal_mcp import (
    OPS_TOOLS,
    PACKAGE,
    READ_TOOLS,
    ToolRefused,
    call_read_tool,
    server_parameters,
    tool_answer,
)

WRITES = {
    "accept_dispute_claim",
    "cancel_sent_invoice",
    "cancel_subscription",
    "create_invoice",
    "create_order",
    "create_product",
    "create_refund",
    "create_shipment_tracking",
    "create_subscription",
    "create_subscription_plan",
    "generate_invoice_qr_code",
    "pay_order",
    "send_invoice",
    "send_invoice_reminder",
    "update_product",
}  # the rest of the 28 tools PayPal's server listed on the sandbox on November 8


def test_the_ops_agent_is_offered_only_tools_that_read() -> None:
    assert set(OPS_TOOLS) <= READ_TOOLS
    assert not READ_TOOLS & WRITES
    assert len(READ_TOOLS | WRITES) == 28  # every tool the server lists is one or the other


def test_the_server_is_started_with_npx_and_the_token_only_in_its_environment() -> None:
    params = server_parameters("made-up-token-1f2e", npx="/usr/bin/npx")

    assert (params.command, params.args) == ("/usr/bin/npx", ["-y", PACKAGE, "--tools=all"])
    assert PACKAGE == "@paypal/mcp@1.8.1"  # pinned: a new release cannot change the tools under us
    assert params.env is not None
    assert (params.env["PAYPAL_ACCESS_TOKEN"], params.env["PAYPAL_ENVIRONMENT"]) == ("made-up-token-1f2e", "SANDBOX")
    assert "made-up-token-1f2e" not in " ".join(params.args)  # never on a command line others can read
    assert server_parameters("t", sandbox=False, npx="npx").env["PAYPAL_ENVIRONMENT"] == "PRODUCTION"  # type: ignore[index]


def test_without_npx_the_server_cannot_start_and_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("openstall_paypal.paypal_mcp.npx_path", lambda: None)

    with pytest.raises(PaymentError) as error:
        server_parameters("t")

    assert error.value.issue == "NPX_MISSING"


def answer(text: str, *, is_error: bool = False) -> Any:
    return SimpleNamespace(content=[SimpleNamespace(text=text)], is_error=is_error)


def test_paypal_s_own_errors_arrive_as_data_and_count_as_refused() -> None:
    assert tool_answer(answer('{"items": []}')) == ({"items": []}, False)
    data, refused = tool_answer(answer('{"ok": false, "status": 404, "message": "The specified resource does not exist."}'))
    assert (data["status"], refused) == (404, True)
    assert tool_answer(answer("not json")) == ({"text": "not json"}, False)
    assert tool_answer(answer("{}", is_error=True))[1] is True


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        return answer('{"id": "5O190127TN364715T", "status": "COMPLETED"}')


def test_a_read_tool_is_called_and_a_tool_that_writes_never_is() -> None:
    client = Recorder()

    data, refused = asyncio.run(call_read_tool(client, "get_order", {"id": "5O190127TN364715T"}))  # type: ignore[arg-type]
    assert (data["status"], refused) == ("COMPLETED", False)

    for name in ("create_refund", "pay_order", "accept_dispute_claim"):
        with pytest.raises(ToolRefused) as error:
            asyncio.run(call_read_tool(client, name, {"capture_id": "C1"}))  # type: ignore[arg-type]
        assert error.value.issue == "TOOL_REFUSED"
    assert client.calls == [("get_order", {"id": "5O190127TN364715T"})]
