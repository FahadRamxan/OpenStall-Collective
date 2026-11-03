"""WhatsApp messages to sellers (spec 3.1 and 3.6): the Messenger interface, and a fake that records instead of sending.

The real adapter, TwilioMessenger, is in whatsapp.py. FakeMessenger stands in for it in fake mode.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import count
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SentMessage:
    """One message as handed to WhatsApp."""

    message_id: str  # the provider's id for it (Twilio's message SID)
    to: str  # for example "whatsapp:+923001234567"
    text: str
    media_urls: tuple[str, ...] = ()


@runtime_checkable
class Messenger(Protocol):
    def send(self, to: str, text: str, media_urls: Sequence[str] = ()) -> SentMessage:
        """Send one WhatsApp message, with optional media at public URLs."""
        ...


class FakeMessenger:
    """Records each message in `calls` instead of sending it. Ids count up: fake-msg-0001, fake-msg-0002, ..."""

    def __init__(self) -> None:
        self.calls: list[SentMessage] = []
        self._next_id = count(1)

    def send(self, to: str, text: str, media_urls: Sequence[str] = ()) -> SentMessage:
        message = SentMessage(f"fake-msg-{next(self._next_id):04d}", to, text, tuple(media_urls))
        self.calls.append(message)
        return message

    def sent_to(self, to: str) -> list[SentMessage]:
        """Every message sent to one number, oldest first."""
        return [message for message in self.calls if message.to == to]
