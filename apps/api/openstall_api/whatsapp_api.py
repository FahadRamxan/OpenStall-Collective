"""WhatsApp over HTTP: Twilio's webhook, Meta's (the WhatsApp Cloud API), Whapi.Cloud's, and in fake mode a way to
play a seller sending a message.

Each webhook answers at once, after checking the request is the provider's (Twilio's and Meta's signatures, the
secret in Whapi's address) and that the message is new: Twilio with an empty TwiML reply, Meta and Whapi with a plain
200. Fetching the media and handling the message happen in a background task, so no provider waits on them; the
replies go back through the Messenger, the provider WHATSAPP_PROVIDER names. What became of each reply, as Meta and
Whapi tell it later, is kept on it (record_status).
"""

import hmac
import json
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from openstall_api.chat.handler import HandledMessage, InboundFile, Refused, Sender
from openstall_api.chat.store import TEXT, apply_delivery, country_of, record_undelivered
from openstall_api.chat.inbox import receive
from openstall_api.db import new_session, session_scope
from openstall_api.limits import TooMany, check
from openstall_api.events import EventType, record_event
from openstall_api.events_api import fake_mode_only
from openstall_api.fixtures import demo_shipment, fixture_photo, fixture_receipt, fixture_voice_note
from openstall_api.proof import unused_shipment
from openstall_api.media import MediaRejected, media_type
from openstall_api.meta_whatsapp import (
    MetaInbound,
    MetaStatus,
    download_meta_media,
    meta_app_secret,
    meta_verify_token,
    parse_meta_inbound,
    parse_meta_statuses,
    valid_meta_request,
)
from openstall_api.models import (
    Channel,
    ChatMessage,
    ChatSession,
    Delivery,
    Direction,
    ProcessedWebhook,
    Seller,
    WhatsAppSend,
)
from openstall_api.settings import Settings, get_settings
from openstall_api.whapi_whatsapp import (
    WhapiInbound,
    WhapiStatus,
    channel_matches,
    download_whapi_media,
    parse_whapi_inbound,
    parse_whapi_statuses,
    starts_with,
    valid_whapi_secret,
    whapi_webhook_secret,
)
from openstall_api.whatsapp import (
    EMPTY_TWIML,
    InboundMessage,
    download_media,
    parse_inbound,
    twilio_token,
    valid_twilio_request,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["whatsapp"])


def public_url(request: Request) -> str:
    """The URL Twilio called, which it signed: our public address plus the path, not the one the server sees."""
    url = get_settings().PUBLIC_BASE_URL + request.url.path
    return f"{url}?{request.url.query}" if request.url.query else url


def first_time(message_sid: str, provider: str = "twilio") -> bool:
    """Whether this message is new. Twilio and Meta both send a message again when an answer is slow or lost."""
    if not message_sid:
        return True
    try:
        with session_scope() as session:
            event_id = f"{provider}:{message_sid}"[:128]
            session.add(ProcessedWebhook(provider=provider, event_id=event_id, payload_json={}))
    except IntegrityError:
        return False
    return True


def record_refusal(provider: str = "Twilio", missing: str = "signature", summary: str | None = None) -> None:
    with session_scope() as session:
        record_event(
            session,
            EventType.SECURITY_REJECTED,
            summary or f"A WhatsApp webhook without {provider}'s {missing} was refused",
        )


def deliver_inbound(sender: Sender, text: str, files: list[InboundFile | Refused]) -> HandledMessage:
    """Handle a seller's message, then send the replies on WhatsApp (chat/inbox.py). A reply that fails to send is
    logged; the message and the reply are still stored. A share she proved she shipped is paid before this returns:
    it already runs in a background task, after Twilio has its answer."""
    return receive(sender, text, files)


def process_whatsapp_inbound(inbound: InboundMessage) -> None:
    """The slow part, after Twilio has its answer: fetch each file, then handle the message. A sender over her
    limit is dropped before any file is fetched or read (limits.py); Twilio already has its answer."""
    try:
        check("chat", f"whatsapp:{inbound.sender}")
    except TooMany as error:
        log.warning("A WhatsApp message was dropped: %s", error)
        return
    files: list[InboundFile | Refused] = []
    if inbound.media:
        with httpx.Client(timeout=20.0) as http:
            for item in inbound.media:
                try:
                    data, kind = download_media(item, get_settings(), http)
                    files.append(InboundFile(data, kind))
                except MediaRejected as error:
                    files.append(Refused(str(error), media_type(item.content_type)))
                except httpx.HTTPError:
                    files.append(Refused("It could not be fetched from WhatsApp.", media_type(item.content_type)))
    deliver_inbound(Sender(Channel.WHATSAPP, inbound.sender, inbound.profile_name), inbound.text, files)


@router.post("/api/webhooks/twilio")
async def twilio_webhook(request: Request, background: BackgroundTasks) -> Response:
    form = await request.form()
    params = [(name, value) for name, value in form.multi_items() if isinstance(value, str)]
    signature = request.headers.get("X-Twilio-Signature", "")
    if not valid_twilio_request(public_url(request), params, signature, twilio_token(get_settings())):
        await run_in_threadpool(record_refusal)
        raise HTTPException(status_code=403, detail="Refused: Twilio did not sign this request.")
    inbound = parse_inbound(dict(params))
    if inbound.sender and await run_in_threadpool(first_time, inbound.message_sid):
        background.add_task(process_whatsapp_inbound, inbound)
    return Response(EMPTY_TWIML, media_type="text/xml")


def process_meta_inbound(inbound: MetaInbound) -> None:
    """Meta's slow part, after it has its answer: fetch her file from Graph API, then handle the message, as for
    Twilio. A sender over her limit is dropped before any file is fetched or read."""
    try:
        check("chat", f"whatsapp:{inbound.sender}")
    except TooMany as error:
        log.warning("A WhatsApp message was dropped: %s", error)
        return
    files: list[InboundFile | Refused] = []
    if inbound.media:
        with httpx.Client(timeout=20.0) as http:
            for item in inbound.media:
                try:
                    data, kind = download_meta_media(item, get_settings(), http)
                    files.append(InboundFile(data, kind))
                except MediaRejected as error:
                    files.append(Refused(str(error), media_type(item.content_type)))
                except (httpx.HTTPError, KeyError, ValueError):
                    files.append(Refused("It could not be fetched from WhatsApp.", media_type(item.content_type)))
    deliver_inbound(Sender(Channel.WHATSAPP, inbound.sender, inbound.profile_name), inbound.text, files)


def record_status(provider: str, status: MetaStatus | WhapiStatus) -> None:
    """What became of a message of ours, as the provider tells it after its 200 to the send (which only meant it took
    the message): kept on the message's send, so her chat on the pages shows whether it was delivered and read
    (apply_delivery). One that could not be delivered is also logged with the provider's reasons and recorded once
    for the live feed, which makes her chat on the pages look again."""
    failed = status.status == Delivery.FAILED
    if failed and not first_time(f"status:{status.message_id}:failed", provider):
        return  # the provider sent this failure again
    with session_scope() as session:
        send = apply_delivery(session, status.message_id, status.status, status.reason)
        if not failed:
            return
        log.warning(
            "WhatsApp could not deliver message %s to %s: %s", status.message_id, status.recipient, status.reason
        )
        if send is not None:
            if any(other.status == Delivery.FAILED for other in send.message.sends if other is not send):
                return  # its other part's failure is in the feed already: one line per message
            record_undelivered(session, send.message, status.reason, provider_message_id=status.message_id)
            return
        # A message from before sends were kept, named by her number. One to anyone else is not OpenStall's: a Whapi
        # number's owner writing to a friend.
        seller = (
            session.scalar(select(Seller).where(Seller.whatsapp_number == status.recipient))
            if status.recipient
            else None
        )
        if seller is not None:
            record_undelivered(session, None, status.reason, provider_message_id=status.message_id, seller=seller)


def may_answer(inbound: WhapiInbound, settings: Settings) -> bool:
    """Whether OpenStall may answer this sender on Whapi. A Whapi channel is often someone's own WhatsApp number, so
    only a maker who began with the start word (her link to OpenStall writes it for her) is answered: this message
    starts with it, or one she sent before did. Anyone else, such as a friend writing to the number's owner, is left
    alone: nothing of theirs is kept, read or sent anywhere. WHAPI_ANSWER_EVERYONE answers all, for a number that is
    OpenStall's alone."""
    start_word = settings.WHAPI_START_WORD
    if settings.WHAPI_ANSWER_EVERYONE or starts_with(inbound.text, start_word):
        return True
    with new_session() as session:
        said = session.scalars(
            select(ChatMessage.text)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .join(Seller, Seller.id == ChatSession.seller_id)
            .where(
                Seller.whatsapp_number == inbound.sender,
                ChatSession.channel == Channel.WHATSAPP,
                ChatMessage.direction == Direction.INBOUND,
            )
        )
        return any(starts_with(text or "", start_word) for text in said)


def process_whapi_inbound(inbound: WhapiInbound) -> None:
    """Whapi's slow part, after it has its answer: fetch her file with the channel's token, then handle the message,
    as for Twilio and Meta. A sender over her limit is dropped before any file is fetched or read."""
    try:
        check("chat", f"whatsapp:{inbound.sender}")
    except TooMany as error:
        log.warning("A WhatsApp message was dropped: %s", error)
        return
    files: list[InboundFile | Refused] = []
    if inbound.media:
        with httpx.Client(timeout=30.0) as http:
            for item in inbound.media:
                try:
                    data, kind = download_whapi_media(item, get_settings(), http)
                    files.append(InboundFile(data, kind))
                except MediaRejected as error:
                    files.append(Refused(str(error), media_type(item.content_type)))
                except httpx.HTTPError:
                    files.append(Refused("It could not be fetched from WhatsApp.", media_type(item.content_type)))
    deliver_inbound(Sender(Channel.WHATSAPP, inbound.sender, inbound.profile_name), inbound.text, files)


@router.get("/api/webhooks/whapi/{secret}", response_class=PlainTextResponse)
def whapi_webhook_check(secret: str) -> str:
    """Our Whapi webhook's address answers when its secret is right, for Whapi's "Check webhook"."""
    if not valid_whapi_secret(secret, whapi_webhook_secret(get_settings())):
        raise HTTPException(status_code=403, detail="Refused: this is not our Whapi webhook's address.")
    return "OK"


@router.post("/api/webhooks/whapi/{secret}")
async def whapi_webhook(secret: str, request: Request, background: BackgroundTasks) -> Response:
    """Whapi's WhatsApp events, at an address only Whapi was given (Whapi signs nothing): each new message from a
    seller is handled in the background, and what became of each message of ours is kept on it (record_status)."""
    settings = get_settings()
    if not valid_whapi_secret(secret, whapi_webhook_secret(settings)):
        await run_in_threadpool(record_refusal, "Whapi", "secret")
        raise HTTPException(status_code=403, detail="Refused: this is not our Whapi webhook's address.")
    try:
        payload = json.loads(await request.body())
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Refused: the body is not JSON.") from error
    events = payload if isinstance(payload, dict) else {}
    if not channel_matches(events, settings):
        await run_in_threadpool(
            record_refusal, "Whapi", "channel", "A WhatsApp webhook from another Whapi channel was refused"
        )
        raise HTTPException(status_code=403, detail="Refused: these events are from another Whapi channel.")
    for inbound in parse_whapi_inbound(events):
        if not await run_in_threadpool(may_answer, inbound, settings):
            continue  # not a maker, such as a friend writing to the number's owner: left alone
        if await run_in_threadpool(first_time, inbound.message_id, "whapi"):
            background.add_task(process_whapi_inbound, inbound)
    for status in parse_whapi_statuses(events):
        background.add_task(record_status, "whapi", status)
    return PlainTextResponse("OK")


@router.get("/api/webhooks/whatsapp", response_class=PlainTextResponse)
def meta_webhook_check(
    mode: Annotated[str, Query(alias="hub.mode")] = "",
    token: Annotated[str, Query(alias="hub.verify_token")] = "",
    challenge: Annotated[str, Query(alias="hub.challenge", max_length=200)] = "",
) -> str:
    """Meta checks the webhook's address once: our verify token back means it is ours, and we echo its challenge."""
    expected = meta_verify_token(get_settings())
    if mode != "subscribe" or not expected or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Refused: the verify token does not match.")
    return challenge


@router.post("/api/webhooks/whatsapp")
async def meta_webhook(request: Request, background: BackgroundTasks) -> Response:
    """Meta's WhatsApp events: each new message from a seller is handled in the background, and what became of each
    message of ours (delivered, read, or could not be delivered and why) is kept on it (record_meta_status)."""
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not valid_meta_request(body, signature, meta_app_secret(get_settings())):
        await run_in_threadpool(record_refusal, "Meta")
        raise HTTPException(status_code=403, detail="Refused: Meta did not sign this request.")
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Refused: the body is not JSON.") from error
    events = payload if isinstance(payload, dict) else {}
    for inbound in parse_meta_inbound(events):
        if await run_in_threadpool(first_time, inbound.message_id, "meta"):
            background.add_task(process_meta_inbound, inbound)
    for status in parse_meta_statuses(events):
        background.add_task(record_status, "meta", status)
    return PlainTextResponse("EVENT_RECEIVED")


class DevInbound(BaseModel):
    """A WhatsApp message to play in fake mode, with a made-up photo, voice note or courier receipt photo if asked."""

    sender: Annotated[str, Field(pattern=r"^\+\d{7,15}$")] = "+923001234567"
    profile_name: Annotated[str | None, Field(max_length=120)] = "Amina"
    text: Annotated[str, Field(max_length=4000)] = ""
    photo: bool = False
    voice_note: bool = False
    # Fake mode's courier receipt photo, with a made-up courier and tracking number for her number's country.
    receipt: bool = False


class DevInboundOut(BaseModel):
    seller_id: str
    message_id: str
    replies: list[str]
    # Each reply's WhatsApp id, as the fake messenger gave it, in order: what Meta's status for it would name.
    reply_whatsapp_ids: list[str] = Field(default_factory=list)


@router.post("/api/dev/inbound", dependencies=[Depends(fake_mode_only)], status_code=201)
def dev_inbound(body: DevInbound) -> DevInboundOut:
    """Fake mode: as if a seller sent this on WhatsApp. It takes the webhook's own path once the files are in."""
    files: list[InboundFile | Refused] = []
    if body.photo:
        files.append(InboundFile(fixture_photo(), "image/png"))
    if body.voice_note:
        files.append(InboundFile(fixture_voice_note(), "audio/wav"))
    if body.receipt:
        with new_session() as session:  # a parcel's own number, as a courier's: one receipt pays one share
            shipment = unused_shipment(session, *demo_shipment(country_of(body.sender)))
        files.append(InboundFile(fixture_receipt(*shipment), "image/png"))
    handled = deliver_inbound(Sender(Channel.WHATSAPP, body.sender, body.profile_name), body.text, files)
    with session_scope() as session:
        sent = session.execute(
            select(WhatsAppSend.message_id, WhatsAppSend.provider_id).where(
                WhatsAppSend.message_id.in_(handled.reply_ids), WhatsAppSend.part == TEXT
            )
        ).all()
    by_message = {message_id: provider_id for message_id, provider_id in sent if provider_id}
    return DevInboundOut(
        seller_id=handled.seller_id,
        message_id=handled.message_id,
        replies=[reply.text for reply in handled.replies],
        reply_whatsapp_ids=[by_message[message_id] for message_id in handled.reply_ids if message_id in by_message],
    )
