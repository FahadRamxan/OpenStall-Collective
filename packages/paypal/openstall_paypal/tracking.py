"""Tracking on the PayPal order (prompt 33): which PayPal carrier code a courier's name is, and which of an order's
trackers is ours.

PayPal takes a carrier from its ShipmentCarrier list, or OTHER with the courier's name. The demo's couriers are mapped
to members of the SDK's own enum (paypal-plan.md lists them, each checked to exist), so a member that disappears
breaks on import, not at PayPal. Any other courier, Leopards for one, goes as OTHER with its name, as the sandbox
proof did.
"""

from collections.abc import Iterable

from paypal.models.enums import ShipmentCarrier

OTHER = ShipmentCarrier.OTHER.value
UNNAMED = "Courier not named"  # carrier_name_other when the receipt named no courier: PayPal needs a name for OTHER

# A courier's name with only its letters and digits, lower case -> PayPal's carrier.
CARRIERS: dict[str, ShipmentCarrier] = {
    "tcs": ShipmentCarrier.TCS,
    "tcsexpress": ShipmentCarrier.TCS,
    "tcscourier": ShipmentCarrier.TCS,
    "tcscouriers": ShipmentCarrier.TCS,
    "indiapost": ShipmentCarrier.INDIA_POST,
    "speedpost": ShipmentCarrier.INDIA_POST,
    "estafeta": ShipmentCarrier.MEX_ESTAFETA,
    "correosdemexico": ShipmentCarrier.CORREOS_DE_MEXICO,
    "royalmail": ShipmentCarrier.ROYAL_MAIL,
    "parcelforce": ShipmentCarrier.PARCELFORCE,
    "parcelforceworldwide": ShipmentCarrier.PARCELFORCE,
    "usps": ShipmentCarrier.USPS,
    "unitedstatespostalservice": ShipmentCarrier.USPS,
    "ups": ShipmentCarrier.UPS,
    "fedex": ShipmentCarrier.FEDEX,
    "dhl": ShipmentCarrier.DHL,
    "dhlexpress": ShipmentCarrier.DHL,
    "bluedart": ShipmentCarrier.BLUEDART,
    "delhivery": ShipmentCarrier.IND_DELHIVERY,
    "dtdc": ShipmentCarrier.DTDC_IN,
}


def carrier_code(name: str | None) -> tuple[str, str | None]:
    """PayPal's carrier for a courier's name, and the name to send with OTHER: ("INDIA_POST", None) for "India
    Post", ("OTHER", "Leopards Courier") for a courier PayPal does not list."""
    key = "".join(char for char in (name or "").lower() if char.isalnum())
    known = CARRIERS.get(key)
    if known is not None:
        return known.value, None
    named = " ".join((name or "").split())
    return OTHER, named if named and named.upper() != OTHER else UNNAMED


def tracker_for(trackers: Iterable[str], tracking_number: str, known: Iterable[str] | None = None) -> str | None:
    """Which of an order's trackers is this shipment's: one whose id holds the tracking number; else, only when
    `known` (the trackers on the order just before our call) is given, the one tracker that is new since; else None.

    Reading an order back without `known`, only the tracking number can say a tracker is ours: another maker's
    tracker must never be taken for hers."""
    listed = list(trackers)
    for tracker in listed:
        if tracking_number and tracking_number in tracker:
            return tracker
    if known is None:
        return None
    before = set(known)
    new = [tracker for tracker in listed if tracker not in before]
    return new[0] if len(new) == 1 else None
