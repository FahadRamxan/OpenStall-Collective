"""The day-one sandbox proof (prompt 08): the payouts path, step by step, on PayPal's real sandbox, through the app's
own gateway code (packages/paypal: APIMatic's PayPal SDK for Orders and Payments, our own client for Payouts).

    python scripts/sandbox_proof.py                    the whole proof; you approve two orders at PayPal
    python scripts/sandbox_proof.py --payee EMAIL      also a $1.00 payout to this sandbox PayPal account
    python scripts/sandbox_proof.py --plan             the steps and what each proves; nothing is sent

It needs PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET (in .env) and refuses any host but PayPal's sandbox. You approve
each order at PayPal yourself, as the sandbox buyer, in your own browser: the script never asks for a login and never
types one. Each step's result prints as a row of the table in docs/day-one-checks.md ("Sandbox proof").

1. One order with intent AUTHORIZE and one purchase unit, the story's four makers as items, $815.00.
2. You approve it at PayPal; the script reads the order back until PayPal says APPROVED.
3. Authorize: the whole $815.00 is held, and nothing is taken.
4. A partial capture of Amina's $216.00, final_capture false, and her tracking on it (DHL).
5. A second partial capture, Priya's $176.00, and her tracking (carrier OTHER, "Leopards Courier").
6. Lucía's $220.00 dropped: never captured.
7. The final capture, Grace's $203.00, final_capture true: the authorization closes. The buyer paid $595.00.
8. The same capture sent again with its PayPal-Request-Id: PayPal answers with the first capture, not a second.
9. A second order, approved by you, authorized, one share captured, and the rest voided.
10. With --payee, a $1.00 payout to that PayPal account; and a $1.00 payout to a Venmo handle, which the sandbox
    refuses ("Recipient wallet not supported in sandbox").
"""

import argparse
import hashlib
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from paypal.models import CaptureRequest

from openstall_api.settings import Settings, get_settings
from openstall_paypal import (
    CheckoutPart,
    CheckoutRequest,
    PaymentError,
    PayoutsGateway,
    PayPalError,
    Share,
    Tracking,
    sandbox_host,
)
from openstall_paypal.gateway import WHOLE_ORDER
from openstall_paypal.sandbox import money

# The story's order: each maker's share, in the order the proof captures them.
SHARES = (
    ("amina", "op_001", Decimal("216.00"), "12 × Hand-embroidered cushion cover, Amina"),
    ("priya", "op_002", Decimal("176.00"), "11 × Mirror-work embroidered cushion cover, Priya"),
    ("lucia", "op_003", Decimal("220.00"), "10 × Hand-woven cushion cover, Lucía"),
    ("grace", "op_004", Decimal("203.00"), "7 × Quilted cushion cover, Grace"),
)
RETURN_URL = "https://example.com/openstall-sandbox-proof/approved"  # PayPal sends the buyer here; nothing listens
CANCEL_URL = "https://example.com/openstall-sandbox-proof/cancelled"
APPROVAL_TIMEOUT = 15 * 60  # seconds a person has to approve each order
POLL_EVERY = 3.0
VENMO_HANDLE = "openstall-sandbox-proof"


@dataclass
class Proof:
    """The table being written: each check and what PayPal answered."""

    rows: list[tuple[str, str]] = field(default_factory=list)
    out: Callable[[str], None] = print

    def record(self, check: str, result: str) -> None:
        self.rows.append((check, result))
        self.out(f"  {check}: {result}")

    def table(self) -> str:
        return "\n".join(["| Check | Result |", "|---|---|", *(f"| {check} | {result} |" for check, result in self.rows)])


def plan() -> str:
    """The steps, from this file's own description, for --plan."""
    lines = (__doc__ or "").split("\n\n", 3)[-1].strip().splitlines()
    return "\n".join(line for line in lines if line[:1].isdigit() or line.startswith("    "))


def checkout(run: str, order: str) -> CheckoutRequest:
    parts = tuple(CheckoutPart(reference, amount, description) for _, reference, amount, description in SHARES)
    return CheckoutRequest(f"proof-{run}-{order}", parts, RETURN_URL, CANCEL_URL)


def wait_for_approval(
    gateway: PayoutsGateway,
    paypal_order_id: str,
    link: str,
    proof: Proof,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """You approve at PayPal, as the sandbox buyer, in your browser; the script only reads the order back."""
    proof.out(f"\n  Open this link and approve as the sandbox buyer (the script waits {APPROVAL_TIMEOUT // 60} minutes):")
    proof.out(f"  {link}\n")
    deadline = clock() + APPROVAL_TIMEOUT
    while True:
        status = gateway.get_order(paypal_order_id).status
        if status == "APPROVED":
            return
        if status not in ("CREATED", "PAYER_ACTION_REQUIRED"):
            raise SystemExit(f"PayPal order {paypal_order_id} is {status}, not approved: the proof stops here.")
        if clock() >= deadline:
            raise SystemExit(f"Order {paypal_order_id} was not approved within {APPROVAL_TIMEOUT // 60} minutes.")
        sleep(POLL_EVERY)


def share(run: str, maker: str, hold: str, amount: Decimal, *, last: bool) -> Share:
    # Our part ids are the idempotency keys PayPal keeps for 45 days, so each run's are its own.
    return Share(part_id=f"proof-{run}-{maker}", hold_id=hold, amount_usd=amount, last=last)


def capture(gateway: PayoutsGateway, piece: Share) -> str:
    request = CaptureRequest(amount=money(piece.amount_usd), invoice_id=piece.part_id, final_capture=piece.last)
    return gateway.capture(piece, request)


def track(
    gateway: PayoutsGateway, paypal_order_id: str, piece: Share, capture_id: str, carrier: str, name: str | None
) -> str:
    known = gateway.get_order(paypal_order_id).trackers
    number = f"PROOF{int(hashlib.sha256(piece.part_id.encode()).hexdigest(), 16) % 10**10:010d}"
    return gateway.add_tracking(Tracking(piece.part_id, paypal_order_id, capture_id, number, carrier, name, known))


def payout(gateway: PayoutsGateway, run: str, key: str, item: dict[str, object]) -> str:
    """One payout from the platform's balance, on our own client (APIMatic's SDK has no Payouts)."""
    header = {"sender_batch_id": f"proof-{run}-{key}", "email_subject": "OpenStall sandbox proof"}
    answer = gateway.client.post(
        "/v1/payments/payouts", {"sender_batch_header": header, "items": [item]}, idempotency_key=f"proof-{run}-{key}"
    )
    batch = answer.get("batch_header") or {}
    return f"batch {batch.get('payout_batch_id')}, {batch.get('batch_status')}"


def dollar(receiver: dict[str, str], run: str, key: str) -> dict[str, object]:
    return {**receiver, "amount": {"currency": "USD", "value": "1.00"}, "sender_item_id": f"proof-{run}-{key}"}


def run_proof(
    gateway: PayoutsGateway,
    proof: Proof,
    payee: str | None = None,
    run: str | None = None,
    approve: Callable[[PayoutsGateway, str, str, Proof], None] = wait_for_approval,
) -> Proof:
    run = run or uuid.uuid4().hex[:8]
    total = sum(amount for _, _, amount, _ in SHARES)

    proof.out("Order 1: the story's order, captured share by share")
    first = gateway.create_checkout(checkout(run, "1"))
    proof.record(
        f"Order with intent AUTHORIZE and one purchase unit (four makers as items, ${total:,.2f})",
        f"Created: {first.paypal_order_id}",
    )
    approve(gateway, first.paypal_order_id, first.approval_url, proof)
    proof.record("The sandbox buyer approves it at PayPal", "Approved")
    hold = gateway.reserve(first.paypal_order_id).holds[WHOLE_ORDER]
    proof.record("Authorize", f"${total:,.2f} held on authorization {hold}")

    (amina, _, a, _), (priya, _, p, _), (lucia, _, dropped, _), (grace, _, g, _) = SHARES
    first_share = share(run, amina, hold, a, last=False)
    first_capture = capture(gateway, first_share)
    proof.record(f"Partial capture ${a:,.2f}, `final_capture` false", f"Captured: {first_capture}")
    tracker = track(gateway, first.paypal_order_id, first_share, first_capture, "DHL", None)
    proof.record("Tracking on that capture, carrier DHL", f"Accepted: tracker {tracker}")

    second_share = share(run, priya, hold, p, last=False)
    second_capture = capture(gateway, second_share)
    proof.record(f"Second partial capture ${p:,.2f}, `final_capture` false", f"Captured: {second_capture}")
    tracker = track(gateway, first.paypal_order_id, second_share, second_capture, "OTHER", "Leopards Courier")
    proof.record('Tracking on the second capture, carrier `OTHER` with `carrier_name_other` "Leopards Courier"', f"Accepted: tracker {tracker}")

    proof.record(f"A dropped share (${dropped:,.2f})", "Never captured")
    final = capture(gateway, share(run, grace, hold, g, last=True))
    paid = a + p + g
    proof.record(
        f"Final capture ${g:,.2f}, `final_capture` true",
        f"Captured: {final}; the authorization closed. The buyer paid ${paid:,.2f} of ${total:,.2f}",
    )
    again = capture(gateway, first_share)
    proof.record(
        "The first capture sent again with the same PayPal-Request-Id",
        "The same capture came back: PayPal dedupes the retry" if again == first_capture else f"A different capture: {again}",
    )

    proof.out("\nOrder 2: one share captured, the rest voided")
    second = gateway.create_checkout(checkout(run, "2"))
    approve(gateway, second.paypal_order_id, second.approval_url, proof)
    hold = gateway.reserve(second.paypal_order_id).holds[WHOLE_ORDER]
    capture(gateway, share(run, f"{amina}-2", hold, a, last=False))
    gateway.release_share(share(run, f"{grace}-2", hold, total - a, last=True))
    proof.record("A second order: one partial capture, then void", f"The remaining ${total - a:,.2f} voided")

    if payee:
        result = payout(gateway, run, "paypal", dollar({"recipient_type": "EMAIL", "receiver": payee}, run, "paypal"))
        proof.record("Payout $1.00 to a PayPal account", result)
    venmo = {"recipient_wallet": "Venmo", "recipient_type": "USER_HANDLE", "receiver": VENMO_HANDLE, "note": "Proof"}
    try:
        result = payout(gateway, run, "venmo", dollar(venmo, run, "venmo"))
    except (PayPalError, PaymentError) as error:  # our client's errors, and the gateway's
        result = f'Refused: "{error}"'
    proof.record("Payout $1.00 to a Venmo handle (`recipient_wallet` Venmo)", result)
    return proof


def connect(settings: Settings) -> PayoutsGateway:
    if not sandbox_host(settings.PAYPAL_API_BASE):
        raise SystemExit(f"{settings.PAYPAL_API_BASE} is not PayPal's sandbox: the proof runs only there.")
    secret = settings.PAYPAL_CLIENT_SECRET
    if not settings.PAYPAL_CLIENT_ID or secret is None:
        raise SystemExit("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env first.")
    return PayoutsGateway.connect(settings.PAYPAL_API_BASE, settings.PAYPAL_CLIENT_ID, secret.get_secret_value())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--payee", help="a sandbox PayPal account's email, for a $1.00 payout")
    parser.add_argument("--plan", action="store_true", help="print the steps and send nothing")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Lucía's name on a Windows console
    if args.plan:
        print(plan())
        return 0
    gateway = connect(get_settings())
    try:
        proof = run_proof(gateway, Proof(), payee=args.payee)
    finally:
        gateway.close()
    print("\nFor docs/day-one-checks.md:\n")
    print(proof.table())
    return 0


if __name__ == "__main__":
    sys.exit(main())
