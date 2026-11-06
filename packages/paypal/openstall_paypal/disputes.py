"""PayPal disputes (prompt 56): reading PayPal's dispute, and the evidence that answers one.

A buyer who says her parcel never came opens a dispute at PayPal on a maker's capture. PayPal's dispute names the
capture as `disputed_transactions[].seller_transaction_id`, says why (`reason`), and lists, in its HATEOAS `links`,
what the seller may do now: `provide_evidence` only while PayPal waits for the seller (status
WAITING_FOR_SELLER_RESPONSE). The answer is PROOF_OF_FULFILLMENT: her tracking (carrier OTHER with her courier's name,
since PayPal's dispute carriers are not the order-tracking ones), notes in words, and her courier receipt photo.

From PayPal's Customer Disputes v1 OpenAPI spec (github.com/paypal/paypal-rest-api-specifications): the reason and
status enums, tracking_info's required carrier_name and tracking_number (255 characters at most), notes (2,000) and
the multipart file part `evidence-file`. The JSON part's name, `input`, is not in the spec; it is the name PayPal's own
examples use, so check it on the first real dispute (paypal-plan.md).
"""

import json
from collections.abc import Mapping
from typing import Any

from openstall_paypal.gateway import DisputeEvidence

__all__ = [
    "ANSWERABLE",
    "REASONS",
    "can_answer",
    "disputed_captures",
    "evidence_input",
    "multipart_parts",
]

# Why a buyer disputes, in words for the receipt and the feed (the spec's reason enum).
REASONS = {
    "MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "the parcel did not arrive",
    "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": "the item is not as described",
    "UNAUTHORISED": "the payment was not authorised",
    "CREDIT_NOT_PROCESSED": "a refund was not processed",
    "DUPLICATE_TRANSACTION": "the payment was taken twice",
    "INCORRECT_AMOUNT": "the amount was wrong",
    "PAYMENT_BY_OTHER_MEANS": "the buyer paid another way",
    "CANCELED_RECURRING_BILLING": "a cancelled subscription was billed",
    "PROBLEM_WITH_REMITTANCE": "a problem with the payment",
    "OTHER": "another reason",
}
# What her proof of shipping answers. Anything else needs a person: a parcel not as described is not disproved by a
# tracking number.
ANSWERABLE = frozenset({"MERCHANDISE_OR_SERVICE_NOT_RECEIVED"})

NOTES_LIMIT = 2000
TRACKING_LIMIT = 255


def disputed_captures(dispute: Mapping[str, Any]) -> list[str]:
    """The captures a dispute is about: PayPal's seller_transaction_id for each disputed transaction."""
    found = []
    for transaction in dispute.get("disputed_transactions") or []:
        if isinstance(transaction, Mapping) and transaction.get("seller_transaction_id"):
            found.append(str(transaction["seller_transaction_id"]))
    return found


def can_answer(dispute: Mapping[str, Any]) -> bool:
    """Whether PayPal takes the seller's evidence now: it waits for the seller, and offers provide_evidence."""
    if dispute.get("status") != "WAITING_FOR_SELLER_RESPONSE":
        return False
    for link in dispute.get("links") or []:
        if isinstance(link, Mapping) and (
            link.get("rel") == "provide_evidence" or str(link.get("href", "")).endswith("/provide-evidence")
        ):
            return True
    return False


def evidence_input(evidence: DisputeEvidence) -> dict[str, Any]:
    """The JSON of provide-evidence: proof of fulfilment, with her tracking and the notes."""
    return {
        "evidences": [
            {
                "evidence_type": "PROOF_OF_FULFILLMENT",
                "evidence_info": {
                    "tracking_info": [
                        {
                            "carrier_name": "OTHER",
                            "carrier_name_other": evidence.carrier[:NOTES_LIMIT],
                            "tracking_number": evidence.tracking_number[:TRACKING_LIMIT],
                        }
                    ]
                },
                "notes": evidence.notes[:NOTES_LIMIT],
            }
        ]
    }


def multipart_parts(evidence: DisputeEvidence) -> list[tuple[str, tuple[str | None, bytes, str]]]:
    """The multipart/form-data parts of provide-evidence: the JSON as `input`, then her receipt photo, if any, as
    `evidence-file`."""
    parts: list[tuple[str, tuple[str | None, bytes, str]]] = [
        ("input", (None, json.dumps(evidence_input(evidence)).encode("utf-8"), "application/json"))
    ]
    if evidence.photo is not None:
        parts.append(
            (
                "evidence-file",
                (evidence.photo_name or "courier-receipt.jpg", evidence.photo, evidence.photo_type or "image/jpeg"),
            )
        )
    return parts
