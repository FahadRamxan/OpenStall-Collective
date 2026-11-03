"""Payout rails (spec 3.5a): how a maker is paid once her share is captured, decided by the country she lives in.

| Country                    | Rail                                                             |
|----------------------------|------------------------------------------------------------------|
| India, Mexico, UK, others  | PayPal Payouts to her PayPal account                             |
| United States, with handle | Payouts to Venmo (recipient_wallet Venmo, USD and US only)       |
| Pakistan                   | Not connected yet: Pakistan is not on PayPal's country list.     |
|                            | Prompt 52 adds Hyperwallet (simulated).                          |

A share is never captured when her rail is unavailable, so a maker is never left half paid.

Venmo items use recipient_type USER_HANDLE with a note, which Venmo requires. Never PHONE (the PayPal sandbox does not
support it) and never VENMO_HANDLE (that value appears in the AI-Toolkit's payouts.md but not in the API reference).
PayPal's sandbox refuses every Venmo payout ("Recipient wallet not supported in sandbox", docs/day-one-checks.md), so
in the sandbox a Venmo share is captured for real and her payout is simulated and labelled so.
"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from openstall_paypal.gateway import PaymentError, PayoutRail, Share

__all__ = [
    "COUNTRY_NAMES",
    "DEFAULT_NOTE",
    "NO_SANDBOX_PAYPAL_ACCOUNT",
    "RAIL_NAMES",
    "PayoutRail",
    "Rail",
    "payout_item",
    "rail_for",
    "receiver",
    "venmo_payouts_simulated",
]

COUNTRY_NAMES = {"PK": "Pakistan", "IN": "India", "MX": "Mexico", "GB": "United Kingdom", "US": "United States"}
RAIL_NAMES: dict[PayoutRail, str] = {
    "paypal": "PayPal",
    "venmo": "Venmo",
    "hyperwallet": "Hyperwallet",
    "unavailable": "no payout rail",
}
# Countries PayPal Payouts cannot reach. Pakistan gets Hyperwallet in prompt 52.
NO_PAYPAL_PAYOUTS = frozenset({"PK"})
DEFAULT_NOTE = "Your share of an OpenStall Collective order."
NO_SANDBOX_PAYPAL_ACCOUNT = "no sandbox PayPal account linked yet"


@dataclass(frozen=True)
class Rail:
    """A maker's payout rail. `reason` says why she cannot be paid yet, when `kind` is "unavailable"."""

    kind: PayoutRail
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.kind != "unavailable"


def _not_connected(detail: str) -> Rail:
    return Rail("unavailable", f"Payout rail not connected yet ({detail})")


def rail_for(
    country: str | None,
    venmo_handle: str | None,
    paypal_email: str | None,
    paypal_merchant_id: str | None,
    *,
    override: PayoutRail | None = None,
    payee_required: bool = False,
) -> Rail:
    """The rail a maker is paid on. `override` is a seller's own choice, when an operator set one.

    `payee_required`: real money paths (the sandbox) need her PayPal account on the PayPal rail. Without one she is
    unavailable rather than captured and then left unpaid. Fake mode simulates the payout, so it needs none.
    """
    country = (country or "").strip().upper()
    if override is not None:
        kind = override
    elif country in NO_PAYPAL_PAYOUTS:
        kind = "unavailable"
    elif country == "US" and venmo_handle:
        kind = "venmo"
    else:
        kind = "paypal"

    # After the override too: no override sends a PayPal or Venmo payout to a country PayPal Payouts cannot reach.
    if kind == "unavailable" or (kind in ("paypal", "venmo") and country in NO_PAYPAL_PAYOUTS):
        return _not_connected(COUNTRY_NAMES.get(country, country or "country unknown"))
    if kind == "hyperwallet":
        return _not_connected("Hyperwallet is not connected yet")
    if kind == "venmo":
        if not venmo_handle:
            return _not_connected("no Venmo handle linked yet")
        if country != "US":
            return _not_connected("Venmo pays makers in the United States only")
        return Rail("venmo")
    if payee_required and not (paypal_email or paypal_merchant_id):
        return _not_connected(NO_SANDBOX_PAYPAL_ACCOUNT)
    return Rail("paypal")


def receiver(share: Share) -> dict[str, str]:
    """Who a PayPal-rail payout goes to: her PayPal email, else her merchant id."""
    if share.payee_email:
        return {"recipient_type": "EMAIL", "receiver": share.payee_email}
    if share.payee_merchant_id:
        return {"recipient_type": "PAYPAL_ID", "receiver": share.payee_merchant_id}
    raise PaymentError("PAYEE_MISSING", f"no PayPal account is linked for share {share.part_id}")


def payout_item(share: Share) -> dict[str, Any]:
    """The share's item in a POST /v1/payments/payouts request, for her rail. Raises PaymentError when no rail can
    pay her, so callers build it before capturing anything."""
    amount = {"currency": "USD", "value": f"{share.amount_usd:.2f}"}
    note = share.note or DEFAULT_NOTE
    if share.payout_rail == "venmo":
        if not share.venmo_handle:
            raise PaymentError("PAYEE_MISSING", f"no Venmo handle is linked for share {share.part_id}")
        return {
            "recipient_wallet": "Venmo",
            "recipient_type": "USER_HANDLE",
            "receiver": share.venmo_handle,
            "note": note,  # Venmo requires a note
            "amount": amount,
            "sender_item_id": share.part_id,
        }
    if share.payout_rail == "paypal":
        return {**receiver(share), "amount": amount, "sender_item_id": share.part_id, "note": note}
    raise PaymentError(
        "PAYOUT_RAIL_UNAVAILABLE", f"no payout rail can reach the maker of share {share.part_id} yet ({share.payout_rail})"
    )


def venmo_payouts_simulated(api_base: str) -> bool:
    """Whether Venmo payouts are simulated on this PayPal host: always in the sandbox, which refuses them."""
    host = urlsplit(api_base).hostname or ""
    return "sandbox" in host
