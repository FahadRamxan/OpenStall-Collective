"""Pay-on-proof in fake mode, as the receipt sees it (prompt 51): the simulated proof of shipping, each maker's payout
rail and its label, honest confirmation sources, and the sandbox payees a real payout would need."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import Event, Order, OrderPart, PartStatus, PayoutRailChoice, Seller
from openstall_api.passports import FAKE_MODE_KEY_B64
from openstall_api.payments import pay_share, release_share, share_of
from openstall_api.seed import DEMO_ORDER_ID, MAKERS, seed, seed_demo_order
from openstall_paypal import PayoutsGateway, Payment, PayPalClient, Share

client = TestClient(app)


@pytest.fixture
def demo_order(db):
    seed(db, with_amina=True)
    seed_demo_order(db, date(2026, 11, 10))
    db.commit()
    return db


@pytest.fixture
def reserved(demo_order, fakes) -> dict[str, str]:
    """The demo order approved on the simulated PayPal page and reserved, with its webhooks delivered."""
    token = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve").status_code == 200
    demo_order.expire_all()
    return {part.seller_id: part.id for part in demo_order.get(Order, DEMO_ORDER_ID).parts}


def parts_by_seller(body: dict) -> dict[str, dict]:
    return {part["seller"]["id"]: part for part in body["parts"]}


def test_each_maker_shows_her_rail_and_fake_mode_says_it_is_simulated(demo_order):
    parts = parts_by_seller(client.get(f"/api/orders/{DEMO_ORDER_ID}").json())

    assert {seller: (p["payout_rail"], p["payout_label"]) for seller, p in parts.items()} == {
        "s_amina": ("unavailable", "Payout rail not connected yet (Pakistan)"),
        "s_priya": ("paypal", "Paid to PayPal when she ships (simulated)"),
        "s_lucia": ("paypal", "Paid to PayPal when she ships (simulated)"),
        "s_grace": ("venmo", "Paid to Venmo when she ships (simulated)"),
    }
    assert {p["confirmation_source"] for p in parts.values()} == {"simulated"}
    assert [p["payout_via_paypal"] for p in parts.values()] == [False, True, True, True]


def test_dev_proof_pays_one_share_and_leaves_the_others_reserved(reserved, demo_order):
    priya = reserved["s_priya"]

    response = client.post(f"/api/dev/parts/{priya}/proof")

    assert response.status_code == 200
    parts = parts_by_seller(response.json())
    assert parts["s_priya"]["status"] == "captured"
    assert [parts[seller]["status"] for seller in ("s_amina", "s_lucia", "s_grace")] == ["authorized"] * 3
    assert response.json()["status"] == "partly_shipped"
    demo_order.expire_all()
    part = demo_order.get(OrderPart, priya)
    assert (part.tracking_number, part.carrier) == (f"SIMULATED-{priya}", "OTHER")
    assert part.capture_id == f"{part.authorization_id}-CAP-1"
    [captured] = demo_order.scalars(select(Event).where(Event.type == EventType.PART_CAPTURED)).all()
    assert captured.payload_json["payout_rail"] == "paypal"

    # Simulated PayPal's capture and payout webhooks follow the request, as PayPal's would.
    after = parts_by_seller(client.get(f"/api/orders/{DEMO_ORDER_ID}").json())
    assert (after["s_priya"]["confirmed_by_paypal"], after["s_priya"]["payout_confirmed"]) == (True, True)
    assert after["s_priya"]["confirmation_source"] == "simulated"
    assert after["s_priya"]["payout_label"] == "Paid to PayPal (simulated)"
    assert after["s_grace"]["payout_label"] == "Paid to Venmo when she ships (simulated)"
    assert after["s_grace"]["payout_confirmed"] is False


def test_dev_proof_twice_pays_once(reserved, demo_order, fakes):
    grace = reserved["s_grace"]

    first = client.post(f"/api/dev/parts/{grace}/proof")
    second = client.post(f"/api/dev/parts/{grace}/proof")

    assert (first.status_code, second.status_code) == (200, 200)
    assert [name for name, _ in fakes.payment_gateway.calls].count("pay_share") == 1
    assert parts_by_seller(second.json())["s_grace"]["payout_label"] == "Paid to Venmo (simulated)"


def test_dev_proof_refuses_amina_before_anything_is_captured(reserved, demo_order, fakes):
    amina = reserved["s_amina"]
    fakes.payment_gateway.calls.clear()

    response = client.post(f"/api/dev/parts/{amina}/proof")

    assert response.status_code == 409
    assert "Payout rail not connected yet (Pakistan)" in response.json()["detail"]
    assert fakes.payment_gateway.calls == []
    demo_order.expire_all()
    part = demo_order.get(OrderPart, amina)
    assert (part.status, part.tracking_number) == (PartStatus.AUTHORIZED, None)  # nothing was saved


def test_a_paypal_override_does_not_get_amina_captured(reserved, demo_order, fakes):
    demo_order.get(Seller, "s_amina").payout_rail = PayoutRailChoice.PAYPAL  # an operator's override
    demo_order.commit()
    fakes.payment_gateway.calls.clear()

    response = client.post(f"/api/dev/parts/{reserved['s_amina']}/proof")

    assert response.status_code == 409
    assert "Payout rail not connected yet (Pakistan)" in response.json()["detail"]
    assert fakes.payment_gateway.calls == []


def test_dev_proof_for_an_unknown_share_is_not_found(db):
    assert client.post("/api/dev/parts/op_nobody/proof").status_code == 404


def test_dev_proof_returns_404_in_sandbox_mode(use_settings, db):
    use_settings(OPENSTALL_MODE="sandbox")

    assert client.post("/api/dev/parts/op_anything/proof").status_code == 404


def test_the_last_proof_is_the_final_capture(reserved, demo_order, fakes):
    assert client.post(f"/api/dev/parts/{reserved['s_amina']}/proof").status_code == 409  # she stays reserved
    release_share(demo_order, reserved["s_amina"], fakes.payment_gateway)  # until she is released mid-order
    demo_order.commit()
    for seller in ("s_priya", "s_lucia", "s_grace"):
        assert client.post(f"/api/dev/parts/{reserved[seller]}/proof").status_code == 200

    finals = [share.last for name, share in fakes.payment_gateway.calls if name == "pay_share"]
    assert finals == [False, False, True]
    body = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()
    assert body["status"] == "shipped"
    amina = parts_by_seller(body)["s_amina"]
    # Released mid-order, then the final capture closed the hold: PayPal never says anything about her share.
    assert (amina["status"], amina["nothing_to_confirm"]) == ("released", True)


# Sandbox mode: real payouts need a PayPal account for each maker (prompt 51's plan review).

PAYEES = {
    "PAYPAL_SANDBOX_PAYEE_PRIYA": "priya-made-up@personal.example.com",
    "PAYPAL_SANDBOX_PAYEE_LUCIA": "lucia-made-up@personal.example.com",
    "PAYPAL_SANDBOX_PAYEE_NOOR": "noor-made-up@personal.example.com",
    "PASSPORT_SIGNING_KEY": FAKE_MODE_KEY_B64,  # sandbox mode signs the seeded passports with a key of its own
}


def test_sandbox_payees_are_seeded_only_in_sandbox_mode(use_settings, db):
    use_settings(OPENSTALL_MODE="fake", **PAYEES)  # the payees are set, but fake mode never links them
    seed(db, with_amina=True)
    db.commit()
    assert {seller.id: seller.paypal_email for seller in db.scalars(select(Seller))} == {
        maker.id: None for maker in MAKERS
    }

    use_settings(OPENSTALL_MODE="sandbox", **PAYEES)
    seed(db, with_amina=True)
    db.commit()
    db.expire_all()
    sellers = {seller.id: seller for seller in db.scalars(select(Seller))}
    assert {seller_id: seller.paypal_email for seller_id, seller in sellers.items()} == {
        "s_amina": None,
        "s_priya": PAYEES["PAYPAL_SANDBOX_PAYEE_PRIYA"],
        "s_lucia": PAYEES["PAYPAL_SANDBOX_PAYEE_LUCIA"],
        "s_grace": None,
        "s_noor": PAYEES["PAYPAL_SANDBOX_PAYEE_NOOR"],
    }
    assert sellers["s_grace"].venmo_handle == "grace-detroit-demo"


class Recorded(PayoutsGateway):
    """PayoutsGateway's own pay_share, with PayPal answered here: what it would capture and pay out, never sent."""

    def __init__(self) -> None:
        super().__init__(PayPalClient("https://api-m.sandbox.paypal.com", "made-up-id", "made-up-secret"), None)  # type: ignore[arg-type]
        self.items: list[dict] = []
        self.captured: list[str] = []
        self.client.post = self._payout  # type: ignore[method-assign]

    def capture(self, share: Share, body: object) -> str:
        self.captured.append(share.part_id)
        return f"CAPTURE-{share.part_id}"

    def _payout(self, path: str, body: dict, *, idempotency_key: str) -> dict:
        self.items.extend(body["items"])
        return {"batch_header": {"payout_batch_id": f"BATCH-{idempotency_key}"}}


def test_in_sandbox_mode_pay_share_builds_a_receiver_for_each_non_pk_seeded_maker(use_settings, db):
    use_settings(OPENSTALL_MODE="sandbox", **PAYEES)
    seed(db, with_amina=True)
    db.commit()
    gateway = Recorded()
    paid = {}
    for maker in MAKERS:
        if maker.country == "PK":
            continue
        seller = db.get(Seller, maker.id)
        part = OrderPart(
            id=f"op_{maker.id}",
            order_id="ord_x",
            seller=seller,
            reference_id="op_001",
            quantity=1,
            unit_price_usd=Decimal("10.00"),
            amount_usd=Decimal("10.00"),
            status=PartStatus.AUTHORIZED,
            authorization_id="AUTH-ALL",
        )
        part.order = Order(id="ord_x", total_usd=Decimal("10.00"), parts=[part])
        paid[maker.id] = gateway.pay_share(share_of(part))
        db.expunge_all()

    receivers = {item["sender_item_id"]: (item["recipient_type"], item["receiver"]) for item in gateway.items}
    assert receivers == {
        "op_s_priya": ("EMAIL", PAYEES["PAYPAL_SANDBOX_PAYEE_PRIYA"]),
        "op_s_lucia": ("EMAIL", PAYEES["PAYPAL_SANDBOX_PAYEE_LUCIA"]),
        "op_s_noor": ("EMAIL", PAYEES["PAYPAL_SANDBOX_PAYEE_NOOR"]),
    }
    # Grace is captured for real but her Venmo payout is simulated: PayPal's sandbox refuses Venmo payouts.
    assert "op_s_grace" in gateway.captured
    assert paid["s_grace"] == Payment("CAPTURE-op_s_grace", None, "venmo", payout_simulated=True)


def test_in_sandbox_mode_without_payees_the_paypal_makers_are_not_connected(use_settings, demo_order):
    use_settings(OPENSTALL_MODE="sandbox", PAYPAL_CLIENT_ID="made-up-id", PAYPAL_CLIENT_SECRET="made-up-secret")

    parts = parts_by_seller(client.get(f"/api/orders/{DEMO_ORDER_ID}").json())

    assert {seller: (p["payout_rail"], p["payout_label"]) for seller, p in parts.items()} == {
        "s_amina": ("unavailable", "Payout rail not connected yet (Pakistan)"),
        "s_priya": ("unavailable", "Payout rail not connected yet (no sandbox PayPal account linked yet)"),
        "s_lucia": ("unavailable", "Payout rail not connected yet (no sandbox PayPal account linked yet)"),
        "s_grace": ("venmo", "Paid to Venmo when she ships (simulated: Venmo payouts don't run in PayPal's sandbox)"),
    }
    assert {p["confirmation_source"] for p in parts.values()} == {"paypal_sandbox"}


def test_in_sandbox_mode_a_maker_without_a_payee_is_refused_before_any_capture(use_settings, demo_order):
    use_settings(OPENSTALL_MODE="sandbox")
    part = next(p for p in demo_order.get(Order, DEMO_ORDER_ID).parts if p.seller_id == "s_priya")
    part.status = PartStatus.AUTHORIZED
    part.authorization_id = "AUTH-ALL"
    part.tracking_number = "LP00123456789IN"
    demo_order.commit()
    gateway = Recorded()

    with pytest.raises(Exception, match="no sandbox PayPal account linked yet"):
        pay_share(demo_order, part.id, gateway)

    assert gateway.captured == [] and gateway.items == []


def test_a_released_share_says_it_gets_no_payout_even_without_a_rail(reserved, demo_order, fakes):
    release_share(demo_order, reserved["s_amina"], fakes.payment_gateway)
    demo_order.commit()

    parts = parts_by_seller(client.get(f"/api/orders/{DEMO_ORDER_ID}").json())
    assert parts["s_amina"]["payout_label"] == "No payout: her share was released"

