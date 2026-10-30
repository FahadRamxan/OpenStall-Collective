"""Call the storefront from a real MCP client: list its tools, then run one search.

Usage: python scripts/try_mcp.py "cushion covers" [--url http://localhost:8000/mcp]
"""

import argparse
import asyncio
import json

from mcp import Client


async def main(url: str, query: str) -> None:
    async with Client(url) as client:
        tools = await client.list_tools()
        print("tools:", ", ".join(tool.name for tool in tools.tools))
        result = await client.call_tool("search_products", {"query": query})
        print(json.dumps(result.structured_content, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query")
    parser.add_argument("--url", default="http://localhost:8000/mcp")
    args = parser.parse_args()
    asyncio.run(main(args.url, args.query))
