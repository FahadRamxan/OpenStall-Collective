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

router = APIRouter(prefix="/api/seller-chat", tags=["seller chat"])

DEMO_PHONE = r"^[A-Za-z0-9_-]{8,32}$"
MAX_FILES = 5
READ_CHUNK = 1024 * 1024


class WebChatReply(BaseModel):
    seller_id: str
    message_id: str
    replies: list[str]


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
