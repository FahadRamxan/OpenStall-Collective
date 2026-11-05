"""The web chat: POST /api/seller-chat/messages, the same handler as WhatsApp, for sellers in the browser.

A web seller is known by a random "demo phone" id her browser keeps, so a judge can onboard a seller without
WhatsApp (spec section 10). Replies come back in the answer, and are stored like WhatsApp's.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from openstall_api.chat.handler import InboundFile, Refused, Sender
from openstall_api.chat.inbox import receive
from openstall_api.media import MAX_BYTES, media_type
from openstall_api.models import Channel
from openstall_api.settings import get_settings

router = APIRouter(prefix="/api/seller-chat", tags=["seller chat"])

DEMO_PHONE = r"^[A-Za-z0-9_-]{8,32}$"
MAX_FILES = 5
READ_CHUNK = 1024 * 1024
# Fake mode's samples (dev_api): a voice note it hears as Amina's words in Urdu, and a photo of her cushion cover.
SAMPLE_VOICE_NOTE = "/api/dev/samples/voice-note.wav"
SAMPLE_PHOTO = "/api/dev/samples/photo.png"


class WebChatReply(BaseModel):
    seller_id: str
    message_id: str
    replies: list[str]


class Samples(BaseModel):
    """Sample files the web chat can attach, as paths on this API. None where this mode has none."""

    voice_note: str | None
    photo: str | None


@router.get("/samples")
def samples() -> Samples:
    """In fake mode, the samples /seller-chat offers to attach. None in sandbox mode, where they would go to the real
    models: OpenAI would hear no words in the sample's hum, and Claude would see a drawn pattern. Always answers, so the
    page never logs a failed request."""
    fake = get_settings().OPENSTALL_MODE == "fake"
    return Samples(voice_note=SAMPLE_VOICE_NOTE if fake else None, photo=SAMPLE_PHOTO if fake else None)


async def read_upload(upload: UploadFile) -> InboundFile | Refused:
    """The file's bytes, read in pieces and refused as soon as it passes 16 MB."""
    kind = media_type(upload.content_type or "")
    chunks, size = [], 0
    while chunk := await upload.read(READ_CHUNK):
        size += len(chunk)
        if size > MAX_BYTES:
            return Refused("The file is over 16 MB; the most we keep is 16 MB.", kind)
        chunks.append(chunk)
    return InboundFile(b"".join(chunks), kind)


@router.post("/messages")
async def send_message(
    background: BackgroundTasks,
    sender: Annotated[str, Form(pattern=DEMO_PHONE)],
    text: Annotated[str, Form(max_length=4000)] = "",
    files: list[UploadFile] | None = None,
) -> WebChatReply:
    """A message from a seller in the web chat: text, photos and voice notes, handled exactly as on WhatsApp
    (chat/inbox.py). A share she proved she shipped is paid after the answer, and her chat shows it live."""
    uploads = files or []
    if len(uploads) > MAX_FILES:
        raise HTTPException(status_code=422, detail=f"Send at most {MAX_FILES} files at a time.")
    if not text.strip() and not uploads:
        raise HTTPException(status_code=422, detail="Write a message or attach a photo or voice note.")
    received: list[InboundFile | Refused] = [await read_upload(upload) for upload in uploads]
    # In a worker thread: a receipt photo is read by the vision model, which must not hold up the event loop.
    handled = await run_in_threadpool(
        receive, Sender(Channel.WEB, sender), text.strip(), received, background.add_task
    )
    return WebChatReply(
        seller_id=handled.seller_id, message_id=handled.message_id, replies=[reply.text for reply in handled.replies]
    )
