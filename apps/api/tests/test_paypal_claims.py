"""Duplicate claims: a PayPal write asked for twice at once is refused by our database, before it reaches PayPal.

A claim is released when PayPal refuses the call or never received it, is marked done once our own rows are saved,
and is marked unknown when the holder finished without PayPal's answer saved, so the next request for the same
write (with the same PayPal-Request-Id, which PayPal dedupes) goes ahead at once. A pending claim is taken over once
it is stale. On Postgres the claim is written in the caller's own transaction, so a request uses one connection.
"""

import logging
import threading
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from openstall_api import claims
from openstall_api.claims import STALE_AFTER, ClaimHeld, joins_callers_transaction, take_claim
from openstall_api.db import get_engine, new_session
from openstall_api.main import app
from openstall_api.models import ClaimState, Order, OrderPart, PartStatus, PayPalClaim, utcnow
from openstall_api.payments import pay_share, release_share
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order
from openstall_paypal import PaymentError, PaymentUnavailable

client = TestClient(app)


@pytest.fixture
def demo_order(db):
    seed(db, with_amina=True)
    seed_demo_order(db, date(2026, 11, 10))
    db.commit()
    return db


@pytest.fixture
def reserved(demo_order, fakes) -> dict[str, str]:
    """The demo order, approved and reserved through the API, with every share's tracking confirmed."""
    paypal_order_id = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    fakes.payment_gateway.approve(paypal_order_id)
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve").status_code == 200
    fakes.payment_gateway.calls.clear()
    demo_order.expire_all()
    parts = demo_order.get(Order, DEMO_ORDER_ID).parts
    for part in parts:
        part.tracking_number = "LP00123456789PK"
    demo_order.commit()
    return {part.seller_id: part.id for part in parts}


def claim_row(key: str) -> PayPalClaim | None:
    with new_session() as session:
        return session.get(PayPalClaim, key)


def hold_claim(
    db, key: str, *, age: timedelta = timedelta(0), state: ClaimState = ClaimState.PENDING, request_id: str = ""
) -> None:
    """Another request's claim, taken (and committed) on its own connection, `age` ago."""
    with new_session() as session:
        session.add(
            PayPalClaim(
                key=key,
                request_id=request_id or f"openstall-{key.replace(':', '-')}",
                state=state,
                holder="someone-else",
                claimed_at=utcnow() - age,
            )
        )
        session.commit()


def gateway_calls(fakes) -> list[str]:
    return [name for name, _ in fakes.payment_gateway.calls]


def test_a_payment_already_in_progress_elsewhere_is_refused_before_paypal(reserved, demo_order, fakes):
    amina = reserved["s_amina"]
    hold_claim(demo_order, f"capture:{amina}")

    with pytest.raises(ClaimHeld, match="Amina's share is being paid by another request"):
        pay_share(demo_order, amina, fakes.payment_gateway)

    assert gateway_calls(fakes) == []
    demo_order.rollback()
    assert demo_order.get(OrderPart, amina).status == PartStatus.AUTHORIZED


def test_the_api_answers_a_concurrent_duplicate_with_409(demo_order, fakes):
    paypal_order_id = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    fakes.payment_gateway.approve(paypal_order_id)
    fakes.payment_gateway.calls.clear()
    hold_claim(demo_order, f"reserve:{DEMO_ORDER_ID}")

    response = client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Order ord_demo is being reserved at PayPal by another request. Try again in a moment."
    )
    assert gateway_calls(fakes) == ["get_order"]  # read, but never reserved twice


def test_of_many_requests_racing_for_one_claim_exactly_one_wins(db):
    engine = get_engine()
    start = threading.Barrier(8)
    won: list[str] = []
    refused: list[str] = []

    def race(number: int) -> None:
        with new_session() as session:
            start.wait()
            try:
                take_claim(session, "capture:op_race", "openstall-capture-op_race", busy="busy")
                won.append(f"request {number}")
            except ClaimHeld:
                refused.append(f"request {number}")

    threads = [threading.Thread(target=race, args=(number,)) for number in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(won) == 1 and len(refused) == 7
    engine.dispose()


def test_a_claim_is_done_with_paypals_id_once_our_rows_are_saved(reserved, demo_order, fakes):
    amina = reserved["s_amina"]

    pay_share(demo_order, amina, fakes.payment_gateway)
    assert claim_row(f"capture:{amina}").state == ClaimState.PENDING  # PayPal answered; our rows are not saved yet
    demo_order.commit()

    row = claim_row(f"capture:{amina}")
    assert row.state == ClaimState.DONE
    assert row.result == demo_order.get(OrderPart, amina).capture_id
    assert row.request_id == f"openstall-capture-{amina}"


def test_a_claim_whose_rows_were_never_saved_is_unknown_and_the_next_try_goes_ahead(reserved, demo_order, fakes):
    amina = reserved["s_amina"]

    pay_share(demo_order, amina, fakes.payment_gateway)
    demo_order.rollback()
    assert claim_row(f"capture:{amina}").state == ClaimState.UNKNOWN

    pay_share(demo_order, amina, fakes.payment_gateway)  # the same PayPal-Request-Id: PayPal answers it once
    demo_order.commit()
    assert claim_row(f"capture:{amina}").state == ClaimState.DONE


def test_a_refused_call_releases_its_claim_so_the_next_try_goes_ahead(reserved, demo_order, fakes, monkeypatch):
    amina = reserved["s_amina"]
    real_pay_share = fakes.payment_gateway.pay_share

    def refused(share):
        raise PaymentError("INSTRUMENT_DECLINED", "declined")

    monkeypatch.setattr(fakes.payment_gateway, "pay_share", refused)
    with pytest.raises(PaymentError):
        pay_share(demo_order, amina, fakes.payment_gateway)
    demo_order.rollback()
    assert claim_row(f"capture:{amina}") is None

    monkeypatch.setattr(fakes.payment_gateway, "pay_share", real_pay_share)
    pay_share(demo_order, amina, fakes.payment_gateway)
    demo_order.commit()
    assert demo_order.get(OrderPart, amina).status == PartStatus.CAPTURED


def test_a_call_that_never_reached_paypal_releases_its_claim(reserved, demo_order, fakes, monkeypatch):
    lucia = reserved["s_lucia"]

    def never_sent(share):
        raise PaymentUnavailable("PAYPAL_UNAVAILABLE", "connection refused", outcome_unknown=False)

    monkeypatch.setattr(fakes.payment_gateway, "release_share", never_sent)
    with pytest.raises(PaymentUnavailable):
        release_share(demo_order, lucia, fakes.payment_gateway)

    assert claim_row(f"release:{lucia}") is None


def test_after_no_answer_the_next_try_goes_ahead_at_once_with_the_same_request_id(
    reserved, demo_order, fakes, monkeypatch
):
    """As before claims: PayPal dedupes on PayPal-Request-Id, so the repeat is answered with the first result."""
    amina = reserved["s_amina"]
    real_pay_share = fakes.payment_gateway.pay_share

    def no_answer(share):
        raise PaymentUnavailable("PAYPAL_UNAVAILABLE", "read timeout")  # outcome unknown

    monkeypatch.setattr(fakes.payment_gateway, "pay_share", no_answer)
    with pytest.raises(PaymentUnavailable):
        pay_share(demo_order, amina, fakes.payment_gateway)
    demo_order.rollback()
    row = claim_row(f"capture:{amina}")
    assert (row.state, row.request_id) == (ClaimState.UNKNOWN, f"openstall-capture-{amina}")

    monkeypatch.setattr(fakes.payment_gateway, "pay_share", real_pay_share)
    pay_share(demo_order, amina, fakes.payment_gateway)
    demo_order.commit()

    assert demo_order.get(OrderPart, amina).status == PartStatus.CAPTURED
    assert claim_row(f"capture:{amina}").state == ClaimState.DONE


def test_pressing_approve_again_after_paypal_did_not_answer_is_not_refused(demo_order, fakes, monkeypatch):
    real_create = fakes.payment_gateway.create_checkout

    def no_answer(request):
        raise PaymentUnavailable("PAYPAL_UNAVAILABLE", "read timeout")

    monkeypatch.setattr(fakes.payment_gateway, "create_checkout", no_answer)
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").status_code == 503
    monkeypatch.setattr(fakes.payment_gateway, "create_checkout", real_create)

    response = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout")

    assert response.status_code == 200
    assert claim_row(f"checkout:{DEMO_ORDER_ID}").state == ClaimState.DONE


def test_an_unknown_claim_for_a_different_request_id_waits_until_it_is_stale(reserved, demo_order, fakes):
    amina = reserved["s_amina"]
    hold_claim(demo_order, f"capture:{amina}", state=ClaimState.UNKNOWN, request_id="openstall-capture-older")

    with pytest.raises(ClaimHeld, match="PayPal did not answer an earlier attempt at this. Try again after"):
        pay_share(demo_order, amina, fakes.payment_gateway)
    assert gateway_calls(fakes) == []


def test_a_failure_to_mark_a_claim_after_the_commit_is_logged_not_raised(
    reserved, demo_order, fakes, monkeypatch, caplog
):
    """Our rows are saved by then: the commit must not turn into an error."""
    amina = reserved["s_amina"]

    def broken(claims_session, claim, state):
        raise RuntimeError("database is locked")

    pay_share(demo_order, amina, fakes.payment_gateway)
    monkeypatch.setattr(claims, "mark", broken)
    with caplog.at_level(logging.ERROR, logger="openstall_api.claims"):
        demo_order.commit()

    assert demo_order.get(OrderPart, amina).status == PartStatus.CAPTURED
    assert f"Could not mark PayPal claims capture:{amina}" in caplog.text


def test_on_postgres_the_claim_is_written_in_the_callers_own_transaction():
    engine = create_engine("postgresql+psycopg://u:p@db.example/openstall")  # never connected
    with Session(engine) as session:
        assert joins_callers_transaction(session)


def test_a_payment_request_whose_claim_joins_its_transaction_uses_one_connection(
    reserved, demo_order, fakes, monkeypatch
):
    """The Postgres path: no second pooled connection while the order's row is locked, and done with the commit."""
    amina = reserved["s_amina"]
    demo_order.close()  # hand the session's connection back, so the count starts from nothing
    monkeypatch.setattr(claims, "joins_callers_transaction", lambda session: True)
    checkouts: list[object] = []

    def count(*args: object) -> None:
        checkouts.append(args)

    engine = get_engine()
    event.listen(engine, "checkout", count)
    try:
        pay_share(demo_order, amina, fakes.payment_gateway)
        demo_order.commit()
    finally:
        event.remove(engine, "checkout", count)

    assert len(checkouts) == 1
    row = claim_row(f"capture:{amina}")
    assert (row.state, row.result) == (ClaimState.DONE, demo_order.get(OrderPart, amina).capture_id)


def test_a_stale_claim_left_by_a_crash_is_taken_over(reserved, demo_order, fakes):
    grace = reserved["s_grace"]
    hold_claim(demo_order, f"capture:{grace}", age=STALE_AFTER + timedelta(seconds=1))

    pay_share(demo_order, grace, fakes.payment_gateway)
    demo_order.commit()

    row = claim_row(f"capture:{grace}")
    assert (row.state, row.holder != "someone-else") == (ClaimState.DONE, True)
    assert demo_order.get(OrderPart, grace).status == PartStatus.CAPTURED
    assert gateway_calls(fakes) == ["pay_share"]


def test_a_claim_just_under_the_stale_age_still_blocks(reserved, demo_order, fakes):
    grace = reserved["s_grace"]
    hold_claim(demo_order, f"capture:{grace}", age=STALE_AFTER - timedelta(seconds=5))

    with pytest.raises(ClaimHeld):
        pay_share(demo_order, grace, fakes.payment_gateway)


def test_pressing_approve_again_takes_over_the_finished_checkout_claim(demo_order, fakes):
    first = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()
    second = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()

    assert first["paypal_order_id"] == second["paypal_order_id"]
    row = claim_row(f"checkout:{DEMO_ORDER_ID}")
    assert (row.state, row.result) == (ClaimState.DONE, first["paypal_order_id"])


def test_with_writes_pending_on_sqlite_the_claim_is_taken_inside_the_callers_transaction(reserved, demo_order, fakes):
    """SQLite has one writer: a claim on another connection would wait for this transaction, so it joins it."""
    amina = reserved["s_amina"]
    demo_order.get(OrderPart, amina).tracking_number = "LP00999999999PK"  # an unsaved change, flushed by the load

    pay_share(demo_order, amina, fakes.payment_gateway)
    demo_order.rollback()

    assert claim_row(f"capture:{amina}") is None  # undone with the caller's transaction
    assert gateway_calls(fakes) == ["pay_share"]


def test_every_claim_is_keyed_by_what_it_is_for(reserved, demo_order, fakes):
    pay_share(demo_order, reserved["s_amina"], fakes.payment_gateway)
    release_share(demo_order, reserved["s_lucia"], fakes.payment_gateway)
    demo_order.commit()

    with new_session() as session:
        keys = set(session.scalars(select(PayPalClaim.key)))
    assert keys == {
        f"checkout:{DEMO_ORDER_ID}",
        f"reserve:{DEMO_ORDER_ID}",
        f"capture:{reserved['s_amina']}",
        f"release:{reserved['s_lucia']}",
    }
