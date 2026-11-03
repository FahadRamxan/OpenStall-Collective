"""The APIMatic PayPal Python SDK, as our gateways use it: one sync client, its retry policy, and one error boundary.

Built with APIMatic's PayPal Context Plugin; paypal-plan.md at the repo root is the contract sheet every SDK fact
here comes from. The SDK covers Orders and Payments. Payouts and webhook verification are not in it, so those stay
on our own PayPalClient (client.py).

- Sync client (PaypalClient): our FastAPI endpoints are plain `def`, run in a thread pool, and the sync client is
  safe to share across threads. It is made once per process and closed with the gateway.
- Retries: the SDK resends only GET requests (get_order), after a retryable status or no answer. It never resends a
  write: when a write gets no answer, the caller reads the order back instead (spec 3.5).
- One resend after a 401 on an operation: the SDK drops its cached token on a 401 but does not resend, and our
  PayPalClient has always fetched a fresh token and tried once more. A 401 means PayPal did nothing, and the
  resend carries the same PayPal-Request-Id. It does not matter how the 401's body reads: PayPal's usual ones do
  not fit the SDK's Error model and come out of the SDK as a decode failure, not ApiError.
- Errors: a refusal becomes PaymentError carrying PayPal's issue code; no answer becomes PaymentUnavailable, with
  outcome_unknown False only when the request provably never reached PayPal.
"""

import json
import logging
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from functools import cache
from importlib.metadata import PackageNotFoundError, distribution
from typing import Any, TypeVar
from urllib.parse import urlsplit

import httpx2
from paypal import PaypalClient
from paypal.core import (
    ApiError,
    ClientCredentials,
    HttpClient,
    HttpRequest,
    HttpResponse,
    Httpx2Client,
    OAuthProviderError,
    RawError,
    RetryOptions,
    UnsetType,
)
from paypal.models import Error

from openstall_paypal.gateway import PaymentError, PaymentUnavailable

log = logging.getLogger(__name__)

T = TypeVar("T")

SDK_DISTRIBUTION = "paypal"  # the APIMatic SDK's distribution name, and its import root
SDK_TIMEOUT = 20.0  # seconds per wait (connect, send, each piece of the answer), as for our PayPalClient
# Only reads are resent: a write that got no answer may have landed, so it is read back, never repeated blindly.
RETRY_POLICY = RetryOptions(max_retries=2, initial_delay=0.5, max_delay=4.0, http_methods_to_retry=frozenset({"GET"}))
TOKEN_PATH = "/v1/oauth2/token"
# The Orders and Payments operations default to "return=minimal": no purchase units, no links. We read both.
REPRESENTATION = "return=representation"
# These transport failures happen before the request leaves: PayPal never saw it.
NEVER_SENT: tuple[type[Exception], ...] = (
    httpx2.ConnectError,
    httpx2.ConnectTimeout,
    httpx2.PoolTimeout,
    httpx2.ProxyError,
)


@dataclass
class Exchange:
    """The last request this thread sent through the SDK: where it went, PayPal's status, and an error body."""

    path: str = ""
    status: int | None = None
    error_body: bytes | None = None  # kept only for an error status, as the SDK reads it; never logged

    @property
    def token_fetch(self) -> bool:
        """The SDK was getting a token, so the operation itself was never sent."""
        return self.path.endswith(TOKEN_PATH)


class _RecordedResponse:
    """An error response passed through unread; when the SDK reads it, the body is kept for the error boundary."""

    def __init__(self, inner: HttpResponse, exchange: Exchange) -> None:
        self._inner = inner
        self._exchange = exchange

    @property
    def url(self) -> str:
        return self._inner.url

    @property
    def status_code(self) -> int:
        return self._inner.status_code

    @property
    def headers(self) -> Mapping[str, str]:
        return self._inner.headers

    def iter_bytes(self, chunk_size: int | None) -> Iterator[bytes]:
        return self._inner.iter_bytes(chunk_size)

    def read(self) -> bytes:
        content = self._inner.read()
        self._exchange.error_body = content
        return content

    def close(self) -> None:
        self._inner.close()


class RecordingTransport:
    """The SDK's transport seam (paypal.core.HttpClient), wrapped around the real one.

    It logs each exchange (method, path, status and PayPal's debug id; never headers or bodies) and remembers, per
    thread, the last request and its status, so the error boundary can tell a token fetch from the operation, and a
    2xx it could not read from a refusal it could not read. It never reads a body itself.
    """

    def __init__(self, inner: HttpClient) -> None:
        self._inner = inner
        self._local = threading.local()

    def last(self) -> Exchange:
        exchange = getattr(self._local, "exchange", None)
        return exchange if isinstance(exchange, Exchange) else Exchange()

    def forget(self) -> None:
        self._local.exchange = Exchange()

    def send(self, request: HttpRequest) -> HttpResponse:
        exchange = Exchange(path=urlsplit(request.url).path)
        self._local.exchange = exchange
        response = self._inner.send(request)  # a TransportError (no answer) goes straight to the SDK's retry loop
        exchange.status = response.status_code
        if response.status_code < 400:
            log.debug("PayPal %s %s answered %s", request.method, exchange.path, response.status_code)
            return response
        log.warning(
            "PayPal %s %s answered %s (debug id %s)",
            request.method,
            exchange.path,
            response.status_code,
            response.headers.get("paypal-debug-id"),
        )
        return _RecordedResponse(response, exchange)

    def close(self) -> None:
        self._inner.close()


class PayPalSdk:
    """The SDK's sync client for one PayPal account, with our transport, timeout and retry policy.

    `transport` replaces the network (tests pass a fake one); by default it is the SDK's own Httpx2Client. The
    base URL is always passed: left out, the SDK silently uses the sandbox.
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        *,
        transport: HttpClient | None = None,
        retry_options: RetryOptions = RETRY_POLICY,
        timeout: float = SDK_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        # With our own transport the client's timeout no longer reaches the wire, so it is set on the transport.
        self.wire = RecordingTransport(transport if transport is not None else Httpx2Client(timeout=timeout))
        self.client = PaypalClient(
            base_url=self.base_url,
            timeout=timeout,
            retry_options=retry_options,
            custom_http_client=self.wire,
            oauth2=ClientCredentials(client_id=client_id, client_secret=client_secret),
        )

    def close(self) -> None:
        """Close the connection pool (it also closes the transport). The client cannot be used again."""
        self.client.close()

    def call(self, operation: Callable[[], T]) -> T:
        """Run one SDK operation and turn every way it can fail into PaymentError or PaymentUnavailable."""
        for attempt in (1, 2):
            self.wire.forget()
            try:
                return operation()
            except ApiError as error:
                exchange = self.wire.last()
                if attempt == 1 and expired_token(exchange) and not isinstance(error.error, OAuthProviderError):
                    continue  # the SDK dropped its token: the resend gets a fresh one, with the same request id
                raise refusal(error.status_code, error.error, exchange) from error
            except NEVER_SENT as error:
                raise PaymentUnavailable(
                    "PAYPAL_UNAVAILABLE", f"PayPal could not be reached ({type(error).__name__})", outcome_unknown=False
                ) from error
            except httpx2.RequestError as error:
                exchange = self.wire.last()
                raise PaymentUnavailable(
                    "PAYPAL_UNAVAILABLE",
                    f"PayPal did not answer ({type(error).__name__})",
                    outcome_unknown=not exchange.token_fetch,
                ) from error
            except ValueError as error:  # pydantic's ValidationError too: an answer the SDK could not read
                exchange = self.wire.last()
                if exchange.status is None:
                    raise  # nothing was sent: a request we built wrong, which is our bug
                if attempt == 1 and expired_token(exchange):
                    # PayPal's usual 401 bodies ({"error": "invalid_token", ...}, or AUTHENTICATION_FAILURE without
                    # a debug_id) do not fit the SDK's Error model, so the 401 arrives as a decode failure.
                    continue
                raise unreadable(exchange) from error
        raise AssertionError("unreachable: the second attempt returns or raises")


def expired_token(exchange: Exchange) -> bool:
    """PayPal answered the operation itself with 401. The SDK has already dropped its token (core/raw_client.py
    invalidates it on every 401, before the error body is decoded), so one resend fetches a fresh one."""
    return exchange.status == 401 and not exchange.token_fetch


def refusal(status: int, error: object, exchange: Exchange) -> PaymentError:
    """PayPal's error answer as ours. A 5xx is no answer at all, so the state must be read back."""
    if isinstance(error, OAuthProviderError):  # our client id or secret: no operation was sent
        return PaymentError(error.error, error.error_description or "PayPal refused our credentials")
    if isinstance(error, Error):
        details = error.details
        issue: str | None = details[0].issue if not isinstance(details, UnsetType) and details else error.name
        message = error.message
    elif isinstance(error, RawError):
        issue, raw_message = issue_of(error.content)
        message = raw_message or f"PayPal answered {status}"
    else:
        issue, message = None, f"PayPal answered {status}"
    if status >= 500:
        return PaymentUnavailable(issue or "PAYPAL_UNAVAILABLE", message, outcome_unknown=not exchange.token_fetch)
    return PaymentError(issue or "PAYPAL_ERROR", message)


def unreadable(exchange: Exchange) -> PaymentError:
    """An answer the SDK could not decode. A 2xx may well have succeeded, so its outcome is unknown; an error
    status is still a refusal (or, for a 5xx, no answer), with the issue read from the body as PayPal sent it."""
    status = exchange.status or 0
    if 200 <= status < 300:
        return PaymentUnavailable(
            "PAYPAL_UNREADABLE",
            f"PayPal answered {status}, but the answer could not be read",
            outcome_unknown=not exchange.token_fetch,
        )
    issue, message = issue_of(exchange.error_body or b"")
    if status >= 500:
        return PaymentUnavailable(
            issue or "PAYPAL_UNAVAILABLE",
            message or f"PayPal answered {status}",
            outcome_unknown=not exchange.token_fetch,
        )
    return PaymentError(issue or "PAYPAL_ERROR", message or f"PayPal answered {status}")


def issue_of(content: bytes) -> tuple[str | None, str | None]:
    """PayPal's issue code and message from an error body that is not the SDK's Error shape: details[0].issue, else
    name, else an OAuth error. (None, None) when the body is not a JSON object."""
    try:
        body: Any = json.loads(content)
    except ValueError:
        return None, None
    if not isinstance(body, dict):
        return None, None
    details = body.get("details")
    detail = details[0] if isinstance(details, list) and details and isinstance(details[0], dict) else {}
    issue = detail.get("issue") or body.get("name") or body.get("error")
    message = body.get("message") or body.get("error_description")
    return (str(issue) if issue else None), (str(message) if message else None)


@dataclass(frozen=True)
class SdkInfo:
    """Which SDK the sandbox gateways call PayPal with, from the installed distribution's own metadata."""

    label: str  # for people, for example "APIMatic PayPal Python SDK 2.29"
    distribution: str  # "paypal"
    version: str  # "2.29"
    commit: str | None  # the SDK repository commit it was installed from, shortened; None if not from git


@cache
def sdk_info() -> SdkInfo | None:
    """The installed SDK's name, version and commit. None if it is not installed."""
    try:
        dist = distribution(SDK_DISTRIBUTION)
    except PackageNotFoundError:
        return None
    meta = dist.metadata
    # "Maintainer: APIMatic", or "Maintainer-email: APIMatic <support@apimatic.io>" when written that way.
    named = meta.get("Maintainer") or meta.get("Author") or ""
    emailed = meta.get("Maintainer-email") or meta.get("Author-email") or ""
    maker = named.strip() or (emailed.split("<")[0].strip().strip('"') if "<" in emailed else "") or "APIMatic"
    commit = None
    try:
        direct_url = json.loads(dist.read_text("direct_url.json") or "{}")
        found = (direct_url.get("vcs_info") or {}).get("commit_id")
        commit = str(found)[:7] if found else None
    except ValueError:
        pass
    version = dist.version
    return SdkInfo(f"{maker} PayPal Python SDK {version}", meta["Name"], version, commit)
