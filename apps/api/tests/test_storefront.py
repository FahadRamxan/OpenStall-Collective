import asyncio
import logging
import socket
import threading
import time

import pytest
import uvicorn
from mcp import Client

from openstall_api.main import app
from openstall_api.storefront import storefront

ALL_SELLERS = {"s_amina", "s_priya", "s_lucia", "s_grace"}


def search(target, query, **filters):
    """Call search_products on an in-process server or a URL; return the seller IDs found."""

    async def go():
        async with Client(target) as client:
            result = await client.call_tool("search_products", {"query": query, **filters})
            return {p["seller_id"] for p in result.structured_content["result"]}

    return asyncio.run(go())


@pytest.fixture(scope="module")
def server_url():
    """Run the real FastAPI app on a free local port, so the test goes over Streamable HTTP."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    give_up = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > give_up:
            raise RuntimeError("API did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


def test_search_finds_every_cushion_seller():
    assert search(storefront, "embroidered cushion covers") == ALL_SELLERS


def test_max_price_filters_out_expensive_sellers():
    assert search(storefront, "cushion covers", max_price=20) == {"s_amina", "s_priya"}


def test_search_with_no_results_is_logged(caplog):
    caplog.set_level(logging.INFO, logger="openstall_api.storefront")
    assert search(storefront, "ceramic mugs") == set()
    assert "ceramic mugs" in caplog.text


def test_storefront_over_http(server_url):
    assert search(server_url, "cushion covers") == ALL_SELLERS


def test_search_is_marked_read_only(server_url):
    async def go():
        async with Client(server_url) as client:
            tools = await client.list_tools()
            return {tool.name: tool.annotations for tool in tools.tools}

    annotations = asyncio.run(go())
    assert annotations["search_products"].read_only_hint is True
