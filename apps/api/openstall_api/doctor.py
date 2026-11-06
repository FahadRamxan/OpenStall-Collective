"""The PayPal doctor (prompt 53): is this deployment ready to hold a buyer's money and pay makers through PayPal?

`GET /api/paypal/doctor`, the /status page and `scripts/doctor.py` run the same checks, each ok, warn, fail or skip,
with what to do in words. It names a missing key, never a key's value. In sandbox mode it asks PayPal for a token and
reads the registered webhook back; nothing else is sent, and nothing changes at PayPal.

The report also carries the PayPal products table (`openstall_paypal.products`) and the APIMatic cross-check
(`openstall_paypal.crosscheck`): paypal-plan.md, the gateway's calls and the installed SDK agree.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from openstall_api.adapters import AdapterRegistry, get_registry
from openstall_api.settings import Mode
from openstall_api.webhooks import SUBSCRIBED_EVENTS
from openstall_paypal import PaymentError, PayPalError, SandboxGateway, sandbox_host
from openstall_paypal.crosscheck import cross_check
from openstall_paypal.products import PRODUCTS, STATE_WORDS, ProductState

router = APIRouter(prefix="/api/paypal", tags=["paypal"])

CheckStatus = Literal["ok", "warn", "fail", "skip"]

# The seeded makers paid by PayPal Payouts in sandbox mode, and the setting that names each one's sandbox account.
SANDBOX_PAYEES = (
    ("Priya", "PAYPAL_SANDBOX_PAYEE_PRIYA"),
    ("Lucía", "PAYPAL_SANDBOX_PAYEE_LUCIA"),
    ("Noor", "PAYPAL_SANDBOX_PAYEE_NOOR"),
)


class Check(BaseModel):
    name: str
    status: CheckStatus
    detail: str


class ProductOut(BaseModel):
    key: str
    name: str
    used_for: str
    calls: list[str]
    code: str
    state: ProductState
    state_words: str
    evidence: str
    prompts: str


class DoctorReport(BaseModel):
    mode: Mode
    healthy: bool  # no check failed
    checks: list[Check]
    products: list[ProductOut]


def products() -> list[ProductOut]:
    return [
        ProductOut(
            key=product.key,
            name=product.name,
            used_for=product.used_for,
            calls=list(product.calls),
            code=product.code,
            state=product.state,
            state_words=STATE_WORDS[product.state],
            evidence=product.evidence,
            prompts=product.prompts,
        )
        for product in PRODUCTS
    ]


def _host(registry: AdapterRegistry) -> Check:
    settings = registry.settings
    if settings.OPENSTALL_MODE == "fake":
        return Check(
            name="Where the money goes",
            status="ok",
            detail="Test mode: a simulated PayPal. Nothing reaches PayPal and no money moves.",
        )
    if sandbox_host(settings.PAYPAL_API_BASE):
        return Check(
            name="Where the money goes",
            status="ok",
            detail=f"PayPal's sandbox ({settings.PAYPAL_API_BASE}): no real money moves.",
        )
    return Check(
        name="Where the money goes",
        status="warn",
        detail=f"{settings.PAYPAL_API_BASE} is PayPal's live host, where money is real. Hyperwallet is only "
        "simulated, so a maker in Pakistan has no payout rail there.",
    )


def _token(registry: AdapterRegistry) -> tuple[Check, SandboxGateway | None]:
    if registry.settings.OPENSTALL_MODE == "fake":
        return Check(name="PayPal keys and token", status="skip", detail="Test mode needs no PayPal keys."), None
    missing = registry.missing_keys("payment_gateway")
    if missing:
        return (
            Check(name="PayPal keys and token", status="fail", detail=f"Set {' and '.join(missing)} in .env."),
            None,
        )
    try:
        gateway = registry.payment_gateway
        assert isinstance(gateway, SandboxGateway)
        gateway.client.token()
    except Exception as error:  # the report must come back whatever PayPal says
        return Check(name="PayPal keys and token", status="fail", detail=f"PayPal gave no token: {error}"), None
    return (
        Check(name="PayPal keys and token", status="ok", detail="PayPal gave a token for the app's client id."),
        gateway,
    )


def _webhook(registry: AdapterRegistry, gateway: SandboxGateway | None) -> Check:
    settings = registry.settings
    name = "PayPal webhook"
    if settings.OPENSTALL_MODE == "fake":
        return Check(
            name=name, status="skip", detail="Test mode signs its own events and sends them through the same checks."
        )
    webhook_id = settings.PAYPAL_WEBHOOK_ID
    if not webhook_id:
        return Check(
            name=name,
            status="warn",
            detail="PAYPAL_WEBHOOK_ID is not set, so every PayPal event is refused and the receipt keeps waiting for "
            "PayPal. Register the webhook once the demo is hosted (docs/day-one-checks.md).",
        )
    if gateway is None:
        return Check(name=name, status="skip", detail="Needs a PayPal token first.")
    try:
        hook = gateway.client.get(f"/v1/notifications/webhooks/{webhook_id}")
    except (PayPalError, PaymentError) as error:  # our REST client's errors, and the gateway's
        return Check(name=name, status="fail", detail=f"PayPal could not show webhook {webhook_id}: {error}")
    subscribed = {str(kind.get("name")) for kind in hook.get("event_types") or [] if isinstance(kind, dict)}
    missing = [] if "*" in subscribed else [event for event in SUBSCRIBED_EVENTS if event not in subscribed]
    expected = f"{settings.PUBLIC_BASE_URL}/api/webhooks/paypal"
    problems = []
    if hook.get("url") != expected:
        problems.append(f"it sends events to {hook.get('url')}, not {expected}")
    if missing:
        problems.append(f"it is not subscribed to {', '.join(missing)}")
    if problems:
        return Check(name=name, status="warn", detail=f"Webhook {webhook_id}: {'; '.join(problems)}.")
    return Check(
        name=name,
        status="ok",
        detail=f"Webhook {webhook_id} sends every event OpenStall needs ({len(SUBSCRIBED_EVENTS)}) to {expected}.",
    )


def _payees(registry: AdapterRegistry) -> Check:
    settings = registry.settings
    name = "Makers' payout accounts"
    if settings.OPENSTALL_MODE == "fake":
        return Check(name=name, status="ok", detail="Test mode simulates every maker's payout, and says so.")
    missing = [(maker, key) for maker, key in SANDBOX_PAYEES if not getattr(settings, key)]
    simulated = "Grace's Venmo payout and Amina's Hyperwallet payout are simulated, and say so."
    if not missing:
        return Check(name=name, status="ok", detail=f"Priya, Lucía and Noor have sandbox PayPal accounts. {simulated}")
    return Check(
        name=name,
        status="warn",
        detail=f"No sandbox PayPal account for {', '.join(maker for maker, _ in missing)}, so their shares are not "
        f"captured in sandbox mode: set {', '.join(key for _, key in missing)}. {simulated}",
    )


def checks(registry: AdapterRegistry) -> list[Check]:
    token, gateway = _token(registry)
    found = [_host(registry), token, _webhook(registry, gateway), _payees(registry)]
    found += [
        Check(
            name=f"APIMatic cross-check: {finding.check}", status="ok" if finding.ok else "fail", detail=finding.detail
        )
        for finding in cross_check()
    ]
    return found


def doctor_report(registry: AdapterRegistry) -> DoctorReport:
    found = checks(registry)
    return DoctorReport(
        mode=registry.settings.OPENSTALL_MODE,
        healthy=all(check.status != "fail" for check in found),
        checks=found,
        products=products(),
    )


@router.get("/doctor")
def read_doctor(registry: Annotated[AdapterRegistry, Depends(get_registry)], response: Response) -> DoctorReport:
    response.headers["Cache-Control"] = "no-store"  # always current, as /api/status
    return doctor_report(registry)
