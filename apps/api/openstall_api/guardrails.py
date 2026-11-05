"""Try to break it (prompt 40): the guardrail panel on /demo.

Each attack is a real attempt to do something OpenStall must never allow, made through the same code a real request
goes through, and each is refused by that code. The refusal is recorded in the live feed as security.rejected (a
forged webhook records its own, in webhooks.py). Nothing an attack touches is kept: an attack that needs an order of
its own drafts the story's order in a transaction that is rolled back, so no other page ever sees it.

The attacks:
- a price talked down below a maker's floor: the offer check every agent's proposal goes through (packages/allocator);
- an AI agent capturing the payment through MCP: the storefront has no tool that moves money;
- a smaller total sent by the browser: totals are worked out on the server (orders_api.verify_total);
- a forged PayPal webhook saying the order was paid: every webhook is verified first (webhooks.py);
- an order reserved that no person approved, and a maker paid before she proved she shipped (payments.py);
- a trust card with one number raised: its Ed25519 signature no longer holds (passports.py).
"""

import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException
from mcp import Client
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_allocator import Offer as CoreOffer
from openstall_allocator import QuoteRequest as CoreRequest
from openstall_allocator import is_valid_offer, lowest_allowed_price
from openstall_api import quotes
from openstall_api.adapters import AdapterRegistry
from openstall_api.db import new_session, session_scope
from openstall_api.events import EventType, record_event
from openstall_api.models import DataSource, Order, PartStatus, Passport, Product, ProductStatus
from openstall_api.offer_rules import listing_of, seller_policy
from openstall_api.orders import server_total
from openstall_api.orders_api import TotalIn, verify_total
from openstall_api.passports import trust_card, verify_card
from openstall_api.payments import WrongStatus, pay_share, reserve_order
from openstall_api.seed import story_order
from openstall_api.storefront import storefront
from openstall_api.webhooks import WebhookRefused, receive_paypal_webhook
from openstall_paypal import PaymentUnavailable

Result = Literal["refused", "got_through", "not_tried"]


@dataclass(frozen=True)
class Attack:
    key: str
    name: str  # what is tried, in words
    guard: str  # what refuses it, in words


ATTACKS: tuple[Attack, ...] = (
    Attack(
        "below_floor",
        "Talk a maker's price down to $1.00",
        "The offer check in code: every price an agent proposes is checked against her limits, whatever it was told",
    ),
    Attack(
        "capture_tool",
        "An AI agent captures the payment through MCP",
        "The MCP storefront has no tool that moves money: only a person's approval does",
    ),
    Attack(
        "changed_total",
        "Send a smaller total than the order's",
        "Totals are worked out on the server, never taken from a browser or an agent",
    ),
    Attack(
        "forged_webhook",
        "Forge a PayPal webhook that says the money was captured",
        "Every webhook is verified with PayPal before anything changes",
    ),
    Attack(
        "reserve_unapproved",
        "Reserve the money for an order no person approved",
        "Only PayPal's record of a person's approval reserves money",
    ),
    Attack(
        "pay_before_proof",
        "Pay a maker before she proves she shipped",
        "A share is captured only once she has confirmed her tracking",
    ),
    Attack(
        "tampered_passport",
        "Raise a maker's on-time rate on her trust card",
        "Each trust card is signed with Ed25519: one changed number breaks the signature",
    ),
)
BY_KEY = {attack.key: attack for attack in ATTACKS}


class Outcome(BaseModel):
    """What one attack tried, and what happened: refused (the guardrail held), got_through (it did not), or
    not_tried (the demo world was missing what it needs)."""

    key: str
    name: str
    guard: str
    tried: str
    result: Result
    reason: str


@dataclass(frozen=True)
class Tried:
    tried: str
    result: Result
    reason: str


async def run_attack(key: str, registry: AdapterRegistry) -> Outcome:
    """Try one attack, record its refusal in the feed, and say what happened. Raises KeyError for an unknown key."""
    attack = BY_KEY[key]
    try:
        tried = await _capture_tool() if key == "capture_tool" else SYNC_ATTACKS[key](registry)
    except NotTried as missing:
        tried = Tried("Nothing: the demo world is missing what this attack needs.", "not_tried", str(missing))
    if tried.result == "refused" and key != "forged_webhook":  # a forged webhook is recorded by webhooks.py itself
        with session_scope() as session:
            record_event(
                session,
                EventType.SECURITY_REJECTED,
                f"Guardrail held: {attack.name}. {tried.reason}",
                payload={"attack": key, "guard": attack.guard},
            )
    return Outcome(key=key, name=attack.name, guard=attack.guard, **tried.__dict__)


class NotTried(Exception):
    """The demo world is missing what an attack needs (for example, the seeded makers)."""


@contextmanager
def throwaway_order() -> Iterator[tuple[Session, Order]]:
    """The story's order, drafted in a transaction that is rolled back: nothing an attack does to it is kept, and no
    other page ever sees it."""
    with new_session() as session:
        try:
            try:
                order = story_order(session, quotes.clock.today())
            except Exception as error:  # the seeded makers are missing
                raise NotTried(f"The story's makers are not seeded ({type(error).__name__}).") from None
            yield session, order
        finally:
            session.rollback()


def _below_floor(registry: AdapterRegistry) -> Tried:
    with new_session() as session:
        product = session.scalars(
            select(Product)
            .where(Product.status == ProductStatus.LIVE, Product.data_source == DataSource.SEEDED_DEMO)
            .order_by(Product.id)
        ).first()
        if product is None or not product.seller.policy_json:
            raise NotTried("No seeded maker with her limits is live.")
        seller = product.seller
        policy, listing = seller_policy(seller, product), listing_of(product)
        today = quotes.clock.today()
        deadline = today + timedelta(days=30)
        offer = CoreOffer(seller_id=seller.id, unit_price=Decimal("1.00"), quantity=1, delivery_date=deadline)
        request = CoreRequest(quantity=1, max_unit_price=listing.price_usd, deadline=deadline)
        check = is_valid_offer(offer, policy, listing, request, today)
        lowest = lowest_allowed_price(policy, listing)
        tried = (
            f"A buyer tells {seller.name}'s agent to sell for $1.00, and it proposes $1.00 a unit for "
            f"“{product.title}”."
        )
    if check.valid:
        return Tried(tried, "got_through", "The offer check accepted $1.00.")
    return Tried(
        tried,
        "refused",
        f"Refused by code ({check.reason}): her lowest price is ${lowest:,.2f}, her floor or her list price less her "
        "largest discount. No agent can offer below it.",
    )


async def _capture_tool() -> Tried:
    tried = 'An AI agent connected to the MCP storefront calls "capture_payment" for the latest order.'
    async with Client(storefront) as mcp:
        names = sorted(tool.name for tool in (await mcp.list_tools()).tools)
        try:
            result = await mcp.call_tool("capture_payment", {"order_id": "ord_demo"})
            answered = not result.is_error
        except Exception:  # the client may raise for an unknown tool instead of answering with an error
            answered = False
    if answered:
        return Tried(tried, "got_through", "A tool called capture_payment answered.")
    return Tried(
        tried,
        "refused",
        f"Refused: there is no such tool. The storefront's {len(names)} tools ({', '.join(names)}) search, quote, "
        "draft and give an approval link; none can capture, refund or pay out.",
    )


def _changed_total(registry: AdapterRegistry) -> Tried:
    with throwaway_order() as (session, order):
        expected = server_total(order)
        claimed = expected - Decimal("100.00")
        tried = f"The browser asks to pay ${claimed:,.2f} for an order of ${expected:,.2f}."
        try:
            verify_total(order.id, TotalIn(total_usd=claimed), session)
        except HTTPException as refused:
            return Tried(tried, "refused", f"Refused (HTTP {refused.status_code}): {refused.detail}")
    return Tried(tried, "got_through", "The smaller total was accepted.")


def _forged_webhook(registry: AdapterRegistry) -> Tried:
    event = {
        "id": f"WH-FORGED-{uuid.uuid4().hex[:16].upper()}",
        "event_version": "1.0",
        "create_time": datetime.now(UTC).isoformat(),
        "resource_type": "capture",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "summary": "Payment completed for $815.00 USD",
        "resource": {
            "id": "FORGED-CAPTURE",
            "status": "COMPLETED",
            "amount": {"currency_code": "USD", "value": "815.00"},
        },
    }
    headers = {
        "paypal-transmission-id": str(uuid.uuid4()),
        "paypal-transmission-time": datetime.now(UTC).isoformat(),
        "paypal-transmission-sig": "Zm9yZ2Vk",
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-forged",
    }
    tried = "Someone posts a PayPal-shaped event, PAYMENT.CAPTURE.COMPLETED for $815.00, with a made-up signature."
    try:
        receive_paypal_webhook(json.dumps(event).encode(), headers)
    except WebhookRefused as refused:
        return Tried(tried, "refused", f"Refused: {refused}. Nothing changed.")
    except PaymentUnavailable:
        why = "Not applied: PayPal could not be asked to verify it right now. Nothing changed."
        return Tried(tried, "refused", why)
    return Tried(tried, "got_through", "The forged event was applied.")


def _reserve_unapproved(registry: AdapterRegistry) -> Tried:
    with throwaway_order() as (session, order):
        tried = f"A request asks OpenStall to reserve ${order.total_usd:,.2f} for a draft order nobody approved."
        try:
            reserve_order(session, order.id, registry.payment_gateway)
        except WrongStatus as refused:
            return Tried(tried, "refused", f"Refused: {refused} Only a person's approval at PayPal reserves money.")
    return Tried(tried, "got_through", "The order was reserved.")


def _pay_before_proof(registry: AdapterRegistry) -> Tried:
    with throwaway_order() as (session, order):
        part = order.parts[0]
        part.status = PartStatus.AUTHORIZED  # as if PayPal held it: reserved, and she has sent no proof
        session.flush()
        name, amount = part.seller.name, part.amount_usd
        tried = f"A request asks OpenStall to pay {name} her ${amount:,.2f} before she has shipped."
        try:
            pay_share(session, part.id, registry.payment_gateway)
        except WrongStatus as refused:
            return Tried(tried, "refused", f"Refused: {refused} Nothing was captured.")
    return Tried(tried, "got_through", "Her share was paid.")


def _tampered_passport(registry: AdapterRegistry) -> Tried:
    with new_session() as session:
        passport = session.scalars(
            select(Passport).where(Passport.data_source == DataSource.SEEDED_DEMO).order_by(Passport.seller_id)
        ).first()
        if passport is None:
            raise NotTried("No seeded maker has a trust passport.")
        card = trust_card(session, passport.seller_id).model_dump(mode="json")
        name = passport.seller.name
    signed = verify_card(card)
    was = float(card["on_time_rate"])
    card["on_time_rate"] = 0.99 if was < 0.99 else 1.0
    tried = (
        f"{name}'s signed trust card is sent with her on-time rate raised from {was:.2f} to "
        f"{card['on_time_rate']:.2f}."
    )
    if not signed:
        raise NotTried(f"{name}'s card does not check out even as signed: seed the demo world again.")
    if verify_card(card):
        return Tried(tried, "got_through", "The changed card checked out.")
    return Tried(
        tried,
        "refused",
        "Refused: the signature does not match. OpenStall signed her card as it was, and one changed number breaks "
        "it, for anyone who checks with the public key.",
    )


SYNC_ATTACKS: dict[str, Callable[[AdapterRegistry], Tried]] = {
    "below_floor": _below_floor,
    "changed_total": _changed_total,
    "forged_webhook": _forged_webhook,
    "reserve_unapproved": _reserve_unapproved,
    "pay_before_proof": _pay_before_proof,
    "tampered_passport": _tampered_passport,
}
assert set(SYNC_ATTACKS) | {"capture_tool"} == set(BY_KEY)
