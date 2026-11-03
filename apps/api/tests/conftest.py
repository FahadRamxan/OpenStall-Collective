"""Fixtures for the API tests (the repo root's conftest.py gives every test fake mode and its own database).

- `api_server`: the real FastAPI app on a free local port, for tests that go over HTTP as an outside client does.
- `server_url`: the MCP storefront on that server, at /mcp.

Nothing from the app is imported at the top of this file. When pytest is given a test file in this folder, it loads
this file before the root conftest.py switches to fake mode and stops reading .env, and the app reads the settings
once when it is imported (for CORS and the MCP host check).
"""

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn


@pytest.fixture(scope="session")
def api_server() -> Iterator[str]:
    """One server for the whole run: the app's start-up runs the MCP session manager, which can only start once per
    process. The app reads the settings and the database per request, so each test still gets its own database.

    It starts before the first test that uses it has its settings, so it starts without migrating: otherwise it would
    migrate the default database, data/openstall.db. Each test makes its own tables.
    """
    from openstall_api.adapters import reset_app_state
    from openstall_api.main import app

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    with pytest.MonkeyPatch.context() as env:
        env.setenv("AUTO_MIGRATE", "false")
        reset_app_state()
        thread.start()
        give_up = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > give_up:
                raise RuntimeError("API did not start")
            time.sleep(0.05)
    reset_app_state()  # forget the settings read for the start-up
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def server_url(api_server: str) -> str:
    """The MCP storefront, over Streamable HTTP."""
    return f"{api_server}/mcp"
