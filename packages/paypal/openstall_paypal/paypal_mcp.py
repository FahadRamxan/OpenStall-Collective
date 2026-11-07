"""PayPal's own MCP server (prompt 55): the ops agent's window onto PayPal.

PayPal publishes an MCP server, `@paypal/mcp` on npm, that offers PayPal's APIs as tools: orders, disputes, shipment
tracking, transactions, refunds, invoices, products and subscriptions. OpenStall connects to it over stdio, run with
npx, with an access token minted from the app's own client id and secret, and uses only the tools that read. A tool that
pays, refunds, accepts a claim, sends, cancels or creates anything is never called and never offered to an agent: no
agent tool moves money (spec 3.2).

Proven on the sandbox on November 8: the server (version 1.8.1) lists 28 tools; get_order answers, with PayPal's 404
for an order it does not know, and list_disputes answers. list_transactions needs the app's Transaction Search
permission, which is off for this sandbox app, so it answers 403.

Test mode runs `stand_in`, an MCP server in process with the same read tools, answering from the simulated PayPal.
"""

import json
import os
import shutil
from collections.abc import Mapping
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from openstall_paypal.gateway import PaymentError

__all__ = [
    "OPS_TOOLS",
    "PACKAGE",
    "READ_TOOLS",
    "ToolRefused",
    "call_read_tool",
    "npx_path",
    "server_parameters",
    "tool_answer",
]

PACKAGE = "@paypal/mcp@1.8.1"  # the version proven on the sandbox; pinned so a new release cannot change the tools
# The server's tools that only read. Everything else it offers writes: create_*, send_*, cancel_*, update_*,
# pay_order, create_refund, accept_dispute_claim and generate_invoice_qr_code.
READ_TOOLS = frozenset(
    {
        "get_order",
        "list_disputes",
        "get_dispute",
        "get_shipment_tracking",
        "list_transactions",
        "get_refund",
        "get_invoice",
        "list_invoices",
        "list_products",
        "show_product_details",
        "list_subscription_plans",
        "show_subscription_plan_details",
        "show_subscription_details",
    }
)
# What the ops agent is offered: the read tools about OpenStall's own money.
OPS_TOOLS = ("get_order", "list_disputes", "get_dispute", "get_shipment_tracking", "list_transactions")


class ToolRefused(PaymentError):
    """A PayPal MCP tool that writes: never called."""

    def __init__(self, name: str) -> None:
        super().__init__("TOOL_REFUSED", f"{name} changes something at PayPal; the ops agent only reads")


def npx_path() -> str | None:
    """Node's npx, which runs PayPal's MCP server. None where Node is not installed."""
    return shutil.which("npx") or shutil.which("npx.cmd")


def server_parameters(access_token: str, *, sandbox: bool = True, npx: str | None = None) -> StdioServerParameters:
    """How to start PayPal's MCP server: npx, the pinned package, every tool listed (OpenStall calls only the read ones),
    and the token in the server's own environment, never on its command line."""
    command = npx or npx_path()
    if command is None:
        raise PaymentError("NPX_MISSING", "PayPal's MCP server runs with Node's npx, which is not installed here")
    env = {
        **os.environ,
        "PAYPAL_ACCESS_TOKEN": access_token,
        "PAYPAL_ENVIRONMENT": "SANDBOX" if sandbox else "PRODUCTION",
    }
    return StdioServerParameters(command=command, args=["-y", PACKAGE, "--tools=all"], env=env)


def tool_answer(result: Any) -> tuple[dict[str, Any], bool]:
    """A tool's answer as data, and whether PayPal refused it. The server answers PayPal's own errors as JSON with
    "ok": false (a 404, a 403) rather than as MCP errors."""
    text = " ".join(str(getattr(part, "text", "")) for part in getattr(result, "content", []) or [])
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError:
        data = {"text": text}
    if not isinstance(data, dict):
        data = {"items": data}
    refused = bool(getattr(result, "is_error", False)) or data.get("ok") is False
    return data, refused


async def call_read_tool(client: Client, name: str, arguments: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """Call one PayPal MCP tool that reads. A tool that writes is refused before anything is sent."""
    if name not in READ_TOOLS:
        raise ToolRefused(name)
    return tool_answer(await client.call_tool(name, dict(arguments)))
