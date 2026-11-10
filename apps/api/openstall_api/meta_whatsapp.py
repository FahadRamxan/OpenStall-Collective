"""WhatsApp through Meta's WhatsApp Cloud API: its webhook's check and signature, the inbound message, its media, and
sending.

Meta checks a webhook address once, with a GET carrying our verify token (hub.verify_token) and a challenge to echo
back; then it POSTs each event as JSON, signed with our app secret: X-Hub-Signature-256 is "sha256=" and the
HMAC-SHA256 of the raw body. A photo or voice note arrives as a media id: Graph API gives its short-lived URL, and both
calls need the access token. Replies go to /{phone number id}/messages, a voice note as a link to our public copy.

In fake mode, with no Meta app, requests are signed with FAKE_META_APP_SECRET and the address is checked with
FAKE_META_VERIFY_TOKEN. Both are public, which is fine: fake mode sends nothing to anyone.
"""

import hashlib
import hmac
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from openstall_api.media import MAX_BYTES, MediaRejected, media_type
from openstall_api.messaging import SentMessage
from openstall_api.settings import Settings
from openstall_api.whatsapp import MessengerError

log = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com"
# Meta's reply buttons: at most 3, each title up to 20 characters, under a text of up to 1024.
MAX_BUTTON_TITLE = 20
MAX_BUTTON_TEXT = 1024
FAKE_META_APP_SECRET = "openstall-fake-mode-meta-app-secret"
FAKE_META_VERIFY_TOKEN = "openstall-fake-mode-meta-verify-token"
# The kinds of message that carry one file. Meta sends each photo or voice note as a message of its own.
FILE_KINDS = ("image", "audio", "video", "document", "sticker")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def meta_signature(body: bytes, secret: str) -> str:
    """Meta's signature for a webhook body: "sha256=" and the HMAC-SHA256 of the raw bytes, in hex."""
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def valid_meta_request(body: bytes, signature: str, secret: str | None) -> bool:
    if not secret or not signature:
        return False
    return hmac.compare_digest(meta_signature(body, secret), signature)


def _secret(value: Any) -> str | None:
    return value.get_secret_value() or None if value is not None else None


def meta_app_secret(settings: Settings) -> str | None:
    """The secret Meta's requests are checked with: ours, or in fake mode the public fake one."""
    return _secret(settings.META_APP_SECRET) or (FAKE_META_APP_SECRET if settings.OPENSTALL_MODE == "fake" else None)


def meta_verify_token(settings: Settings) -> str | None:
    """The token Meta must send to check our webhook address: ours, or in fake mode the public fake one."""
    configured = _secret(settings.META_WHATSAPP_VERIFY_TOKEN)
    return configured or (FAKE_META_VERIFY_TOKEN if settings.OPENSTALL_MODE == "fake" else None)


@dataclass(frozen=True)
class MetaMedia:
    media_id: str
    content_type: str


@dataclass(frozen=True)
class MetaInbound:
    """One WhatsApp message to our number, as Meta describes it."""

    message_id: str  # Meta's wamid, the same when Meta sends it again
    sender: str  # E.164, such as +923001234567
    profile_name: str | None  # the name on her WhatsApp profile: a first guess at her name
    text: str
    media: tuple[MetaMedia, ...]


def _words(message: dict[str, Any], kind: str) -> str:
    """What she wrote: a text's body, a photo's caption, or the title of a button she tapped."""
    if kind == "text":
        return str((message.get("text") or {}).get("body") or "")
    if kind in FILE_KINDS:
        return str((message.get(kind) or {}).get("caption") or "")
    if kind == "button":
        return str((message.get("button") or {}).get("text") or "")
    if kind == "interactive":
        reply = message.get("interactive") or {}
        return str((reply.get("button_reply") or reply.get("list_reply") or {}).get("title") or "")
    return ""


@dataclass(frozen=True)
class MetaStatus:
    """What became of a message we sent, as Meta tells it afterwards. Meta's 200 to a send only means it took the
    message; whether it reached her phone comes later, as one of these: sent, delivered, read, or failed with Meta's
    reasons."""

    message_id: str  # the wamid our send was given
    status: str  # "sent", "delivered", "read" or "failed"
    recipient: str  # her number in E.164 form, such as +923001234567
    errors: tuple[str, ...] = ()  # Meta's reasons, each in words (meta_error)

    @property
    def reason(self) -> str:
        """Why it failed, in Meta's words, or that Meta gave none."""
        return "; ".join(self.errors) or "Meta gave no reason."


def meta_error(error: Any) -> str:
    """One of Meta's errors in words: its code, title and details, such as "(131047) Re-engagement message: Message
    failed to send because more than 24 hours have passed since the customer last replied to this number."."""
    if not isinstance(error, dict):
        return str(error)[:300]
    title = str(error.get("title") or error.get("message") or "").strip()
    data = error.get("error_data")
    details = str(data.get("details") or "").strip() if isinstance(data, dict) else ""
    words = f"{title}: {details}" if title and details and details != title else title or details or "no reason given"
    code = error.get("code")
    return (f"({code}) {words}" if code is not None else words)[:300]


def parse_meta_statuses(payload: dict[str, Any]) -> list[MetaStatus]:
    """Every status update in a webhook's payload: what became of each message we sent."""
    found: list[MetaStatus] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            for update in (change.get("value") or {}).get("statuses") or []:
                message_id, status = str(update.get("id") or ""), str(update.get("status") or "")
                if not message_id or not status:
                    continue
                recipient = str(update.get("recipient_id") or "").strip().lstrip("+")
                errors = tuple(meta_error(error) for error in update.get("errors") or [])
                found.append(MetaStatus(message_id, status, f"+{recipient}" if recipient else "", errors))
    return found


def parse_meta_inbound(payload: dict[str, Any]) -> list[MetaInbound]:
    """Every message in a webhook's payload. Status updates (sent, delivered, read, failed: parse_meta_statuses) and
    kinds OpenStall cannot use (a reaction, a location) are left out."""
    found: list[MetaInbound] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            names = {
                str(contact.get("wa_id")): ((contact.get("profile") or {}).get("name") or "").strip() or None
                for contact in value.get("contacts") or []
            }
            for message in value.get("messages") or []:
                wa_id = str(message.get("from") or "").strip().lstrip("+")
                kind = str(message.get("type") or "")
                if not wa_id or kind not in ("text", "button", "interactive", *FILE_KINDS):
                    continue
                item = message.get(kind) or {} if kind in FILE_KINDS else {}
                media = (MetaMedia(str(item["id"]), str(item.get("mime_type") or "")),) if item.get("id") else ()
                found.append(
                    MetaInbound(
                        message_id=str(message.get("id") or ""),
                        sender=f"+{wa_id}",
                        profile_name=names.get(wa_id),
                        text=_words(message, kind).strip(),
                        media=media,
                    )
                )
    return found


def download_meta_media(media: MetaMedia, settings: Settings, http: httpx.Client) -> tuple[bytes, str]:
    """Fetch one file from Meta: its short-lived URL from Graph API, then its bytes, stopping as soon as it is over
    16 MB. Returns its bytes and type."""
    token = _secret(settings.META_WHATSAPP_TOKEN) or ""
    headers = {"Authorization": f"Bearer {token}"}
    info = http.get(f"{GRAPH}/{settings.META_GRAPH_VERSION}/{media.media_id}", headers=headers)
    info.raise_for_status()
    details = info.json()
    if int(details.get("file_size") or 0) > MAX_BYTES:
        raise MediaRejected("The file is over 16 MB; the most we keep is 16 MB.")
    with http.stream("GET", str(details["url"]), headers=headers, follow_redirects=True) as response:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise MediaRejected("The file is over 16 MB; the most we keep is 16 MB.")
            chunks.append(chunk)
        kind = (
            media_type(str(details.get("mime_type") or ""))
            or media_type(media.content_type)
            or media_type(response.headers.get("content-type", ""))
        )
    return b"".join(chunks), kind


class MetaMessenger:
    """Sends WhatsApp messages through Meta's WhatsApp Cloud API, from our business phone number (a test number from
    Meta's developer site works). Within 24 hours of her last message, as WhatsApp allows any reply."""

    def __init__(self, token: str, phone_number_id: str, version: str, *, http: httpx.Client | None = None) -> None:
        self._token = token
        self.phone_number_id = phone_number_id
        self.version = version
        self._http = http or httpx.Client(timeout=15.0)

    def send(
        self, to: str, text: str, media_urls: Sequence[str] = (), buttons: Sequence[str] = ()
    ) -> SentMessage:
        recipient = to.removeprefix("whatsapp:").strip().lstrip("+")
        ids: list[str] = []
        if text:
            ids.append(self._text(recipient, text, buttons))
        for url in media_urls:
            kind = "image" if url.split("?", 1)[0].lower().endswith(IMAGE_SUFFIXES) else "audio"
            ids.append(self._post(recipient, {"type": kind, kind: {"link": url}}))
        return SentMessage(ids[0] if ids else "", f"whatsapp:+{recipient}", text, tuple(media_urls), tuple(buttons))

    def _text(self, recipient: str, text: str, buttons: Sequence[str]) -> str:
        """Her text, with reply buttons under it when it offers any (Meta takes 3, each title up to 20 characters,
        under a text of up to 1024); the text alone if Meta refuses them, as it also says what to type."""
        if buttons and len(text) <= MAX_BUTTON_TEXT:
            choices = [
                {"type": "reply", "reply": {"id": f"button-{index}", "title": title[:MAX_BUTTON_TITLE]}}
                for index, title in enumerate(buttons[:3], 1)
            ]
            interactive = {"type": "button", "body": {"text": text}, "action": {"buttons": choices}}
            try:
                return self._post(recipient, {"type": "interactive", "interactive": interactive})
            except MessengerError as error:
                log.warning("Meta refused the reply buttons, so the text goes alone: %s", error)
        return self._post(recipient, {"type": "text", "text": {"body": text, "preview_url": False}})

    def _post(self, recipient: str, message: dict[str, Any]) -> str:
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": recipient, **message}
        try:
            response = self._http.post(
                f"{GRAPH}/{self.version}/{self.phone_number_id}/messages",
                json=body,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.TransportError as error:
            raise MessengerError(f"Meta's WhatsApp API could not be reached ({type(error).__name__})") from error
        if response.status_code >= 400:
            try:
                detail = str((response.json().get("error") or {}).get("message") or "")
            except ValueError:
                detail = response.text[:200]
            raise MessengerError(f"Meta refused the message ({response.status_code}): {detail}")
        return str(response.json()["messages"][0]["id"])
