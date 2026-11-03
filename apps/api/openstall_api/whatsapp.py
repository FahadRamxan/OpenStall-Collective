"""WhatsApp through Twilio (spec 3.1): Twilio's request signature, the inbound message, its media, and sending.

Twilio signs each webhook with our auth token: HMAC-SHA1 over the URL it called followed by every form field, sorted
by name. The URL is the public one (PUBLIC_BASE_URL plus the path), not the address the server sees behind Render's
proxy. Media links need the account SID and auth token to download.

In fake mode, with no Twilio account, requests are signed with FAKE_TWILIO_TOKEN instead. It is public, which is
fine: fake mode sends nothing to anyone.
"""

import base64
import hashlib
import hmac
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from openstall_api.media import MAX_BYTES, MediaRejected, media_type
from openstall_api.messaging import SentMessage
from openstall_api.settings import Settings

FAKE_TWILIO_TOKEN = "openstall-fake-mode-twilio-token"
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
TWILIO_API = "https://api.twilio.com/2010-04-01"
MAX_MEDIA = 10  # WhatsApp's limit per message


def twilio_signature(url: str, params: Iterable[tuple[str, str]], token: str) -> str:
    """Twilio's signature for a request: the URL, then each field's name and value, sorted, HMAC-SHA1, base64."""
    values: dict[str, set[str]] = {}
    for name, value in params:
        values.setdefault(name, set()).add(value)
    data = url + "".join(name + value for name in sorted(values) for value in sorted(values[name]))
    digest = hmac.new(token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def _with_and_without_port(url: str) -> list[str]:
    """Twilio may sign the URL with or without the default port, so accept both, as its own library does."""
    parts = urlsplit(url)
    default = {"https": 443, "http": 80}.get(parts.scheme)
    host = parts.hostname or ""
    if parts.port is None and default:
        other = parts._replace(netloc=f"{host}:{default}")
    elif parts.port == default:
        other = parts._replace(netloc=host)
    else:
        return [url]
    return [url, urlunsplit(other)]


def valid_twilio_request(url: str, params: Sequence[tuple[str, str]], signature: str, token: str | None) -> bool:
    if not token or not signature:
        return False
    return any(
        hmac.compare_digest(twilio_signature(candidate, params, token), signature)
        for candidate in _with_and_without_port(url)
    )


def twilio_token(settings: Settings) -> str | None:
    """The token Twilio's requests are checked with: ours, or in fake mode the public fake one."""
    if settings.TWILIO_AUTH_TOKEN is not None and settings.TWILIO_AUTH_TOKEN.get_secret_value():
        return settings.TWILIO_AUTH_TOKEN.get_secret_value()
    return FAKE_TWILIO_TOKEN if settings.OPENSTALL_MODE == "fake" else None


@dataclass(frozen=True)
class InboundMedia:
    url: str
    content_type: str


@dataclass(frozen=True)
class InboundMessage:
    """One WhatsApp message to our number, as Twilio describes it."""

    message_sid: str
    sender: str  # E.164, such as +923001234567
    profile_name: str | None  # the name on her WhatsApp profile: a first guess at her name
    text: str
    media: tuple[InboundMedia, ...]


def parse_inbound(form: dict[str, str]) -> InboundMessage:
    wa_id = form.get("WaId", "").strip()
    sender = f"+{wa_id}" if wa_id else form.get("From", "").removeprefix("whatsapp:").strip()
    try:
        count = min(int(form.get("NumMedia") or 0), MAX_MEDIA)
    except ValueError:
        count = 0
    media = tuple(
        InboundMedia(url=form[f"MediaUrl{index}"], content_type=form.get(f"MediaContentType{index}", ""))
        for index in range(count)
        if form.get(f"MediaUrl{index}")
    )
    return InboundMessage(
        message_sid=form.get("MessageSid") or form.get("SmsMessageSid") or "",
        sender=sender,
        profile_name=(form.get("ProfileName") or "").strip() or None,
        text=(form.get("Body") or "").strip(),
        media=media,
    )


def download_media(media: InboundMedia, settings: Settings, http: httpx.Client) -> tuple[bytes, str]:
    """Fetch one media item from Twilio, stopping as soon as it is over 16 MB. Returns its bytes and type."""
    sid = settings.TWILIO_ACCOUNT_SID or ""
    token = settings.TWILIO_AUTH_TOKEN.get_secret_value() if settings.TWILIO_AUTH_TOKEN else ""
    with http.stream("GET", media.url, auth=(sid, token), follow_redirects=True) as response:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise MediaRejected("The file is over 16 MB; the most we keep is 16 MB.")
            chunks.append(chunk)
        kind = media_type(response.headers.get("content-type", "")) or media_type(media.content_type)
    return b"".join(chunks), kind


class MessengerError(RuntimeError):
    """Twilio refused or could not take a message."""


class TwilioMessenger:
    """Sends WhatsApp messages through Twilio's Messages API, from our WhatsApp sandbox number."""

    def __init__(self, account_sid: str, token: str, from_number: str, *, http: httpx.Client | None = None) -> None:
        self.account_sid = account_sid
        self._token = token
        self.from_number = from_number
        self._http = http or httpx.Client(timeout=15.0)

    def send(self, to: str, text: str, media_urls: Sequence[str] = ()) -> SentMessage:
        recipient = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
        form: dict[str, str | list[str]] = {"From": self.from_number, "To": recipient, "Body": text}
        if media_urls:
            form["MediaUrl"] = list(media_urls)  # one field per photo
        try:
            response = self._http.post(
                f"{TWILIO_API}/Accounts/{self.account_sid}/Messages.json",
                data=form,
                auth=(self.account_sid, self._token),
            )
        except httpx.TransportError as error:
            raise MessengerError(f"Twilio could not be reached ({type(error).__name__})") from error
        if response.status_code >= 400:
            detail = response.json().get("message", "") if response.content else ""
            raise MessengerError(f"Twilio refused the message ({response.status_code}): {detail}")
        return SentMessage(response.json()["sid"], recipient, text, tuple(media_urls))
