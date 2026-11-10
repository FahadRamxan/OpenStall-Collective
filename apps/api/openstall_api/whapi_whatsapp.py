"""WhatsApp through Whapi.Cloud (gate.whapi.cloud): a WhatsApp number linked to Whapi as a device. Its webhook, the
inbound message, its media, what became of each message we sent, and sending.

Whapi signs nothing, so the webhook address carries a secret of ours in its path: PUBLIC_BASE_URL +
/api/webhooks/whapi/{WHAPI_WEBHOOK_SECRET}. Each event is JSON: "messages" for new messages (ours come back too, as
from_me, and are left out) and "statuses" for what became of ours. A photo or voice note arrives as a media id,
fetched from /media/{id} with the channel's token. Replies go to /messages/text, and a spoken answer to
/messages/voice as a link to our public copy, which Whapi converts for WhatsApp.

A Whapi number is often someone's own WhatsApp, which friends write to as well. So OpenStall answers only a maker who
began with the start word (WHAPI_START_WORD, "Start", which her link to OpenStall writes for her); anyone else is left
alone, and nothing of theirs is kept, read or sent anywhere (whatsapp_api.may_answer).

In fake mode, with no Whapi channel, the webhook's secret is FAKE_WHAPI_WEBHOOK_SECRET. It is public, which is fine:
fake mode sends nothing to anyone.
"""

import hmac
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from openstall_api.media import MAX_BYTES, MediaRejected, media_type
from openstall_api.messaging import SentMessage
from openstall_api.meta_whatsapp import IMAGE_SUFFIXES, meta_error
from openstall_api.settings import Settings
from openstall_api.whatsapp import MessengerError

log = logging.getLogger(__name__)

FAKE_WHAPI_WEBHOOK_SECRET = "openstall-fake-mode-whapi-webhook-secret"
# Whapi's quick reply buttons: at most 3, each title up to 25 characters (Meta's are 20, which ours keep to).
MAX_BUTTON_TITLE = 25
# The kinds of message that carry one file. A voice note is "voice"; a sound file sent as such is "audio".
FILE_KINDS = ("image", "voice", "audio", "video", "document", "sticker")
# Whapi's statuses, as OpenStall keeps them: "played" (she listened to a voice note) counts as read; "pending" is
# not kept, as the send's own answer already said Whapi took it.
STATUSES = {"sent": "sent", "delivered": "delivered", "read": "read", "played": "read", "failed": "failed"}
# Chats that are not one person's: a group, a channel, and WhatsApp's status updates.
NOT_A_PERSON = ("@g.us", "@newsletter", "@broadcast")


def _secret(value: Any) -> str | None:
    return value.get_secret_value() or None if value is not None else None


def whapi_webhook_secret(settings: Settings) -> str | None:
    """The secret in Whapi's webhook address: ours, or in fake mode the public fake one."""
    configured = _secret(settings.WHAPI_WEBHOOK_SECRET)
    return configured or (FAKE_WHAPI_WEBHOOK_SECRET if settings.OPENSTALL_MODE == "fake" else None)


def valid_whapi_secret(given: str, expected: str | None) -> bool:
    return bool(expected) and hmac.compare_digest(given.encode(), (expected or "").encode())


@dataclass(frozen=True)
class WhapiMedia:
    media_id: str
    content_type: str
    size: int = 0  # bytes, as Whapi says, or 0 when it does not


@dataclass(frozen=True)
class WhapiInbound:
    """One WhatsApp message to our number, as Whapi describes it."""

    message_id: str  # the same when Whapi sends it again
    sender: str  # E.164, such as +923001234567
    profile_name: str | None  # the name on her WhatsApp profile: a first guess at her name
    text: str
    media: tuple[WhapiMedia, ...]


@dataclass(frozen=True)
class WhapiStatus:
    """What became of a message we sent, as Whapi tells it afterwards."""

    message_id: str
    status: str  # as OpenStall keeps it: "sent", "delivered", "read" or "failed"
    recipient: str  # her number in E.164 form, or "" when Whapi does not say
    errors: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        """Why it failed, in Whapi's words, or that Whapi gave none."""
        return "; ".join(self.errors) or "Whapi gave no reason."


def _sender(message: dict[str, Any]) -> str | None:
    """Her number, digits only, for a message in a chat with one person; None for a group, a channel or a status
    update, or a sender that is not a phone number."""
    chat_id = str(message.get("chat_id") or "")
    if chat_id.endswith(NOT_A_PERSON):
        return None
    number = str(message.get("from") or chat_id.split("@", 1)[0]).strip().lstrip("+")
    return number if number.isdigit() and 7 <= len(number) <= 15 else None


def _words(message: dict[str, Any], kind: str) -> str:
    """What she wrote: a text's body (with or without a link in it), a photo's caption, or the title of a button she
    tapped (the button's own words, in her language, which the chat reads as her answer)."""
    if kind in ("text", "link_preview"):
        return str((message.get(kind) or {}).get("body") or "")
    if kind in FILE_KINDS:
        return str((message.get(kind) or {}).get("caption") or "")
    if kind == "reply":
        reply = message.get("reply") or {}
        return str((reply.get("buttons_reply") or reply.get("list_reply") or {}).get("title") or "")
    return ""


def parse_whapi_inbound(payload: dict[str, Any]) -> list[WhapiInbound]:
    """Every new message from a seller in a webhook's payload. Our own (Whapi sends them back, as from_me), groups,
    channels, status updates and kinds OpenStall cannot use (a reaction, a location) are left out."""
    found: list[WhapiInbound] = []
    for message in payload.get("messages") or []:
        if not isinstance(message, dict) or message.get("from_me"):
            continue
        kind, number = str(message.get("type") or ""), _sender(message)
        if number is None or kind not in ("text", "link_preview", "reply", *FILE_KINDS):
            continue
        item = (message.get(kind) or {}) if kind in FILE_KINDS else {}
        media = (
            (WhapiMedia(str(item["id"]), str(item.get("mime_type") or ""), int(item.get("file_size") or 0)),)
            if item.get("id")
            else ()
        )
        found.append(
            WhapiInbound(
                message_id=str(message.get("id") or ""),
                sender=f"+{number}",
                profile_name=str(message.get("from_name") or "").strip() or None,
                text=_words(message, kind).strip(),
                media=media,
            )
        )
    return found


def parse_whapi_statuses(payload: dict[str, Any]) -> list[WhapiStatus]:
    """Every status update in a webhook's payload that OpenStall keeps: what became of each message we sent."""
    found: list[WhapiStatus] = []
    for update in payload.get("statuses") or []:
        if not isinstance(update, dict):
            continue
        message_id, status = str(update.get("id") or ""), STATUSES.get(str(update.get("status") or "").lower())
        if not message_id or status is None:
            continue
        recipient = str(update.get("recipient_id") or "").split("@", 1)[0].lstrip("+")
        errors = tuple(meta_error(error) for error in update.get("errors") or [])
        found.append(WhapiStatus(message_id, status, f"+{recipient}" if recipient.isdigit() else "", errors))
    return found


def starts_with(text: str, word: str) -> bool:
    """Whether her message begins with the start word, as a maker's link to OpenStall writes it: "Start", "start!",
    "Start please"."""
    return bool(word) and re.match(rf"\W*{re.escape(word)}\b", text, re.IGNORECASE) is not None


def channel_matches(payload: dict[str, Any], settings: Settings) -> bool:
    """Whether an event is from our channel, when WHAPI_CHANNEL_ID names it."""
    return not settings.WHAPI_CHANNEL_ID or payload.get("channel_id") == settings.WHAPI_CHANNEL_ID


def download_whapi_media(media: WhapiMedia, settings: Settings, http: httpx.Client) -> tuple[bytes, str]:
    """Fetch one file from Whapi with the channel's token, stopping as soon as it is over 16 MB. Returns its bytes
    and type."""
    if media.size > MAX_BYTES:
        raise MediaRejected("The file is over 16 MB; the most we keep is 16 MB.")
    headers = {"Authorization": f"Bearer {_secret(settings.WHAPI_TOKEN) or ''}"}
    url = f"{settings.WHAPI_API_URL.rstrip('/')}/media/{media.media_id}"
    with http.stream("GET", url, headers=headers, follow_redirects=True) as response:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise MediaRejected("The file is over 16 MB; the most we keep is 16 MB.")
            chunks.append(chunk)
        kind = media_type(media.content_type) or media_type(response.headers.get("content-type", ""))
    return b"".join(chunks), kind


class WhapiMessenger:
    """Sends WhatsApp messages through Whapi.Cloud, from the number linked to its channel."""

    def __init__(self, token: str, base_url: str = "https://gate.whapi.cloud", *, http: httpx.Client | None = None):
        self._token = token
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=30.0)

    def send(
        self, to: str, text: str, media_urls: Sequence[str] = (), buttons: Sequence[str] = ()
    ) -> SentMessage:
        recipient = to.removeprefix("whatsapp:").strip().lstrip("+")
        ids: list[str] = []
        if text:
            ids.append(self._text(recipient, text, buttons))
        for url in media_urls:
            image = url.split("?", 1)[0].lower().endswith(IMAGE_SUFFIXES)
            ids.append(self._post("/messages/image" if image else "/messages/voice", {"to": recipient, "media": url}))
        return SentMessage(ids[0] if ids else "", f"whatsapp:+{recipient}", text, tuple(media_urls), tuple(buttons))

    def _text(self, recipient: str, text: str, buttons: Sequence[str]) -> str:
        """Her text, with quick reply buttons under it when it offers any (at most 3, each title up to 25
        characters); the text alone if Whapi refuses them, as Whapi says its buttons depend on Meta, and the text
        also says what to type."""
        if buttons:
            choices = [
                {"type": "quick_reply", "title": title[:MAX_BUTTON_TITLE], "id": f"button-{index}"}
                for index, title in enumerate(buttons[:3], 1)
            ]
            body = {"to": recipient, "type": "button", "body": {"text": text}, "action": {"buttons": choices}}
            try:
                return self._post("/messages/interactive", body)
            except MessengerError as error:
                log.warning("Whapi refused the reply buttons, so the text goes alone: %s", error)
        return self._post("/messages/text", {"to": recipient, "body": text})

    def _post(self, path: str, body: dict[str, Any]) -> str:
        try:
            response = self._http.post(
                f"{self.base_url}{path}", json=body, headers={"Authorization": f"Bearer {self._token}"}
            )
        except httpx.TransportError as error:
            raise MessengerError(f"Whapi could not be reached ({type(error).__name__})") from error
        if response.status_code >= 400:
            try:
                detail = str((response.json().get("error") or {}).get("message") or "")
            except ValueError:
                detail = response.text[:200]
            raise MessengerError(f"Whapi refused the message ({response.status_code}): {detail}")
        answer = response.json()
        if not answer.get("sent"):
            raise MessengerError("Whapi did not send the message.")
        return str((answer.get("message") or {}).get("id") or "")
