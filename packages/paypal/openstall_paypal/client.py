"""A small PayPal REST client for the sandbox: OAuth token caching, idempotency keys, and typed errors.

Every write carries a PayPal-Request-Id, so PayPal treats a repeat of it as the same request. Writes are never
retried automatically: when PayPal cannot be reached, the caller reads the state back instead (spec 3.5: never retry
a capture blindly). The one retry is getting a fresh token after a 401.
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

log = logging.getLogger(__name__)

TOKEN_MARGIN_SECONDS = 60  # renew the token this long before PayPal says it expires


class PayPalError(Exception):
    """PayPal refused a request. `issue` is PayPal's code (such as ORDER_NOT_APPROVED); `debug_id` is for support."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        issue: str | None = None,
        debug_id: str | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.issue = issue
        self.debug_id = debug_id
        self.details = details or []


class PayPalAuthError(PayPalError):
    """The client id or secret is wrong, or the token was refused."""


class PayPalValidationError(PayPalError):
    """PayPal understood the request and refused it (400 or 422), with details."""


class PayPalNotFound(PayPalError):
    """The order, authorization or payout does not exist."""


class PayPalUnavailable(PayPalError):
    """PayPal did not answer properly (network error or 5xx). The request may or may not have taken effect."""


class PayPalClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        secret: str,
        *,
        http: httpx.Client | None = None,
        timeout: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._secret = secret
        self._http = http or httpx.Client(timeout=timeout)
        self._clock = clock
        self._token: str | None = None
        self._token_expires = 0.0
        self._lock = threading.Lock()

    def close(self) -> None:
        """Close the connection pool."""
        self._http.close()

    def token(self, *, refresh: bool = False) -> str:
        """An OAuth access token, cached until shortly before it expires."""
        with self._lock:
            if refresh or self._token is None or self._clock() >= self._token_expires:
                try:
                    response = self._http.post(
                        f"{self.base_url}/v1/oauth2/token",
                        data={"grant_type": "client_credentials"},
                        auth=(self._client_id, self._secret),
                        headers={"Accept": "application/json"},
                    )
                except httpx.TransportError as error:
                    raise PayPalUnavailable(f"PayPal could not be reached ({type(error).__name__})") from error
                if response.status_code >= 400:
                    raise _error(response, auth=True)
                body = response.json()
                self._token = body["access_token"]
                self._token_expires = self._clock() + max(0, int(body.get("expires_in", 0)) - TOKEN_MARGIN_SECONDS)
            return self._token

    def get(self, path: str) -> dict[str, Any]:
        return self._send("GET", path, None, None)

    def post(self, path: str, body: dict[str, Any] | None, *, idempotency_key: str) -> dict[str, Any]:
        return self._send("POST", path, body, idempotency_key)

    def post_raw(self, path: str, content: bytes) -> dict[str, Any]:
        """POST a JSON body exactly as given. For checks that change nothing, so no idempotency key."""
        return self._send("POST", path, None, None, content=content)

    def _send(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        idempotency_key: str | None,
        *,
        content: bytes | None = None,
        renewed: bool = False,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.token(refresh=renewed)}",
            "Accept": "application/json",
            "Prefer": "return=representation",
        }
        if idempotency_key is not None:
            headers["PayPal-Request-Id"] = idempotency_key
        if content is not None:
            headers["Content-Type"] = "application/json"
        try:
            if content is not None:
                response = self._http.request(method, f"{self.base_url}{path}", content=content, headers=headers)
            else:
                response = self._http.request(method, f"{self.base_url}{path}", json=body, headers=headers)
        except httpx.TransportError as error:
            raise PayPalUnavailable(f"PayPal could not be reached ({type(error).__name__})") from error
        if response.status_code == 401 and not renewed:
            return self._send(method, path, body, idempotency_key, content=content, renewed=True)
        if response.status_code >= 400:
            raise _error(response)
        return response.json() if response.content else {}


def _error(response: httpx.Response, *, auth: bool = False) -> PayPalError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    debug_id = response.headers.get("Paypal-Debug-Id") or body.get("debug_id")
    issue = body.get("name") or body.get("error")
    details = body.get("details") or []
    detail_issue = details[0].get("issue") if details and isinstance(details[0], dict) else None
    message = body.get("message") or body.get("error_description") or f"PayPal answered {response.status_code}"
    log.warning(
        "PayPal %s %s answered %s %s (debug id %s)",
        response.request.method,
        response.request.url.path,
        response.status_code,
        detail_issue or issue,
        debug_id,
    )
    kind: type[PayPalError]
    if auth or response.status_code in (401, 403):
        kind = PayPalAuthError
    elif response.status_code in (400, 422):
        kind = PayPalValidationError
    elif response.status_code == 404:
        kind = PayPalNotFound
    elif response.status_code >= 500:
        kind = PayPalUnavailable
    else:
        kind = PayPalError
    return kind(message, status=response.status_code, issue=detail_issue or issue, debug_id=debug_id, details=details)
