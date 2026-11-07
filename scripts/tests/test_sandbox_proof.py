"""The day-one sandbox proof script (prompt 08): it runs the payouts path step by step through the app's own gateway,
waits for a person to approve at PayPal without ever handling a login, refuses any host but the sandbox, and prints
each step as a row of docs/day-one-checks.md's table. Here PayPal is a stand-in gateway; the real run is a person's."""

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from openstall_paypal import Checkout, OrderState, PayPalValidationError, Reservation
from openstall_paypal.gateway import WHOLE_ORDER

SCRIPT = Path(__file__).resolve().parents[1] / "sandbox_proof.py"
_spec = importlib.util.spec_from_file_location("sandbox_proof", SCRIPT)
assert _spec is not None and _spec.loader is not None
sandbox_proof = importlib.util.module_from_spec(_spec)
sys.modules["sandbox_proof"] = sandbox_proof
_spec.loader.exec_module(sandbox_proof)


class StandInClient:
    """Our own PayPal client's side: payouts. A Venmo payout is refused, as PayPal's sandbox refuses it."""

    def __init__(self) -> None:
        self.payouts: list[tuple[dict[str, Any], str]] = []

    def post(self, path: str, body: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        assert path == "/v1/payments/payouts"
        self.payouts.append((body, idempotency_key))
        if body["items"][0].get("recipient_wallet") == "Venmo":
            raise PayPalValidationError("Recipient wallet not supported in sandbox.", issue="RECIPIENT_WALLET")
        return {"batch_header": {"payout_batch_id": "BATCH-1", "batch_status": "SUCCESS"}}


class StandInGateway:
    """PayPal as the proof meets it: each order is approved on the second look, a repeated capture returns the first."""

    def __init__(self) -> None:
        self.client = StandInClient()
        self.calls: list[tuple[Any, ...]] = []
        self.looks: dict[str, int] = {}
        self.captures: dict[str, str] = {}
        self.trackers: dict[str, list[str]] = {}

    def create_checkout(self, request: Any) -> Checkout:
        self.calls.append(("create_checkout", request.order_id, request.total_usd, len(request.parts)))
        token = f"PP-{request.order_id}"
        return Checkout(token, f"https://www.sandbox.paypal.com/checkoutnow?token={token}")

    def get_order(self, paypal_order_id: str) -> OrderState:
        self.looks[paypal_order_id] = self.looks.get(paypal_order_id, 0) + 1
        status = "APPROVED" if self.looks[paypal_order_id] > 1 else "CREATED"
        return OrderState(status, {}, tuple(self.trackers.get(paypal_order_id, [])))  # type: ignore[arg-type]

    def reserve(self, paypal_order_id: str) -> Reservation:
        self.calls.append(("reserve", paypal_order_id))
        return Reservation(paypal_order_id, {WHOLE_ORDER: f"AUTH-{paypal_order_id}"})

    def capture(self, share: Any, body: Any) -> str:
        self.calls.append(("capture", share.part_id, body.amount.value, body.final_capture))
        return self.captures.setdefault(share.part_id, f"CAP-{len(self.captures) + 1}")

    def add_tracking(self, tracking: Any) -> str:
        self.calls.append(("track", tracking.capture_id, tracking.carrier, tracking.carrier_name_other))
        trackers = self.trackers.setdefault(tracking.paypal_order_id, [])
        trackers.append(f"TRK-{len(trackers) + 1}")
        return trackers[-1]

    def release_share(self, share: Any) -> None:
        self.calls.append(("release", share.amount_usd, share.last))


def approve_at_once(gateway: Any, paypal_order_id: str, link: str, proof: Any) -> None:
    sandbox_proof.wait_for_approval(gateway, paypal_order_id, link, proof, sleep=lambda seconds: None)


def test_the_proof_runs_the_payouts_path_step_by_step_and_writes_the_table() -> None:
    gateway, printed = StandInGateway(), []

    proof = sandbox_proof.run_proof(
        gateway, sandbox_proof.Proof(out=printed.append), payee="priya@example.com", run="t1", approve=approve_at_once
    )

    assert [call for call in gateway.calls if call[0] != "track"] == [
        ("create_checkout", "proof-t1-1", Decimal("815.00"), 4),
        ("reserve", "PP-proof-t1-1"),
        ("capture", "proof-t1-amina", "216.00", False),
        ("capture", "proof-t1-priya", "176.00", False),
        ("capture", "proof-t1-grace", "203.00", True),  # the final capture closes the authorization
        ("capture", "proof-t1-amina", "216.00", False),  # the same capture again: PayPal answers with the first
        ("create_checkout", "proof-t1-2", Decimal("815.00"), 4),
        ("reserve", "PP-proof-t1-2"),
        ("capture", "proof-t1-amina-2", "216.00", False),
        ("release", Decimal("599.00"), True),  # the last share voids what is left
    ]
    assert [call for call in gateway.calls if call[0] == "track"] == [
        ("track", "CAP-1", "DHL", None),
        ("track", "CAP-2", "OTHER", "Leopards Courier"),
    ]
    rows = dict(proof.rows)
    assert rows["Authorize"] == "$815.00 held on authorization AUTH-PP-proof-t1-1"
    assert rows["Final capture $203.00, `final_capture` true"].endswith("The buyer paid $595.00 of $815.00")
    assert rows["The first capture sent again with the same PayPal-Request-Id"] == (
        "The same capture came back: PayPal dedupes the retry"
    )
    assert rows["A second order: one partial capture, then void"] == "The remaining $599.00 voided"
    assert rows["Payout $1.00 to a PayPal account"] == "batch BATCH-1, SUCCESS"
    assert rows["Payout $1.00 to a Venmo handle (`recipient_wallet` Venmo)"] == (
        'Refused: "Recipient wallet not supported in sandbox."'
    )
    assert proof.table().startswith("| Check | Result |\n|---|---|\n| Order with intent AUTHORIZE")


def test_you_approve_at_paypal_yourself_and_the_script_only_reads_the_order_back() -> None:
    gateway, printed = StandInGateway(), []

    approve_at_once(gateway, "PP-1", "https://www.sandbox.paypal.com/checkoutnow?token=PP-1", sandbox_proof.Proof(out=printed.append))

    assert gateway.looks == {"PP-1": 2}  # read until APPROVED; nothing written
    assert any("approve as the sandbox buyer" in line for line in printed)
    assert "https://www.sandbox.paypal.com/checkoutnow?token=PP-1" in printed[-1]
    source = SCRIPT.read_text(encoding="utf-8").lower()
    assert "password" not in source and "getpass" not in source and "input(" not in source  # it never asks for a login


def test_an_order_left_unapproved_stops_the_proof() -> None:
    gateway = StandInGateway()
    gateway.get_order = lambda paypal_order_id: OrderState("CREATED", {})  # type: ignore[method-assign]
    now = [0.0]

    def later(seconds: float) -> None:
        now[0] += 600

    with pytest.raises(SystemExit, match="was not approved within 15 minutes"):
        sandbox_proof.wait_for_approval(gateway, "PP-1", "link", sandbox_proof.Proof(out=lambda line: None), lambda: now[0], later)


def test_only_paypal_s_sandbox_and_only_with_its_keys(use_settings) -> None:
    with pytest.raises(SystemExit, match="is not PayPal's sandbox"):
        sandbox_proof.connect(use_settings(OPENSTALL_MODE="sandbox", PAYPAL_API_BASE="https://api-m.paypal.com"))
    with pytest.raises(SystemExit, match="Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET"):
        sandbox_proof.connect(use_settings(OPENSTALL_MODE="sandbox"))


def test_the_plan_lists_every_step_and_sends_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert sandbox_proof.main(["--plan"]) == 0

    steps = capsys.readouterr().out
    assert steps.startswith("1. One order with intent AUTHORIZE")
    assert "8. The same capture sent again with its PayPal-Request-Id" in steps
    assert "Recipient wallet not supported in sandbox" in steps
