"""Security and abuse limits (prompt 46): how much any one client, and everyone together, may ask of OpenStall.

Most of OpenStall is public on purpose: AI agents shop through /mcp without an account, anyone may buy from a stall,
and sellers write in from WhatsApp. So the limits are on what costs money or fills the database, counted in a sliding
window per client, and refused with 429 and Retry-After:

| Limit       | How many            | Per            | What it protects                                        |
|-------------|---------------------|----------------|---------------------------------------------------------|
| api         | 600 requests        | client, minute | the API as a whole (webhooks and /health are not counted) |
| mcp         | 120 calls           | client, minute | the MCP storefront                                      |
| stall_order | 20 orders           | client, hour   | PayPal orders made from stall pages                     |
| demo        | 30 runs             | client, hour   | /demo's runs, resets and the guardrail panel            |
| quote       | 60 quote requests   | everyone, hour | the makers' AI agents a quote request starts            |
| agent_run   | 12 runs             | everyone, hour | a buyer's AI agent, which calls Claude in a loop        |
| chat        | 30 messages         | sender, 10 min | reading a seller's photos and voice notes with AI       |

A client is its IP address. Behind a proxy (Render), set PROXY_HOPS to the number of proxies in front of the API: the
address is then read from X-Forwarded-For counting that many from the right, the entries the proxies themselves
added, so a client cannot choose its own by sending the header. Requests from this computer (loopback) are not
counted: they are its own tests, and a judge running it at home. The everyone limits (quote, agent_run) and the chat
limit protect what real AI services cost, so they apply in sandbox mode only; test mode costs nothing.

The windows are kept in memory, per process: one API process runs the demo. A refusal is recorded in the live feed
as security.rejected once per window and client, by a hash of the address, never the address itself.

Bodies are limited too (MAX_BODY_BYTES, before anything reads them), and every API response carries headers that
keep browsers from guessing types or framing it.
"""

import hashlib
import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from openstall_api.db import session_scope
from openstall_api.events import EventType, record_event
from openstall_api.settings import Settings, get_settings

log = logging.getLogger(__name__)

# The largest request body read: a 16 MB photo or voice note (media.MAX_BYTES), with room for its form.
MAX_BODY_BYTES = 17 * 1024 * 1024
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})
# Never counted: PayPal and Twilio retry what is refused, and every webhook is verified before it is acted on.
UNCOUNTED_PREFIXES = ("/api/webhooks/", "/api/whatsapp/", "/health")
SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
)


@dataclass(frozen=True)
class Limit:
    name: str
    count: int
    seconds: int
    what: str  # what is counted, in words
    everyone: bool = False  # one count for every client together
    sandbox_only: bool = False  # it protects real services' costs, so test mode does not count it


LIMITS: dict[str, Limit] = {
    limit.name: limit
    for limit in (
        Limit("api", 600, 60, "requests to the API"),
        Limit("mcp", 120, 60, "calls to the MCP storefront"),
        Limit("stall_order", 20, 3600, "orders from stall pages"),
        Limit("demo", 30, 3600, "demo runs and resets"),
        Limit("quote", 60, 3600, "quote requests, which start the makers' AI agents", everyone=True, sandbox_only=True),
        Limit("agent_run", 12, 3600, "runs of a buyer's AI agent", everyone=True, sandbox_only=True),
        Limit("chat", 30, 600, "messages from one seller", sandbox_only=True),
    )
}
# Which routes count against which limits, besides "api": (method, path prefix, limit).
ROUTE_LIMITS: tuple[tuple[str, str, str], ...] = (
    ("POST", "/mcp", "mcp"),
    ("POST", "/api/stall-orders", "stall_order"),
    ("POST", "/api/demo/", "demo"),
    ("POST", "/api/guardrails/", "demo"),
)


class TooMany(Exception):
    """A limit was reached: answered with 429 and Retry-After."""

    def __init__(self, limit: Limit, retry_after: int) -> None:
        self.limit = limit
        self.retry_after = retry_after
        per = {60: "a minute", 600: "every 10 minutes", 3600: "an hour"}.get(
            limit.seconds, f"every {limit.seconds} seconds"
        )
        who = "OpenStall takes" if limit.everyone else "each client may make"
        super().__init__(f"Too many {limit.what}: {who} {limit.count} {per}. Try again in {retry_after} seconds.")


class RateLimiter:
    """Sliding windows in memory: the times of each (limit, key)'s recent uses, oldest first."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._noted: dict[tuple[str, str], float] = {}

    def hit(self, limit: Limit, key: str) -> int | None:
        """Count one use. None if it is allowed; else the whole seconds until the next one would be."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault((limit.name, key), deque())
            while hits and hits[0] <= now - limit.seconds:
                hits.popleft()
            if len(hits) >= limit.count:
                if not hits:  # a limit of none: nothing is let through
                    return limit.seconds
                return max(1, int(hits[0] + limit.seconds - now + 0.999))
            hits.append(now)
            if len(self._hits) > 50_000:  # forget clients gone quiet, so memory stays bounded
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - 3600}
            return None

    def first_refusal(self, limit: Limit, key: str) -> bool:
        """Whether this refusal is the first in its window for this client: only that one is recorded."""
        now = self._clock()
        with self._lock:
            last = self._noted.get((limit.name, key))
            if last is not None and last > now - limit.seconds:
                return False
            self._noted[(limit.name, key)] = now
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._noted.clear()


LIMITER = RateLimiter()


def applies(limit: Limit, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not settings.RATE_LIMITS:
        return False
    return not limit.sandbox_only or settings.OPENSTALL_MODE == "sandbox"


def masked(key: str) -> str:
    """A client in the feed: a short hash, never its address or phone number."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]


def note_refusal(limit: Limit, key: str) -> None:
    """Record the first refusal of a window in the live feed."""
    if not LIMITER.first_refusal(limit, key):
        return
    try:
        with session_scope() as session:
            record_event(
                session,
                EventType.SECURITY_REJECTED,
                f"Limit reached: more than {limit.count} {limit.what} "
                f"{'from everyone together' if limit.everyone else f'from client {masked(key)}'} were refused",
                payload={"limit": limit.name, "client": None if limit.everyone else masked(key)},
            )
    except Exception:  # the refusal stands even if the feed cannot be written
        log.exception("A %s limit refusal could not be recorded", limit.name)


def check(name: str, key: str = "everyone", settings: Settings | None = None) -> None:
    """Count one use of a limit from code (a quote request, an agent run, a seller's message). Raises TooMany."""
    limit = LIMITS[name]
    if not applies(limit, settings) or (not limit.everyone and key in LOOPBACK):
        return
    retry = LIMITER.hit(limit, "everyone" if limit.everyone else key)
    if retry is not None:
        note_refusal(limit, "everyone" if limit.everyone else key)
        raise TooMany(limit, retry)


def client_key(scope: Scope, hops: int) -> str:
    """The client's address: the peer's, or behind `hops` proxies the one they added to X-Forwarded-For."""
    if hops > 0:
        for name, value in scope.get("headers") or []:
            if name == b"x-forwarded-for":
                hosts = [host.strip() for host in value.decode("latin-1").split(",") if host.strip()]
                if len(hosts) >= hops:
                    return hosts[-hops]
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


def limits_for(method: str, path: str) -> list[Limit]:
    if path.startswith(UNCOUNTED_PREFIXES):
        return []
    found = [LIMITS["api"]]
    for route_method, prefix, name in ROUTE_LIMITS:
        if method == route_method and (path == prefix or path.startswith(prefix)):
            found.append(LIMITS[name])
    return found


async def _answer(send: Send, status: int, body: dict[str, Any], headers: list[tuple[bytes, bytes]]) -> None:
    raw = json.dumps(body).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(raw)).encode()),
                *SECURITY_HEADERS,
                *headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": raw})


class LimitsMiddleware:
    """Counts each request against its limits, refuses a body over MAX_BODY_BYTES, and adds the security headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length is not None and length.isdigit() and int(length) > MAX_BODY_BYTES:
            await _answer(send, 413, {"detail": "The request is too large."}, [])
            return
        key = client_key(scope, settings.PROXY_HOPS)
        if key not in LOOPBACK:
            for limit in limits_for(scope["method"], scope["path"]):
                if not applies(limit, settings):
                    continue
                retry = LIMITER.hit(limit, key)
                if retry is not None:
                    await run_in_threadpool(note_refusal, limit, key)
                    await _answer(
                        send, 429, {"detail": str(TooMany(limit, retry))}, [(b"retry-after", str(retry).encode())]
                    )
                    return

        received = 0

        async def capped() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    raise ValueError("The request body is larger than MAX_BODY_BYTES")
            return message

        async def secured(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                extra = [(name, value) for name, value in SECURITY_HEADERS if name not in present]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, capped, secured)
