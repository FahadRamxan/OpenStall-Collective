# PayPal integration plan: Orders and Payments on the APIMatic PayPal Python SDK

Written with APIMatic's PayPal Context Plugin (skills `python-integrate-paypal` and `python-getting-started`).
Every SDK fact below was looked up in the SDK map (`sdk-map.md`, `map/operations/orders.md`,
`map/operations/payments.md`) of the source tree at commit `143e57f2a372`, then in the module the map names inside
the installed package (`.venv/Lib/site-packages/paypal`). Nothing here is from memory.

## Scope

Move every Orders and Payments call of `SandboxGateway` (packages/paypal/openstall_paypal/sandbox.py) onto the SDK:

| Gateway method | SDK operation | Route |
| --- | --- | --- |
| `create_checkout` | `client.orders.create_order` | `POST /v2/checkout/orders` |
| `get_order` | `client.orders.get_order` | `GET /v2/checkout/orders/{id}` |
| `reserve` | `client.orders.authorize_order` | `POST /v2/checkout/orders/{id}/authorize` |
| `pay_share` (capture part) | `client.payments.capture_authorized_payment` | `POST /v2/payments/authorizations/{authorization_id}/capture` |
| `release_share` (void) | `client.payments.void_payment` | `POST /v2/payments/authorizations/{authorization_id}/void` |
| `add_tracking` (prompt 33) | `client.orders.create_order_tracking` | `POST /v2/checkout/orders/{id}/track` |

Prompt 33 (each maker's tracking on the PayPal order) adds the last row: once a share is captured, its confirmed
tracking number and courier are attached to that capture on the order. Unlike every other write here, this route
takes **no `PayPal-Request-Id`** (the SDK method has no such parameter, and none of its headers is one), so PayPal
does not dedupe a repeat for us: the order's trackers are read first (`get_order`), the call is claimed like every
other write (`track:{part_id}`), and a tracker already on the order is recorded instead of being sent again.

Not in this SDK (40 operations, 5 controllers; none is Payouts or Notifications), so they stay on our own
`PayPalClient` (client.py): `POST /v1/payments/payouts` and `POST /v1/notifications/verify-webhook-signature`, and
the status page's token check (`PayPalClient.token()`). The gateway holds both clients.

Prompt 51 (payout rails, rails.py) changes nothing on the SDK side: `PayoutsGateway.pay_share` still captures with
`capture_authorized_payment` and releases with `void_payment` as above. It now checks the maker's payout rail and
builds her Payouts item (`rails.payout_item`: PayPal by EMAIL or PAYPAL_ID, or Venmo by USER_HANDLE with a note)
before that capture, so a share no rail can reach is never captured. On the sandbox host a Venmo share is captured
and its payout is simulated, because PayPal's sandbox refuses Venmo payouts; no Payouts call is made for it.

## Repo survey (pattern + exemplar)

- Host is **sync**: FastAPI endpoints are `def`, run in the thread pool (exemplar: apps/api/openstall_api/orders_api.py).
- Adapters are made once per process by the registry and shared across threads (apps/api/openstall_api/adapters.py).
- Services leave committing to the caller; errors are domain exceptions mapped to HTTP in one place
  (apps/api/openstall_api/payments.py, `payment_errors()` in orders_api.py).
- Uniqueness is enforced by the database (unique constraints; `ProcessedWebhook.event_id`, caught as
  `IntegrityError` in apps/api/openstall_api/webhooks.py). Tables in models.py, alembic migrations generated with
  `--autogenerate` (exemplar: migrations/versions/0004_seller_web_chat_id.py); test_db_migrations.py demands the
  migrations match models.py exactly.
- Tests: pytest, bare `assert`, respx for HTTP (packages/paypal/tests/test_sandbox_gateways.py).

## Toolchain and baseline

- pip + venv at `.venv`; run Python as `.venv/Scripts/python`. Install: `pip install -e ".[dev]"`.
- SDK installed: `paypal 2.29` from `git+https://github.com/context-plugins/paypal-python-sdk.git@143e57f2a3729d7df3727386b8c9ddf023d9a5df`
  (direct_url commit `143e57f2a3729d7df3727386b8c9ddf023d9a5df`); import probe printed
  `.venv/Lib/site-packages/paypal`. Its runtime dependency `httpx2 2.16.0` is installed with it.
- Tests: `.venv/Scripts/python -m pytest -q`. Type check: `.venv/Scripts/python -m mypy --strict <files>` (mypy
  installed into the venv; the project had no type checker configured).
- Baseline on the untouched tree: pytest 663 passed, 1 skipped. `mypy --strict packages/paypal/openstall_paypal`:
  1 error (sandbox.py:49, `no-any-return` in `approval_link`), which this change removes.

## Contract sheet

### Client

| Fact | Value |
| --- | --- |
| Sync or async | **Sync**: `PaypalClient` (import from `paypal`). Never `AsyncPaypalClient`; the two do not mix. |
| Construction | keyword-only: `PaypalClient(base_url=..., timeout=..., retry_options=..., custom_http_client=..., oauth2=...)` |
| Where it lives | built once by `make_paypal_gateway` (registry, process-wide), held by the gateway as `gateway.sdk`; `gateway.close()` calls `PaypalClient.close()`; the registry closes its adapters on reset and at app shutdown. Safe to share across threads. |
| Transport | `custom_http_client=RecordingTransport(Httpx2Client(timeout=20.0))`. `Httpx2Client` (from `paypal.core`) takes keyword-only `timeout`, `proxy_url`, `verify`. With a custom transport the client's own `timeout=` no longer reaches the wire, so the timeout is set on `Httpx2Client`. |
| Transport protocol | `HttpClient` (`paypal.core`): `send(request: HttpRequest) -> HttpResponse` and `close()`. `send` returns on the head, never reads the body, raises `TransportError` (`paypal.core`, `.inner_exception`) when no response arrives. Response: `url`, `status_code`, `headers` (lowercase keys), `iter_bytes(chunk_size)`, `read()`, `close()`. Request: `method`, `url`, `headers` (lowercase keys), `body`, `timeout`. |
| base_url | **Always passed**: `settings.PAYPAL_API_BASE` (default `https://api-m.sandbox.paypal.com`). Omitting it silently means `https://api-m.sandbox.paypal.com`. The token URL is `<base_url>/v1/oauth2/token`, derived. |
| Auth | `oauth2=ClientCredentials(client_id=..., client_secret=...)` (`paypal.core`). Always set: omitting it builds a no-auth client silently. Token fetched lazily on the first call, cached on the client, renewed before expiry. |
| Timeout | `20.0` s per wait (the SDK default is `30.0`; 20 matches our `PayPalClient`). It bounds each wait, not the call; **sync code has no whole-call limit** through this SDK. |
| Retry policy | `RetryOptions(max_retries=2, initial_delay=0.5, max_delay=4.0, http_methods_to_retry=frozenset({"GET"}))`; statuses stay at the default `{408, 429, 500, 502, 503, 504}`. So only `get_order` (a read) is ever resent by the SDK, after a retryable status or no response. **No write (POST) is ever resent by the SDK**: the method gate also covers dropped connections and timeouts. Our rule: a write is never repeated blindly; on no answer the caller reads the state back. |
| 401 | The SDK invalidates its cached token on every 401, in the send loop before the error body is decoded (`core/raw_client.py`, `_attempt_send`), and does not resend. We resend **once** ourselves after a 401 on an operation (not on the token fetch), with the same `PayPal-Request-Id`, whatever the 401's body: a 401 means PayPal refused before doing anything, and this keeps `PayPalClient`'s behaviour (one fresh token, one resend after any 401). PayPal's usual 401 bodies (`{"error": "invalid_token", "error_description": ...}` for an expired or revoked token, `AUTHENTICATION_FAILURE` without `debug_id`) do not fit `Error`, so the operation's error mapper (`decode_json[Error]` for 401) raises `ValidationError` rather than `ApiError`; the boundary goes by the recorded status, not by how the body decoded. |
| Idempotency | The SDK adds its own `Idempotency-Key` header (a new uuid4 every call) to non-GET operations; it is not ours and is never relied on. Our keys go in `pay_pal_request_id` (wire header `PayPal-Request-Id`). PayPal keeps keys for 45 days (void_payment docstring). |
| Logging | No SDK hook. `RecordingTransport` logs method, path and status (warning for >= 400, with `paypal-debug-id`), never headers or bodies. |

### Operations (sync parsed spelling; required params positional, the rest keyword-only after `*`, every keyword has a real default, so no defensive `None`s)

| Operation | Positional | Keywords we pass | Returns (parsed) | Error union (`ApiError.error`) |
| --- | --- | --- | --- | --- |
| `orders.create_order` | `body: OrderRequest \| OrderRequestDict` | `pay_pal_request_id="openstall-checkout-{order_id}"`, `prefer="return=representation"` (default `"return=minimal"`) | `Order` | `CreateOrderErrorBody = Error \| RawError`; `Error` from 400, 401, 422 |
| `orders.get_order` | `id_: str` | none (`fields` left default) | `Order` | `GetOrderErrorBody = Error \| RawError`; `Error` from 401, 404 |
| `orders.authorize_order` | `id_: str` | `pay_pal_request_id="openstall-reserve-{paypal_order_id}"`, `prefer="return=representation"`, `body=OrderAuthorizeRequest()` (serializes to `{}`) | `OrderAuthorizeResponse` | `AuthorizeOrderErrorBody = Error \| RawError`; `Error` from 400, 401, 403, 404, 422, 500 |
| `payments.capture_authorized_payment` | `authorization_id: str` | `pay_pal_request_id="openstall-capture-{part_id}"`, `prefer="return=representation"`, `body=CaptureRequest(...)` | `CapturedPayment` | `CaptureAuthorizedPaymentErrorBody = Error \| RawError`; `Error` from 400, 401, 403, 404, 409, 422; 500 is `RawError` |
| `payments.void_payment` | `authorization_id: str` | `pay_pal_request_id="openstall-release-{part_id}"`, `prefer="return=representation"` | `PaymentAuthorization` (200 with representation) | `VoidPaymentErrorBody = Error \| RawError`; `Error` from 401, 403, 404, 409, 422; 500 is `RawError` |
| `orders.create_order_tracking` | `id_: str` (the PayPal order), `body: OrderTrackerRequest \| OrderTrackerRequestDict` | none: its only keywords are `pay_pal_auth_assertion` and `request_options`; **no `pay_pal_request_id`, no `prefer`** | `Order` (PayPal documents 200 "with a JSON response body that shows tracker details") | `CreateOrderTrackingErrorBody = Error \| RawError`; `Error` from 400, 403, 404, 422, 500; anything else (401 included) is `RawError` |

None of the six returns `None` (the 11 `None` operations are all out of scope). Every operation also has
`with_raw_response`; we use the parsed (raising) spelling everywhere.

`prefer` is a header param defaulting to `"return=minimal"`: a minimal answer lacks purchase units and links, so
every call whose body we read passes `"return=representation"`. `void_payment` declares a JSON payload, and its
decoder raises `ValueError` on an empty 2xx body; we pass `return=representation` (200 with the authorization) and
also treat a `204` from PayPal as success, since we read nothing from a void's body.

### Request models (from `paypal.models`; `Optional[T]` is `T | UnsetType`, never `None`; omit a member to leave it out)

| Model | Required | Members we set (Python name = wire name for all of these, no aliases) |
| --- | --- | --- |
| `OrderRequest` | `intent: CheckoutPaymentIntentOrStr`, `purchase_units: list[PurchaseUnitRequest]` | `intent`, `purchase_units`, `payment_source` |
| `PurchaseUnitRequest` | `amount: AmountWithBreakdown` | `reference_id`, `custom_id`, `description`, `amount`, `payee` (multiparty), `items` (payouts) |
| `AmountWithBreakdown` | `currency_code: str`, `value: str` | + `breakdown` (payouts) |
| `AmountBreakdown` | none | `item_total: Money` |
| `Money` | `currency_code: str`, `value: str` | money is a `str` scaled to the currency: `f"{amount:.2f}"` for USD from a `Decimal` |
| `PayeeBase` | none | `merchant_id` or `email_address` |
| `ItemRequest` | `name: str`, `unit_amount: Money`, `quantity: str` | `name`, `sku`, `quantity="1"`, `unit_amount`, `category` |
| `PaymentSource` | none | `paypal: PayPalWallet` |
| `PayPalWallet` | none | `experience_context: PayPalWalletExperienceContext` |
| `PayPalWalletExperienceContext` | none | `brand_name`, `shipping_preference`, `user_action`, `return_url`, `cancel_url`. Members with real defaults are **always sent**: `contact_preference="NO_CONTACT_INFO"`, `landing_page="NO_PREFERENCE"`, `payment_method_preference="UNRESTRICTED"` (and `shipping_preference`/`user_action`, which we set). |
| `OrderAuthorizeRequest` | none | nothing: `{}` |
| `CaptureRequest` | none (`final_capture: bool = False` has a real default, always sent) | `invoice_id`, `final_capture`, and `amount` on the payouts path |
| `OrderTrackerRequest` | `capture_id: str` (`notify_payer: bool = False` has a real default, always sent) | `capture_id`, `tracking_number`, `carrier: ShipmentCarrierOrStr`, `carrier_name_other` (only when `carrier` is `OTHER`), `notify_payer=False` (PayPal's app may still tell the payer; we send no extra email per parcel); `items` left out |

The request body is dumped with `UNSET` stripped (`core/bodies.py`, `strip_unset`); real defaults stay.

### Enums (from `paypal.models.enums`; open: a field typed `…OrStr` also takes or returns a plain `str`)

| Enum | Members we use (wire value = member name) |
| --- | --- |
| `CheckoutPaymentIntent` | `AUTHORIZE` |
| `PayPalWalletContextShippingPreference` | `NO_SHIPPING` |
| `PayPalExperienceUserAction` | `PAY_NOW` |
| `ItemCategory` | `PHYSICAL_GOODS` |
| `OrderStatus` (read) | `CREATED`, `SAVED`, `APPROVED`, `VOIDED`, `COMPLETED`, `PAYER_ACTION_REQUIRED`; an unknown wire value arrives as a `str` and is passed through as-is |
| `ShipmentCarrier` (`paypal.models.enums.shipment_carrier`, 4,256 lines) | the demo's couriers, each checked to exist: `TCS` ("TCS courier"), `INDIA_POST`, `MEX_ESTAFETA` ("Estafeta"), `ROYAL_MAIL`, `PARCELFORCE`, `USPS`, `UPS`, `FEDEX`, `DHL`, `BLUEDART`, `IND_DELHIVERY`, `DTDC_IN`, `CORREOS_DE_MEXICO`; anything else is `OTHER` with the name in `carrier_name_other` (Leopards has no member; `OTHER` with "Leopards Courier" was accepted on the sandbox, docs/day-one-checks.md) |

### Response members we depend on (all `Optional` = may be `UNSET`; guard each)

| Model | Members read | Guard |
| --- | --- | --- |
| `Order` (create) | `id: Optional[str]`, `links: Optional[list[LinkDescription]]` | no `id` after a create: outcome unknown (`PaymentUnavailable`); no payer-action/approve link: `PaymentError("NO_APPROVAL_LINK")` |
| `LinkDescription` | `href: str`, `rel: str` (**required**: the one 2xx shape here with required members, so a link without them fails to decode) | |
| `Order` (get) | `status: Optional[OrderStatusOrStr]`, `purchase_units` | no `status`: outcome unknown (a read; `PaymentUnavailable`) |
| `OrderAuthorizeResponse` | `purchase_units: Optional[list[PurchaseUnit]]` | no authorization: `PaymentError("NO_AUTHORIZATION")` (as today) |
| `PurchaseUnit` | `reference_id: Optional[str]` (`"default"` when unset, as today), `payments: Optional[PaymentCollection]` | |
| `PaymentCollection` | `authorizations: Optional[list[AuthorizationWithAdditionalData]]` | |
| `AuthorizationWithAdditionalData` | `id: Optional[str]` | |
| `CapturedPayment` | `id: Optional[str]` | no `id` after a capture: outcome unknown (`PaymentUnavailable`) |
| `PurchaseUnit` (tracking) | `shipping: Optional[ShippingWithTrackingDetails]` | |
| `ShippingWithTrackingDetails` | `trackers: Optional[list[OrderTrackerResponse]]` | |
| `OrderTrackerResponse` | `id: Optional[str]` (documented only as "The tracker id."), `status: Optional[OrderTrackerStatusOrStr]` (`SHIPPED`, `CANCELLED`); it has **no** tracking-number or capture-id member | after a track call, ours is the tracker whose `id` contains our tracking number, else the one id that was not on the order when we read it just before; neither: outcome unknown (`PaymentUnavailable`), read back next time |
| `Error` (`paypal.models`) | `name: str`, `message: str`, `debug_id: str` (all required), `details: Optional[list[ErrorDetails]]` | |
| `ErrorDetails` | `issue: str` (required) | |

### Failures and our error boundary (one method, `PayPalSdk.call`, in sdk.py)

`PaymentError(issue, message)` = PayPal refused; `PaymentUnavailable(issue, message, outcome_unknown=...)` = no
answer; the caller reads the state back. `outcome_unknown` is new: `False` when the request provably never reached
PayPal (so a claim is released), `True` when it may have landed (the claim is marked `unknown`, and only a repeat with the same `PayPal-Request-Id` takes it over at once).

| What happens | How it reaches us | Becomes |
| --- | --- | --- |
| PayPal refuses (4xx) with an `Error` body | `ApiError`, `.error` is `Error` | `PaymentError(details[0].issue else name)` |
| 4xx with a body that is not `Error` | `ApiError` with `RawError`, or `ValueError`/`ValidationError` from the error mapper (`decode_json[Error]`, e.g. no `debug_id`) | `PaymentError(issue from the recorded JSON body: details[0].issue, else name, else error; else "PAYPAL_ERROR")` |
| PayPal 5xx | `ApiError` (`Error` or `RawError`), or a decode failure on it | `PaymentUnavailable(issue or "PAYPAL_UNAVAILABLE", outcome_unknown=True)` |
| 401 on an operation | `ApiError` 401 when the body fits `Error`; otherwise (`invalid_token`, no `debug_id`) a `ValidationError` from the error mapper, recorded as status 401 by `RecordingTransport` | resend once (the SDK dropped its token); a second 401 is `PaymentError(issue)`, the issue read as in the row above (`invalid_token`, `AUTHENTICATION_FAILURE`) |
| Token fetch refused | `ApiError` whose `.error` is `OAuthProviderError` (`error: str`, `error_description: str \| None`, `error_uri`) or `RawError`, raised out of the operation call, in both response modes | `PaymentError(error, error_description)`: our credentials; nothing was sent |
| Token fetch got no answer / 5xx | httpx2 exception or `ApiError` from the token URL | `PaymentUnavailable(outcome_unknown=False)`: the operation was never sent |
| Never sent | `httpx2.ConnectError`, `ConnectTimeout`, `PoolTimeout`, `ProxyError` (unwrapped from `TransportError`) | `PaymentUnavailable("PAYPAL_UNAVAILABLE", outcome_unknown=False)` |
| Sent, no answer | any other `httpx2.RequestError` (`ReadTimeout`, `WriteTimeout`, `RemoteProtocolError`, ...) | `PaymentUnavailable("PAYPAL_UNAVAILABLE", outcome_unknown=True)` |
| 2xx body that does not decode | `ValueError` / `pydantic.ValidationError` (both response modes) | `PaymentUnavailable("PAYPAL_UNREADABLE", outcome_unknown=True)`; for `void_payment` a 204 is success |
| A model we build is invalid | `ValidationError` before sending | our bug: propagates unchanged |

Which request failed, its status and an error body are taken from `RecordingTransport`, a thread-local record of
the last exchange on this thread (path, status, and an error body as the SDK reads it). It never reads a body itself.

### What limits a whole call

Nothing, in sync code: `timeout=20.0` limits each wait. A read can take up to 3 attempts (2 retries, waits of
0.5 s and 1 s plus jitter, capped at 4 s). The claim stale window (below) is longer than a call normally takes, but
not a hard bound: a server that trickles its answer could hold a call past it.

## DUPLICATE CLAIMS

Store: a new table `paypal_claims` in our database (models.py `PayPalClaim`, migration 0005), primary key `key`
(`"checkout:{order_id}"`, `"reserve:{order_id}"`, `"capture:{part_id}"`, `"release:{part_id}"`), beside it the
`PayPal-Request-Id` we send, `state` (`pending`, `done` or `unknown`), a `holder` token, `result` (PayPal's id) and
timestamps. Order: **claim, SDK call, record the result**. A second insert of a key fails on the primary key
(`IntegrityError`), or, while the first insert is uncommitted, waits for its transaction and then fails or goes
ahead; either way two requests are never calling PayPal for one key at once.

**Where the claim row is written:**

- **Postgres (the hosted demo): inside the caller's own transaction**, in a savepoint, so a payment request uses
  one pooled connection, not two. (With a claim on a second connection, about 15 concurrent payment requests each
  held one connection, locked on its order's row, and waited for a second: the default pool of 5 + 10 ran dry and
  they all failed after its 30 s timeout.) It is just as exclusive: every flow first locks the order's row
  (`payments.load_order`, `SELECT ... FOR UPDATE`), so a second request for the same order waits there and then
  finds the stored result; and the uncommitted primary key blocks any other insert of the key until the
  transaction ends. `done` is written in the same commit as our rows. A request that rolls back, or whose process
  dies, takes its claim (and its row lock) with it, and the next try carries the same `PayPal-Request-Id`.
- **SQLite (local runs, tests): on a connection of its own**, inserted and committed before the SDK call, since
  SQLite takes no row locks and the claim is the only guard. When the caller's transaction has already written, a
  claim on another connection would wait for it while nobody else can write; the claim then joins the caller's
  transaction too (a savepoint), which is just as exclusive, and is saved or undone with it.

**How a claim on its own connection ends:** `done` with PayPal's id once the caller commits its rows (a session
`after_commit` / `after_transaction_end` hook), so `done` always means our rows have it. Released (deleted) on a
refusal (`PaymentError`, or `PaymentUnavailable` with `outcome_unknown=False`). **`unknown`** when the holder is
finished without PayPal's answer saved: no answer (`outcome_unknown=True`), or the caller rolled back. A failure to
write any of these is logged, never raised: after a commit it would turn saved rows into a 500.

**Takeover:** `pending` means a holder is calling PayPal now and refuses the second request (`ClaimHeld`, 409,
"... by another request"). An `unknown` claim is taken over at once by a request with the **same**
`PayPal-Request-Id`: PayPal dedupes on it (6 hours for Orders, 45 days for Payments), so the repeat is answered
with the first result if the first landed, as a repeat was before claims existed; a different request id waits
until it is stale (`ClaimHeld`, 409, "PayPal did not answer an earlier attempt at this. Try again after HH:MM
UTC."). A `done` claim is taken over by the next caller (payments.py returns the stored result before it gets that
far, so that is a deliberate repeat such as pressing Approve again, which PayPal answers with the same order).
**Stale rule:** a `pending` claim older than `STALE_AFTER` (2 minutes) was left by a process that stopped mid-call
and is taken over, with the same `PayPal-Request-Id`. Every takeover is a compare-and-set on the holder token, so
two takers cannot both win. `ClaimHeld` is answered with 409 by `orders_api.payment_errors`.

| Write | Where the claim is stored | What rejects the second one | Where that rejection is caught | Where in the code |
| --- | --- | --- | --- | --- |
| Checkout (`create_order`) | `paypal_claims` row `checkout:{order_id}` | the primary key on `paypal_claims.key` (INSERT fails with `IntegrityError`), or the holder compare-and-set on a takeover; on Postgres first the order's row lock (`load_order`) | `except IntegrityError` in `claims.take_claim`, raised as `ClaimHeld` | `claims.take_claim` (via `claims.paypal_claim` in `payments.start_checkout`), then `SandboxGateway.create_checkout` |
| Reserve (`authorize_order`) | `paypal_claims` row `reserve:{order_id}` | the primary key on `paypal_claims.key`, or the holder compare-and-set; on Postgres first the order's row lock | `except IntegrityError` in `claims.take_claim`, raised as `ClaimHeld` | `claims.take_claim` (via `claims.paypal_claim` in `payments.reserve_order`), then `SandboxGateway.reserve` |
| Pay a share (`capture_authorized_payment`) | `paypal_claims` row `capture:{part_id}` | the primary key on `paypal_claims.key`, or the holder compare-and-set; on Postgres first the order's row lock (`load_part`) | `except IntegrityError` in `claims.take_claim`, raised as `ClaimHeld` | `claims.take_claim` (via `claims.paypal_claim` in `payments.pay_share`), then `SandboxGateway.capture` |
| Release a share (`void_payment`) | `paypal_claims` row `release:{part_id}` | the primary key on `paypal_claims.key`, or the holder compare-and-set; on Postgres first the order's row lock (`load_part`) | `except IntegrityError` in `claims.take_claim`, raised as `ClaimHeld` | `claims.take_claim` (via `claims.paypal_claim` in `payments.release_share`), then `SandboxGateway.void` |
| Tracking on a share's capture (`create_order_tracking`) | `paypal_claims` row `track:{part_id}`, request id `openstall-track-{part_id}` (stored for the takeover rule only: this route sends no `PayPal-Request-Id`) | the primary key on `paypal_claims.key`, or the holder compare-and-set; on Postgres first the order's row lock (`load_part`); and before any send, the order's trackers read back, so a tracker that already landed is recorded, never sent twice | `except IntegrityError` in `claims.take_claim`, raised as `ClaimHeld` | `payments.track_share` (reads `gateway.get_order(...).trackers`, then `claims.paypal_claim`), then `SandboxGateway.add_tracking` |

## Assumptions & Blockers

- **Done November 3: the real-sandbox smoke.** With the sandbox app's keys in `.env`, OpenStall's own Approve
  flow ran `create_order`, `get_order` and `authorize_order` through this SDK against the real sandbox (200, 200,
  201; the buyer approved in a browser), and a scratch script then ran `capture_authorized_payment` (a partial
  capture, `final_capture` false) and `void_payment` through the gateway on that authorization. Sending the same
  capture again with the same `PayPal-Request-Id` returned the same capture id. No operation answered 403, and
  PayPal accepted the experience context's three defaults below. Evidence: docs/day-one-checks.md, "Sandbox proof".
- Minor: the experience context now also sends PayPal's documented defaults `contact_preference=NO_CONTACT_INFO`,
  `landing_page=NO_PREFERENCE`, `payment_method_preference=UNRESTRICTED` (real defaults on the SDK model).
- Minor: on SQLite, a concurrent duplicate of a write (two tabs on the return page at the same instant) now gets
  409 for the second request instead of both calling PayPal. On Postgres the second waits on the order's row lock,
  as before, and then gets the stored result. A repeat once the first has finished returns the stored result.
- After an unknown outcome (no answer to a write), a repeat goes ahead at once with the same `PayPal-Request-Id`,
  as before this change; it is not refused.
- **Tracking (prompt 33), proven by hand, not yet through the SDK.** The sandbox proof attached tracking to two
  captures with `POST /v2/checkout/orders/{id}/track` (carrier `DHL`, and `OTHER` with `carrier_name_other`), but
  did not record the answer, and the SDK documents the tracker `id` only as "The tracker id." So, until the hosted
  demo's first real tracking runs, two things are assumed: the answer lists the order's trackers (its decoder is
  `Order`), and after a call that got **no** answer, our tracker can be recognised on the order by an `id` that
  contains our tracking number. The first is not relied on for safety: an answer without a new tracker is read as
  unknown, never as success. If the second is wrong, a retry after a lost answer could add the tracking twice
  (PayPal does not dedupe this route); check the ids on the first real run and record them here.
- Not run: the claims tests on Postgres. There is no Postgres server on the development machine; the Postgres path
  is covered by a test that runs it on SQLite and counts one pooled connection per request.

## REQUIRED READING

- Client construction, the shared sync client, `close()`, the custom transport and its timeout: MUST load `python-client-initialization`.
- `oauth2=` credentials, the lazy token, the `OAuthProviderError` failure: MUST load `python-authentication`.
- Positional vs keyword-only parameters, `prefer` defaults, the parsed response mode: MUST load `python-calling-endpoints`.
- `UNSET`, open enums, required members, real defaults that are always sent, money as `str`: MUST load `python-models`.
- The error boundary, decode failures, never-sent vs unknown transport failures: MUST load `python-error-handling`.
- The retry policy (GET only), timeouts, the logging transport, the duplicate-claim rule: MUST load `python-configuration-resilience`.
- The fake transport seam, the token request first, the four failure kinds: MUST load `python-testing`.
