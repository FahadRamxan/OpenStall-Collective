"""Duplicate claims for PayPal writes: the same checkout, reserve, capture or void asked for twice at once.

Before the SDK call, the write is claimed: a row in paypal_claims, keyed by what it is for ("capture:op_1"). A second
caller's insert fails on the primary key, so it is refused by the database before it can reach PayPal, whichever
process or host it runs in. Where the row is written depends on the database:

- Postgres: inside the caller's own transaction (a savepoint), so a payment request uses one pooled connection, not
  two. That is just as exclusive: each flow first locks the order's row (payments.load_order, SELECT ... FOR
  UPDATE), so a second request for the same order waits there and then finds our stored result; and an uncommitted
  insert of a key blocks any other insert of it until its transaction ends. The claim is saved, done, with the
  caller's rows, or undone with them; a request that dies mid-call releases its lock and its claim with its
  connection, and the next try carries the same PayPal-Request-Id, so PayPal answers it with the first result.
- SQLite: it takes no row locks, so the claim is inserted and committed on a connection of its own and is what
  keeps a second request out. If the caller's transaction has already written, a claim on another connection would
  wait for it, while nobody else can write until it ends; so then it joins the caller's transaction too.

A claim committed on its own connection then ends one of three ways:

- PayPal answered and the caller saved its rows: the claim becomes done (after the caller's commit), so a done
  claim always means our rows have the result.
- PayPal refused (PaymentError), or the request provably never left (PaymentUnavailable with outcome_unknown
  False): the claim is released (deleted), so the next attempt may go ahead.
- The holder is finished, but PayPal's answer is not saved: no answer, so it may have landed (outcome_unknown
  True), or the caller did not commit. The claim becomes unknown. The next request for the same write, carrying
  the same PayPal-Request-Id, takes it over at once: PayPal dedupes on that id, so a repeat is answered with the
  first result if the first landed, exactly as a repeat was before claims existed.

A pending claim is one whose holder is still calling PayPal. If its process stopped mid-call, it is taken over once
older than STALE_AFTER. A done claim is taken over by the next caller: the services return a stored result before
they get this far, so that is a deliberate repeat, such as pressing Approve again (PayPal gives back the same order).
Every takeover is a compare-and-set on the holder's token, so two callers can never both take one claim.
"""

import logging
import secrets
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, Engine, delete, event, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, SessionTransaction

from openstall_api.models import ClaimState, PayPalClaim, utcnow
from openstall_paypal import PaymentError, PaymentUnavailable

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=2)

Writer = Callable[[], AbstractContextManager[Session]]


class ClaimHeld(ValueError):
    """This PayPal write cannot be sent right now (another request is sending it). Refused with 409."""


@dataclass
class Claim:
    key: str
    holder: str
    inside: bool  # taken inside the caller's transaction (Postgres, or SQLite with writes pending), not on its own
    result: str | None = None  # set by the caller once PayPal answers: PayPal's id for what was made


def engine_of(session: Session) -> Engine:
    """The engine behind a request's session: claims go to the same database."""
    bind = session.get_bind()
    return bind if isinstance(bind, Engine) else bind.engine


def aware(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes; ours are all UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def joins_callers_transaction(session: Session) -> bool:
    """Whether the claim is written in the caller's own transaction: always, except on SQLite before the caller has
    written (the sqlite3 driver only begins a transaction before its first write, so an open one means it has)."""
    if engine_of(session).dialect.name != "sqlite":
        return True
    if not session.in_transaction():
        return False
    return bool(getattr(session.connection().connection.dbapi_connection, "in_transaction", False))


@contextmanager
def own_transaction(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session
        session.commit()


@contextmanager
def savepoint(session: Session) -> Iterator[Session]:
    with session.begin_nested():
        yield session


def writer_for(session: Session, inside: bool) -> Writer:
    if inside:
        return lambda: savepoint(session)
    engine = engine_of(session)
    return lambda: own_transaction(engine)


def take_claim(session: Session, key: str, request_id: str, *, busy: str) -> Claim:
    """Claim `key` for the caller's session, or raise ClaimHeld if it cannot be sent now: `busy` while another
    request holds it."""
    inside = joins_callers_transaction(session)
    writes = writer_for(session, inside)
    holder = secrets.token_hex(8)
    now = utcnow()
    try:
        with writes() as claims:
            claims.add(
                PayPalClaim(key=key, request_id=request_id, state=ClaimState.PENDING, holder=holder, claimed_at=now)
            )
            claims.flush()
        return Claim(key, holder, inside)
    except IntegrityError:  # the store refuses the second claim on this key
        pass
    with writes() as claims:
        existing = claims.get(PayPalClaim, key, populate_existing=True)
        if existing is None:  # released between our insert and this read: the caller may simply try again
            raise ClaimHeld(busy)
        claimed_before = aware(existing.claimed_at)
        stale = claimed_before <= now - STALE_AFTER
        if existing.state == ClaimState.PENDING and not stale:
            raise ClaimHeld(busy)
        if existing.state == ClaimState.UNKNOWN and existing.request_id != request_id and not stale:
            # Only the same PayPal-Request-Id is answered with the first result; a new one waits until stale.
            until = claimed_before + STALE_AFTER
            raise ClaimHeld(f"PayPal did not answer an earlier attempt at this. Try again after {until:%H:%M} UTC.")
        previous_state, previous = existing.state, existing.holder
        taken = cast(
            CursorResult[Any],
            claims.execute(
                update(PayPalClaim)
                .where(PayPalClaim.key == key, PayPalClaim.holder == previous)
                .values(
                    state=ClaimState.PENDING,
                    holder=holder,
                    request_id=request_id,
                    result=None,
                    claimed_at=now,
                    finished_at=None,
                )
                .execution_options(synchronize_session=False)
            ),
        )
    if taken.rowcount != 1:  # someone else took it over first
        raise ClaimHeld(busy)
    if previous_state == ClaimState.PENDING:
        log.warning("Took over a stale PayPal claim %s, claimed at %s", key, claimed_before.isoformat())
    elif previous_state == ClaimState.UNKNOWN:
        log.info("Sending %s again with the same PayPal-Request-Id; PayPal did not answer the last attempt", key)
    return Claim(key, holder, inside)


def release(claims: Session, claim: Claim) -> None:
    """Give the claim back: PayPal refused the call, or never received it."""
    claims.execute(
        delete(PayPalClaim)
        .where(PayPalClaim.key == claim.key, PayPalClaim.holder == claim.holder)
        .execution_options(synchronize_session=False)
    )


def mark(claims: Session, claim: Claim, state: ClaimState) -> None:
    """The holder is finished: done (with PayPal's id), or unknown (PayPal's answer is not saved)."""
    claims.execute(
        update(PayPalClaim)
        .where(PayPalClaim.key == claim.key, PayPalClaim.holder == claim.holder)
        .values(state=state, result=claim.result if state == ClaimState.DONE else None, finished_at=utcnow())
        .execution_options(synchronize_session=False)
    )


def settle(session: Session, claim: Claim, outcome: Callable[[Session], None]) -> None:
    """Record how a failed call ended. A failure to record it is logged, never raised: the caller is already
    raising the call's own error, which says more, and a claim left pending is taken over once it is stale."""
    try:
        with writer_for(session, claim.inside)() as claims:
            outcome(claims)
    except Exception:
        log.exception("Could not record how the PayPal call for claim %s ended", claim.key)


# Claims committed on their own connection, to mark done or unknown when the caller's transaction ends.
WAITING = "openstall_paypal_claims_waiting"
COMMITTED = "openstall_paypal_claims_committed"


def complete(session: Session, claim: Claim) -> None:
    """Record that PayPal answered, and with what, once the caller's own rows are saved."""
    if claim.inside:  # saved, or undone, with the caller's transaction
        with savepoint(session) as claims:
            mark(claims, claim, ClaimState.DONE)
        return
    session.info.setdefault(WAITING, []).append(claim)


# SQLAlchemy calls after_commit, then after_transaction_end, for every transaction, savepoints included. A claim
# waits for its caller's own transaction to end, not a savepoint's: done if it committed, unknown if not.


@event.listens_for(Session, "after_commit")
def _note_commit(session: Session) -> None:
    if session.info.get(WAITING):
        session.info[COMMITTED] = True


@event.listens_for(Session, "after_transaction_end")
def _finish_claims(session: Session, transaction: SessionTransaction) -> None:
    waiting: list[Claim] | None = session.info.get(WAITING)
    if not waiting:
        return
    committed = session.info.pop(COMMITTED, False)
    if transaction.parent is not None:  # a savepoint ended, not the caller's transaction
        return
    del session.info[WAITING]
    state = ClaimState.DONE if committed else ClaimState.UNKNOWN
    try:
        with own_transaction(engine_of(session)) as claims:
            for claim in waiting:
                mark(claims, claim, state)
    except Exception:
        # Our rows are already saved (or rolled back); raising here would turn that commit into an error. A claim
        # left pending is taken over once it is stale.
        log.exception("Could not mark PayPal claims %s", ", ".join(claim.key for claim in waiting))


@contextmanager
def paypal_claim(session: Session, key: str, request_id: str, *, busy: str) -> Iterator[Claim]:
    """Claim, run the PayPal call in the block, then record the result, release the claim, or mark it unknown.

    Only the write's own outcome decides: the block must re-raise the write's error, not a later read's.
    """
    claim = take_claim(session, key, request_id, busy=busy)
    try:
        yield claim
    except PaymentUnavailable as error:
        if error.outcome_unknown:  # it may have landed: a repeat must carry the same PayPal-Request-Id
            settle(session, claim, lambda claims: mark(claims, claim, ClaimState.UNKNOWN))
        else:
            settle(session, claim, lambda claims: release(claims, claim))
        raise
    except PaymentError:
        settle(session, claim, lambda claims: release(claims, claim))
        raise
    complete(session, claim)
