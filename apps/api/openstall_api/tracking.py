"""Each maker's tracking on the PayPal order (spec 3.6, prompt 33): once her share is captured on proof of shipping,
her confirmed tracking number and courier go on that capture at PayPal, so the buyer sees them on their PayPal order.

It runs after her payment is committed, in a transaction of its own (payments.track_share), so a tracking call that
fails never undoes a payment. It is tried again whenever the order is reserved again (the receipt page, opened again),
so a share whose tracking PayPal did not take is put right without anyone repeating her payment.
"""

import logging
from collections.abc import Callable

from sqlalchemy import select

from openstall_api.adapters import AdapterUnavailable
from openstall_api.claims import ClaimHeld
from openstall_api.db import new_session, session_scope
from openstall_api.events import EventType, record_event
from openstall_api.models import OrderPart
from openstall_api.payments import PAID, OrderNotFound, WrongStatus, track_share
from openstall_api.settings import get_settings
from openstall_paypal import PaymentError, PaymentGateway, PaymentUnavailable

log = logging.getLogger(__name__)


def track_on_paypal(part_id: str, gateway: Callable[[], PaymentGateway]) -> bool:
    """Put one paid share's tracking on the PayPal order, in a transaction of its own. Returns whether it is there
    now. When PayPal refuses or does not answer, tracking.not_added says why, and the share is tried again later."""
    try:
        with session_scope() as session:
            part = track_share(session, part_id, gateway())
            return part.paypal_tracker_id is not None
    except ClaimHeld:
        return False  # another request is adding it right now
    except (WrongStatus, OrderNotFound) as error:
        log.info("Tracking for share %s is not for PayPal yet: %s", part_id, error)
        return False
    except (PaymentError, AdapterUnavailable) as error:
        log.warning("Tracking for share %s could not be added to PayPal: %s", part_id, error)
        _not_added(part_id, error)
        return False


def track_order(order_id: str, gateway: Callable[[], PaymentGateway]) -> list[str]:
    """Put the tracking of every paid share of the order that is not on PayPal yet on it. Safe to call again.
    Returns the ids of the shares whose tracking went on now."""
    with new_session() as session:
        waiting = session.scalars(
            select(OrderPart.id).where(
                OrderPart.order_id == order_id,
                OrderPart.status.in_(sorted(PAID)),
                OrderPart.tracking_number.is_not(None),
                OrderPart.paypal_tracker_id.is_(None),
            )
        ).all()
    return [part_id for part_id in waiting if track_on_paypal(part_id, gateway)]


def _not_added(part_id: str, error: Exception) -> None:
    issue = error.issue if isinstance(error, PaymentError) else type(error).__name__
    unknown = isinstance(error, PaymentUnavailable)
    with session_scope() as session:
        part = session.get(OrderPart, part_id)
        if part is None:
            return
        where = "simulated PayPal" if get_settings().OPENSTALL_MODE == "fake" else "PayPal"
        record_event(
            session,
            EventType.TRACKING_NOT_ADDED,
            f"{part.seller.name}'s tracking is not on the {where} order yet ({issue}"
            f"{': PayPal did not answer' if unknown else ''}). It is tried again when the order is opened again",
            entity_id=part.id,
            payload={"order_id": part.order_id, "issue": issue, "outcome_unknown": unknown},
        )
