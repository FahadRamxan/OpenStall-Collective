"""The scripted buyer agent: the story's request, played through OpenStall's MCP storefront (spec section 2).

It searches, asks for a quote (40 hand-embroidered cushion covers, at most $30 each, due 30 days from today, to
Chicago), drafts the collective order and gets the approval link for a person, printing each step. It cannot move
money: open the link to approve.

Usage: python scripts/run_demo_request.py [--url http://localhost:8000/mcp] [--pause]
"""

import argparse
import asyncio
from datetime import UTC, datetime

from mcp import Client

from openstall_api.buyer import BuyerError, run_story


async def main(url: str, pause: bool) -> int:
    async def wait(step: str) -> None:
        if pause:
            await asyncio.to_thread(input, f"Press Enter for the next step ({step})...")

    try:
        async with Client(url) as client:
            await run_story(client, datetime.now(UTC).date(), pause=wait)
    except BuyerError as error:
        print(f"The buyer agent stopped: {error}")
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000/mcp", help="the MCP storefront to buy from")
    parser.add_argument("--pause", action="store_true", help="wait for Enter between steps, for recording a video")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.url, args.pause)))
