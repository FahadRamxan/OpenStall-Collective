"""WhatsApp over HTTP: Twilio's webhook, and in fake mode a way to play a seller sending a message.

The webhook answers Twilio at once with an empty TwiML reply, after checking the signature and that the message is
new. Fetching the media and handling the message happen in a background task, so Twilio never waits on them; the
replies go back through the Messenger.
"""

import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from openstall_api.chat.handler import HandledMessage, InboundFile, Refused, Sender, country_of
from openstall_api.chat.inbox import receive
from openstall_api.db import session_scope
from openstall_api.events import EventType, record_event
from openstall_api.events_api import fake_mode_only
from openstall_api.fixtures import demo_shipment, fixture_photo, fixture_receipt, fixture_voice_note
from openstall_api.media import MediaRejected, media_type
from openstall_api.models import Channel, ProcessedWebhook
from openstall_api.settings import get_settings
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


def first_time(message_sid: str) -> bool:
    """Whether this message is new. Twilio sends a message again when an answer is slow or lost."""
    if not message_sid:
        return True
    try:
        with session_scope() as session:
            session.add(ProcessedWebhook(provider="twilio", event_id=f"twilio:{message_sid}"[:128], payload_json={}))
    except IntegrityError:
        return False
    return True


def record_refusal() -> None:
    with session_scope() as session:
        record_event(session, EventType.SECURITY_REJECTED, "A WhatsApp webhook without Twilio's signature was refused")


def deliver_inbound(sender: Sender, text: str, files: list[InboundFile | Refused]) -> HandledMessage:
    """Handle a seller's message, then send the replies on WhatsApp (chat/inbox.py). A reply that fails to send is
    logged; the message and the reply are still stored. A share she proved she shipped is paid before this returns:
    it already runs in a background task, after Twilio has its answer."""
    return receive(sender, text, files)


def process_whatsapp_inbound(inbound: InboundMessage) -> None:
    """The slow part, after Twilio has its answer: fetch each file, then handle the message."""
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


@router.post("/api/dev/inbound", dependencies=[Depends(fake_mode_only)], status_code=201)
def dev_inbound(body: DevInbound) -> DevInboundOut:
    """Fake mode: as if a seller sent this on WhatsApp. It takes the webhook's own path once the files are in."""
    files: list[InboundFile | Refused] = []
    if body.photo:
        files.append(InboundFile(fixture_photo(), "image/png"))
    if body.voice_note:
        files.append(InboundFile(fixture_voice_note(), "audio/wav"))
    if body.receipt:
        files.append(InboundFile(fixture_receipt(*demo_shipment(country_of(body.sender))), "image/png"))
    handled = deliver_inbound(Sender(Channel.WHATSAPP, body.sender, body.profile_name), body.text, files)
    return DevInboundOut(
        seller_id=handled.seller_id, message_id=handled.message_id, replies=[reply.text for reply in handled.replies]
    )
