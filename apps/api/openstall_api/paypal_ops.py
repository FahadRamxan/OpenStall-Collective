"""The PayPal ops agent (prompt 55): OpenStall's own records checked against PayPal, through PayPal's own MCP server.

- `check_order`: for an order, what PayPal says through the server's read tools (get_order, list_disputes), side by
  side with OpenStall's records: the order's status, the amount, the authorization, each maker's capture and tracker,
  and any dispute. Code compares; no model is needed. A difference is said plainly.
- `ask`: an operator's question in words, answered by an AI agent (Claude in sandbox mode, test mode's stand-in) that
  is offered only the read tools (`OPS_TOOLS`). A call to any other tool is refused before it reaches PayPal: the
  agent cannot pay, refund, accept a claim or change anything.

In sandbox mode the server is PayPal's own (`npx @paypal/mcp`, pinned), started with a token minted from the app's keys;
it needs Node's npx on the host. Test mode connects to `stand_in`, an MCP server in process with the same read tools,
answering from the simulated PayPal. `GET /api/paypal/ops/tools`, `POST /api/paypal/ops/check` and
`POST /api/paypal/ops/ask`; the last two need the demo token in sandbox mode, and asking counts against the AI limits.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from mcp import Client
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from sqlalchemy import select

from openstall_agents.buyer_agent import ToolCall, ToolResult, ToolSpec
from openstall_agents.ops_agent import FakeOpsAgent, result_text, run_ops_agent
from openstall_api.adapters import AdapterRegistry, AdapterUnavailable, get_registry
from openstall_api.db import new_session
from openstall_api.demo_api import demo_controls_allowed
from openstall_api.limits import check
from openstall_api.models import Order, PartStatus
from openstall_paypal import FakeGateway, PaymentError, SandboxGateway, sandbox_host
from openstall_paypal.paypal_mcp import OPS_TOOLS, PACKAGE, READ_TOOLS, ToolRefused, call_read_tool, server_parameters

router = APIRouter(prefix="/api/paypal/ops", tags=["paypal"])

READS = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)


def stand_in(gateway: FakeGateway) -> MCPServer:
    """Test mode's PayPal MCP server: the same tool names as PayPal's, the read ones answering from the simulated
    PayPal, and three of the ones that write, which answer that OpenStall never calls them (and it never does)."""
    server = MCPServer("PayPal (test mode's stand-in)")

    def missing(kind: str, name: str) -> dict[str, Any]:
        return {"ok": False, "status": 404, "message": f"Simulated PayPal knows no {kind} {name}."}

    @server.tool(annotations=READS)
    def get_order(id: str) -> str:
        """Show an order's details: its status, amount, authorization, captures and trackers."""
        try:
            return json.dumps(gateway.paypal_view(id))
        except PaymentError:
            return json.dumps(missing("order", id))

    @server.tool(annotations=READS)
    def list_disputes(dispute_state: str | None = None) -> str:
        """List the disputes buyers opened."""
        items = [
            {"dispute_id": item["dispute_id"], "reason": item["reason"], "status": item["status"]}
            for item in gateway.disputes()
            if dispute_state is None or item.get("status") == dispute_state
        ]
        return json.dumps({"items": items})

    @server.tool(annotations=READS)
    def get_dispute(dispute_id: str) -> str:
        """Show one dispute in full."""
        found = next((item for item in gateway.disputes() if item["dispute_id"] == dispute_id), None)
        return json.dumps(found or missing("dispute", dispute_id))

    @server.tool(annotations=READS)
    def get_shipment_tracking(order_id: str, transaction_id: str | None = None) -> str:
        """Show the shipment trackers on an order."""
        try:
            unit = gateway.paypal_view(order_id)["purchase_units"][0]
        except PaymentError:
            return json.dumps(missing("order", order_id))
        trackers = (unit.get("shipping") or {}).get("trackers") or []
        if transaction_id:
            trackers = [tracker for tracker in trackers if str(tracker["id"]).startswith(transaction_id)]
        return json.dumps({"trackers": trackers})

    @server.tool(annotations=READS)
    def list_transactions() -> str:
        """List the account's transactions: here, each capture of the simulated PayPal's orders."""
        return json.dumps({"transaction_details": gateway.captures()})

    def refuse(id: str) -> str:
        return json.dumps({"ok": False, "message": "Simulated PayPal: OpenStall never calls this tool."})

    for name in ("pay_order", "create_refund", "accept_dispute_claim"):
        server.tool(name=name, description=f"{name}: changes something at PayPal.", annotations=WRITES)(refuse)
    return server


def server_label(registry: AdapterRegistry) -> str:
    settings = registry.settings
    if settings.OPENSTALL_MODE == "fake":
        return "Test mode's stand-in for PayPal's MCP server"
    where = "sandbox" if sandbox_host(settings.PAYPAL_API_BASE) else "live"
    return f"PayPal's MCP server ({PACKAGE}, {where})"


@asynccontextmanager
async def paypal_mcp(registry: AdapterRegistry) -> AsyncIterator[Client]:
    """A session with PayPal's MCP server: PayPal's own in sandbox mode, test mode's stand-in otherwise."""
    gateway = registry.payment_gateway
    if isinstance(gateway, FakeGateway):
        async with Client(stand_in(gateway)) as client:
            yield client
        return
    if not isinstance(gateway, SandboxGateway):
        raise AdapterUnavailable("The PayPal ops agent needs the sandbox PayPal gateway.")
    token = gateway.client.token()
    params = server_parameters(token, sandbox=sandbox_host(registry.settings.PAYPAL_API_BASE))
    async with Client(params, read_timeout_seconds=60) as client:
        yield client


class ToolOut(BaseModel):
    name: str
    reads: bool  # only reads at PayPal
    offered: bool  # offered to the ops agent


class ToolsOut(BaseModel):
    server: str
    tools: list[ToolOut]


class Finding(BaseModel):
    check: str
    ok: bool
    ours: str
    paypal: str


class OpsCheck(BaseModel):
    order_id: str
    paypal_order_id: str | None
    server: str
    agrees: bool  # every finding agrees
    findings: list[Finding]


class OpsStep(BaseModel):
    tool: str
    arguments: dict[str, Any]
    ok: bool
    summary: str


class OpsAnswer(BaseModel):
    agent: str
    server: str
    question: str
    steps: list[OpsStep]
    answer: str
    refused: list[str]  # tools the agent asked for that write, never called


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


# OpenStall's order statuses, and what PayPal's Orders API shows for each.
PAYPAL_STATUSES: dict[str, tuple[str, ...]] = {
    "awaiting_approval": ("CREATED", "PAYER_ACTION_REQUIRED", "APPROVED"),
    "authorized": ("COMPLETED",),
    "partly_shipped": ("COMPLETED",),
    "shipped": ("COMPLETED",),
    "completed": ("COMPLETED",),
}


def latest_order_id() -> str:
    with new_session() as session:
        order = session.scalar(
            select(Order).where(Order.paypal_order_id.is_not(None)).order_by(Order.created_at.desc(), Order.id.desc())
        )
        if order is None:
            raise HTTPException(status_code=404, detail="No order has reached PayPal yet.")
        return order.id


async def check_order(registry: AdapterRegistry, order_id: str) -> OpsCheck:
    """What PayPal says of an order through its MCP server, beside OpenStall's own records."""
    with new_session() as session:
        order = session.get(Order, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail=f"There is no order called {order_id!r}.")
        paypal_order_id, status, total = order.paypal_order_id, order.status.value, Decimal(order.total_usd)
        shares = [
            (
                part.seller.name,
                part.status,
                part.authorization_id,
                part.capture_id,
                part.amount_usd,
                part.paypal_tracker_id,
                (part.dispute_json or {}).get("dispute_id"),
            )
            for part in order.parts
        ]
    findings: list[Finding] = []
    if paypal_order_id is None:
        nothing = Finding(check="The order at PayPal", ok=False, ours="not sent to PayPal yet", paypal="nothing")
        return OpsCheck(
            order_id=order_id, paypal_order_id=None, server=server_label(registry), agrees=False, findings=[nothing]
        )
    async with paypal_mcp(registry) as client:
        seen, refused = await call_read_tool(client, "get_order", {"id": paypal_order_id})
        disputes, disputes_refused = await call_read_tool(client, "list_disputes", {})
    if refused:
        findings.append(
            Finding(check="The order at PayPal", ok=False, ours=paypal_order_id, paypal=str(seen.get("message"))[:200])
        )
        label = server_label(registry)
        return OpsCheck(
            order_id=order_id, paypal_order_id=paypal_order_id, server=label, agrees=False, findings=findings
        )
    unit = (seen.get("purchase_units") or [{}])[0]
    paypal_status = str(seen.get("status"))
    findings.append(
        Finding(
            check="The order's status",
            ok=paypal_status in PAYPAL_STATUSES.get(status, ()),
            ours=status.replace("_", " "),
            paypal=paypal_status,
        )
    )
    held = Decimal(str((unit.get("amount") or {}).get("value", "0")))
    findings.append(Finding(check="The amount", ok=held == total, ours=f"${total:,.2f}", paypal=f"${held:,.2f}"))
    payments = unit.get("payments") or {}
    holds = {str(item.get("id")): str(item.get("status")) for item in payments.get("authorizations") or []}
    ours_holds = {hold for _, _, hold, _, _, _, _ in shares if hold}
    if ours_holds:
        hold = sorted(ours_holds)[0]
        findings.append(
            Finding(
                check="The authorization holding the money",
                ok=hold in holds,
                ours=hold,
                paypal=f"{hold} {holds[hold]}" if hold in holds else ", ".join(holds) or "none",
            )
        )
    captures = {
        str(item.get("id")): str((item.get("amount") or {}).get("value")) for item in payments.get("captures") or []
    }
    trackers = {str(item.get("id")) for item in (unit.get("shipping") or {}).get("trackers") or []}
    for name, part_status, _, capture_id, amount, tracker, _ in shares:
        if part_status in (PartStatus.CAPTURED, PartStatus.DELIVERED) and capture_id:
            findings.append(
                Finding(
                    check=f"{name}'s capture",
                    ok=captures.get(capture_id) == f"{amount:.2f}",
                    ours=f"{capture_id}, ${amount:,.2f}",
                    paypal=f"{capture_id}, ${captures[capture_id]}" if capture_id in captures else "no such capture",
                )
            )
        if tracker:
            on_order = tracker in trackers
            findings.append(
                Finding(
                    check=f"{name}'s tracking",
                    ok=on_order,
                    ours=tracker,
                    paypal="on the order" if on_order else "not on the order",
                )
            )
    open_disputes = {str(item.get("dispute_id")): str(item.get("status")) for item in disputes.get("items") or []}
    ours_disputes = {dispute for *_, dispute in shares if dispute}
    findings.append(
        Finding(
            check="Disputes",
            ok=not disputes_refused and ours_disputes <= set(open_disputes),
            ours=", ".join(sorted(ours_disputes)) or "none",
            paypal=str(disputes.get("message"))[:200]
            if disputes_refused
            else ", ".join(f"{key} {value}" for key, value in sorted(open_disputes.items())) or "none",
        )
    )
    return OpsCheck(
        order_id=order_id,
        paypal_order_id=paypal_order_id,
        server=server_label(registry),
        agrees=all(finding.ok for finding in findings),
        findings=findings,
    )


async def ask(registry: AdapterRegistry, question: str) -> OpsAnswer:
    """The ops agent answers in words, reading PayPal through the server's read tools only."""
    model = FakeOpsAgent() if registry.settings.OPENSTALL_MODE == "fake" else registry.buyer_agent
    context = ""
    try:
        latest = latest_order_id()
        with new_session() as session:
            order = session.get(Order, latest)
            if order is not None and order.paypal_order_id:
                context = f"The latest OpenStall order is {order.id}, PayPal order {order.paypal_order_id}. "
    except HTTPException:
        pass
    refused: list[str] = []
    async with paypal_mcp(registry) as client:
        listed = (await client.list_tools()).tools
        tools = [
            ToolSpec(tool.name, tool.description or "", dict(tool.input_schema or {}))
            for tool in listed
            if tool.name in OPS_TOOLS
        ]

        async def call(made: ToolCall) -> ToolResult:
            if made.name not in OPS_TOOLS:
                refused.append(made.name)
                return ToolResult(made, None, str(ToolRefused(made.name)), is_error=True)
            data, failed = await call_read_tool(client, made.name, made.arguments)
            return ToolResult(made, data, result_text(data), is_error=failed)

        run = await run_ops_agent(model, f"{context}{question}", tools, call)
    return OpsAnswer(
        agent=run.agent,
        server=server_label(registry),
        question=question,
        steps=[
            OpsStep(tool=step.tool, arguments=step.arguments, ok=step.ok, summary=step.summary) for step in run.steps
        ],
        answer=" ".join(run.said).strip() or "The agent stopped without an answer.",
        refused=refused,
    )


def unavailable(error: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=f"PayPal's MCP server could not be reached: {error}")


@router.get("/tools")
async def read_tools(registry: Annotated[AdapterRegistry, Depends(get_registry)]) -> ToolsOut:
    """The PayPal MCP server's tools: which only read, and which the ops agent is offered. Never one that writes."""
    try:
        async with paypal_mcp(registry) as client:
            names = sorted(tool.name for tool in (await client.list_tools()).tools)
    except (PaymentError, AdapterUnavailable, OSError) as error:
        raise unavailable(error) from None
    return ToolsOut(
        server=server_label(registry),
        tools=[ToolOut(name=name, reads=name in READ_TOOLS, offered=name in OPS_TOOLS) for name in names],
    )


@router.post("/check", dependencies=[Depends(demo_controls_allowed)])
async def run_check(
    registry: Annotated[AdapterRegistry, Depends(get_registry)], order_id: str | None = None
) -> OpsCheck:
    """OpenStall's records for an order (the latest that reached PayPal, by default) beside what PayPal says."""
    try:
        return await check_order(registry, order_id or latest_order_id())
    except (PaymentError, AdapterUnavailable, OSError) as error:
        raise unavailable(error) from None


@router.post("/ask", dependencies=[Depends(demo_controls_allowed)])
async def run_ask(body: Question, registry: Annotated[AdapterRegistry, Depends(get_registry)]) -> OpsAnswer:
    """An operator's question, answered by the ops agent from PayPal's read tools."""
    check("agent_run")  # in sandbox mode it calls Claude in a loop, as the buyer agent does
    try:
        return await ask(registry, body.question)
    except (PaymentError, AdapterUnavailable, OSError) as error:
        raise unavailable(error) from None
