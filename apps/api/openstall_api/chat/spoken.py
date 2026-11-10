"""Spoken answers: a maker who talks to OpenStall in voice notes hears its answers as voice notes too, in her language
(ElevenLabs' Eleven v4 Turbo in sandbox mode, a stand-in tone in fake mode).

Many of the makers OpenStall is for send voice notes because typing is slow for them, or reading is. So when her
message held a voice note it heard, each answer to it is also spoken: after the commit, outside any transaction (the
voice may take a second or two), kept in the media store and on the answer's own message, and, on WhatsApp, sent as a
voice note after the text. The words stay the template's, written by code; the voice only reads them out. An answer
that cannot be spoken is logged, and she still has it as text.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from openstall_agents.adapters import TextToSpeech, TextToSpeechError, language_name
from openstall_api.adapters import AdapterUnavailable
from openstall_api.chat.handler import HandledMessage
from openstall_api.chat.store import CHANNEL_WORDS
from openstall_api.chat.voice import Heard
from openstall_api.db import session_scope
from openstall_api.events import EventType, record_event
from openstall_api.media import MediaRejected, MediaStore, StoredMedia
from openstall_api.wording import speakable
from openstall_api.models import ChatMessage, ChatSession

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Spoken:
    """One answer spoken: its message, and the audio kept for it."""

    message_id: str
    audio: StoredMedia


def speak_replies(
    handled: HandledMessage, heard: Heard, store: MediaStore, voice: Callable[[], TextToSpeech]
) -> list[Spoken]:
    """After her message is committed: if it held a voice note that was heard, each answer to it spoken in her
    language, kept, and put on its message. Returns what was spoken, in order; nothing when she typed."""
    if not heard.texts or not handled.reply_ids:
        return []
    try:
        speaker = voice()
    except AdapterUnavailable as error:
        log.warning("Answers cannot be spoken here: %s", error)
        return []
    spoken: list[Spoken] = []
    for message_id, reply in zip(handled.reply_ids, handled.replies, strict=True):
        try:
            audio = speaker.speak(speakable(reply.text), handled.language)  # no "*" or bullet read out
            spoken.append(Spoken(message_id, store.save(audio.data, audio.media_type)))
        except (TextToSpeechError, MediaRejected) as error:
            log.warning("An answer to seller %s could not be spoken: %s", handled.seller_id, error)
        except Exception:
            # A bug, not the provider: logged in full, and she still has the answer as text.
            log.exception("Speaking an answer to seller %s failed unexpectedly", handled.seller_id)
    if spoken:
        _keep(handled, spoken)
    return spoken


def _keep(handled: HandledMessage, spoken: list[Spoken]) -> None:
    """Each spoken answer on its message, and one line for the live feed."""
    with session_scope() as session:
        name, channel = "a seller", None
        for item in spoken:
            message = session.get(ChatMessage, item.message_id)
            if message is None:
                continue
            message.media_json = [
                *message.media_json,
                {
                    "key": item.audio.key,
                    "url": item.audio.url,
                    "content_type": item.audio.content_type,
                    "size": item.audio.size,
                    "spoken": True,
                },
            ]
            message.language = handled.language
            chat = session.get(ChatSession, message.session_id)
            if chat is not None and chat.seller is not None:
                name, channel = chat.seller.name, chat.channel
        answers = "answer was" if len(spoken) == 1 else f"{len(spoken)} answers were"
        where = f" {CHANNEL_WORDS[channel]}" if channel is not None else ""
        record_event(
            session,
            EventType.MESSAGE_SPOKEN,
            f"OpenStall's {answers} spoken to {name}{where}, in {language_name(handled.language)}, as she sent a voice "
            "note",
            entity_id=handled.seller_id,
            payload={"message_ids": [item.message_id for item in spoken], "language": handled.language},
        )
