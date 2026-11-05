"""Everything that happens when a seller writes, whichever way she writes: WhatsApp, the web chat, or fake mode
playing a seeded maker. One path, so every channel behaves the same.

1. Her photo is looked at first, outside any transaction (the vision model may take seconds), if she has a share
   waiting for proof of shipping (handler.look_at_photos).
2. Her message and the replies are stored in one transaction (handler.handle_inbound), and committed.
3. On WhatsApp the replies are sent through the Messenger; the web chat shows them from the answer.
4. Any share she proved she shipped is captured and paid (proof.pay_on_proof), now or as a background task.
"""

import logging
from collections.abc import Callable, Sequence
from typing import Any

from openstall_api.adapters import get_registry
from openstall_api.chat.handler import HandledMessage, InboundFile, Refused, Sender, handle_inbound, look_at_photos
from openstall_api.db import session_scope
from openstall_api.media import get_media_store
from openstall_api.models import Channel
from openstall_api.proof import pay_on_proof

log = logging.getLogger(__name__)

# How the caller runs follow-up work: FastAPI's BackgroundTasks.add_task, so the answer is not held up by PayPal.
Later = Callable[..., Any]


def receive(
    sender: Sender, text: str, files: Sequence[InboundFile | Refused], later: Later | None = None
) -> HandledMessage:
    """Handle one message from a seller, end to end. Without `later`, payments run before this returns."""
    registry = get_registry()
    photo = look_at_photos(sender, files, lambda: registry.llm)
    with session_scope() as session:
        handled = handle_inbound(session, get_media_store(), sender, text, files, photo)
    if sender.channel == Channel.WHATSAPP:
        messenger = registry.messenger
        for reply in handled.replies:
            try:
                messenger.send(f"whatsapp:{sender.address}", reply.text)
            except Exception:
                log.exception("A WhatsApp reply to seller %s could not be sent", handled.seller_id)
    for part_id in handled.pay_after:
        args = (part_id, lambda: registry.payment_gateway, lambda: registry.messenger)
        if later is not None:
            later(pay_on_proof, *args)
        else:
            pay_on_proof(*args)
    return handled
