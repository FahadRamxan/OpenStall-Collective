"""PayPal disputes (prompt 56): reading PayPal's dispute, the evidence that answers one, and simulated PayPal's side
of it in FakeGateway."""

import json
from decimal import Decimal

import pytest

from openstall_paypal import DisputeEvidence, FakeGateway, PaymentError
from openstall_paypal.disputes import (
    ANSWERABLE,
    REASONS,
    can_answer,
    disputed_captures,
    evidence_input,
    multipart_parts,
)

EVIDENCE = DisputeEvidence(
    dispute_id="PP-D-1",
    part_id="op_amina",
    carrier="TCS",
    tracking_number="7712345678",
    notes="Shipped with TCS, tracking number 7712345678.",
)
WAITING = {
    "dispute_id": "PP-D-1",
    "status": "WAITING_FOR_SELLER_RESPONSE",
    "disputed_transactions": [{"seller_transaction_id": "CAP-1"}, {"buyer_transaction_id": "B-1"}],
    "links": [{"rel": "provide_evidence", "method": "POST", "href": "/v1/customer/disputes/PP-D-1/provide-evidence"}],
}


def test_a_dispute_names_the_captures_it_is_about() -> None:
    assert disputed_captures(WAITING) == ["CAP-1"]
    assert disputed_captures({"disputed_transactions": None}) == []


def test_paypal_takes_the_seller_s_evidence_only_while_it_waits_for_her_and_offers_it() -> None:
    assert can_answer(WAITING)
    assert not can_answer({**WAITING, "status": "UNDER_REVIEW"})
    assert not can_answer({**WAITING, "links": [{"rel": "self", "href": "/v1/customer/disputes/PP-D-1"}]})
    # A link found by its address counts too, whatever its rel.
    assert can_answer({**WAITING, "links": [{"rel": "x", "href": "https://api/v1/customer/disputes/PP-D-1/provide-evidence"}]})


def test_only_a_parcel_that_never_came_is_answered_by_her_proof() -> None:
    assert ANSWERABLE == {"MERCHANDISE_OR_SERVICE_NOT_RECEIVED"}
    assert REASONS["MERCHANDISE_OR_SERVICE_NOT_RECEIVED"] == "the parcel did not arrive"


def test_the_evidence_is_proof_of_fulfilment_with_her_tracking_under_her_courier_s_own_name() -> None:
    assert evidence_input(EVIDENCE) == {
        "evidences": [
            {
                "evidence_type": "PROOF_OF_FULFILLMENT",
                "evidence_info": {
                    "tracking_info": [
                        {"carrier_name": "OTHER", "carrier_name_other": "TCS", "tracking_number": "7712345678"}
                    ]
                },
                "notes": "Shipped with TCS, tracking number 7712345678.",
            }
        ]
    }


def test_the_evidence_stays_within_paypal_s_limits() -> None:
    long = DisputeEvidence("PP-D-1", "op_1", "C" * 3000, "9" * 300, "n" * 2500)

    [evidence] = evidence_input(long)["evidences"]

    assert len(evidence["notes"]) == 2000
    [tracking] = evidence["evidence_info"]["tracking_info"]
    assert (len(tracking["carrier_name_other"]), len(tracking["tracking_number"])) == (2000, 255)


def test_the_multipart_body_has_the_json_then_her_receipt_photo() -> None:
    [only] = multipart_parts(EVIDENCE)
    assert only[0] == "input" and only[1][0] is None and only[1][2] == "application/json"
    assert json.loads(only[1][1]) == evidence_input(EVIDENCE)

    with_photo = DisputeEvidence(**{**EVIDENCE.__dict__, "photo": b"PNG", "photo_name": "r.png", "photo_type": "image/png"})
    assert multipart_parts(with_photo)[1] == ("evidence-file", ("r.png", b"PNG", "image/png"))


# Simulated PayPal's side (FakeGateway)


def opened(gateway: FakeGateway, reason: str = "MERCHANDISE_OR_SERVICE_NOT_RECEIVED") -> str:
    dispute_id = gateway.open_dispute("AUTH-1-CAP-1", Decimal("216.00"), reason)
    return dispute_id


def test_the_buyer_opens_a_dispute_and_paypal_says_so() -> None:
    gateway = FakeGateway()

    dispute_id = opened(gateway)

    [event] = gateway.take_outbox()
    assert event["event_type"] == "CUSTOMER.DISPUTE.CREATED"
    dispute = event["resource"]
    assert dispute["dispute_id"] == dispute_id and dispute_id.startswith("PP-D-FAKE-")
    assert disputed_captures(dispute) == ["AUTH-1-CAP-1"]
    assert dispute["dispute_amount"] == {"currency_code": "USD", "value": "216.00"}
    assert can_answer(dispute)
    assert opened(gateway) == dispute_id and gateway.take_outbox() == []  # opened again: nothing new
    assert gateway.calls == []  # the buyer's action, not ours


def test_simulated_paypal_takes_her_proof_and_decides_in_her_favour() -> None:
    gateway = FakeGateway()
    dispute_id = opened(gateway)
    gateway.take_outbox()

    gateway.answer_dispute(DisputeEvidence(**{**EVIDENCE.__dict__, "dispute_id": dispute_id}))

    [event] = gateway.take_outbox()
    assert event["event_type"] == "CUSTOMER.DISPUTE.RESOLVED"
    assert event["resource"]["status"] == "RESOLVED"
    assert event["resource"]["dispute_outcome"] == {"outcome_code": "RESOLVED_SELLER_FAVOUR"}
    assert not can_answer(event["resource"])
    assert [name for name, _ in gateway.calls] == ["answer_dispute"]


def test_evidence_for_a_dispute_paypal_does_not_know_or_has_closed_is_refused() -> None:
    gateway = FakeGateway()
    with pytest.raises(PaymentError) as unknown:
        gateway.answer_dispute(EVIDENCE)
    assert unknown.value.issue == "INVALID_RESOURCE_ID"

    dispute_id = opened(gateway)
    evidence = DisputeEvidence(**{**EVIDENCE.__dict__, "dispute_id": dispute_id})
    gateway.answer_dispute(evidence)
    with pytest.raises(PaymentError) as closed:
        gateway.answer_dispute(evidence)
    assert closed.value.issue == "NOT_AUTHORIZED"
