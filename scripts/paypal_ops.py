"""The PayPal ops agent in a terminal (prompt 55): PayPal's own MCP server, through the app's own code.

    python scripts/paypal_ops.py tools               its tools: which only read, which the ops agent is offered
    python scripts/paypal_ops.py check [ORDER_ID]    an order's records beside PayPal's (the latest order by default)
    python scripts/paypal_ops.py ask "QUESTION"      the ops agent's answer (Claude in sandbox mode)

It reads .env as the API does. In sandbox mode it starts PayPal's MCP server with npx and a token minted from the app's
keys, and calls only tools that read: nothing it does changes anything at PayPal.
"""

import argparse
import asyncio
import sys

from openstall_api.adapters import get_registry
from openstall_api.paypal_ops import ask, check_order, latest_order_id, paypal_mcp, server_label
from openstall_paypal.paypal_mcp import OPS_TOOLS, READ_TOOLS


async def tools() -> None:
    registry = get_registry()
    async with paypal_mcp(registry) as client:
        names = sorted(tool.name for tool in (await client.list_tools()).tools)
    print(f"{server_label(registry)}: {len(names)} tools")
    for name in names:
        kind = "offered" if name in OPS_TOOLS else "reads, not offered" if name in READ_TOOLS else "writes: never called"
        print(f"  {name:32} {kind}")


async def check(order_id: str | None) -> bool:
    report = await check_order(get_registry(), order_id or latest_order_id())
    print(f"{report.server}: order {report.order_id} (PayPal {report.paypal_order_id})")
    for finding in report.findings:
        print(f"  {'agrees ' if finding.ok else 'DIFFERS'}  {finding.check}: OpenStall {finding.ours}; PayPal {finding.paypal}")
    return report.agrees


async def answer(question: str) -> None:
    reply = await ask(get_registry(), question)
    for step in reply.steps:
        print(f"  {step.tool} {step.arguments}: {step.summary}")
    print(f"\n{reply.agent}: {reply.answer}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("tools", help="list the server's tools")
    checking = commands.add_parser("check", help="an order's records beside PayPal's")
    checking.add_argument("order_id", nargs="?")
    asking = commands.add_parser("ask", help="ask the ops agent")
    asking.add_argument("question")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # makers' names on a Windows console
    if args.command == "tools":
        asyncio.run(tools())
        return 0
    if args.command == "check":
        return 0 if asyncio.run(check(args.order_id)) else 1
    asyncio.run(answer(args.question))
    return 0


if __name__ == "__main__":
    sys.exit(main())
