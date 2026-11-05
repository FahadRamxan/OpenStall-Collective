"""Voice notes turned into text (spec 3.1, step 2), before her message is stored.

listen() asks the speech to text adapter outside any transaction, as look_at_photos asks the vision model: a provider
can take seconds, and must not hold the database meanwhile. handle_inbound then stores what was heard on her message,
word for word and never translated, so a wrong reading can be traced to the voice note; and saves the language on her
profile when she has none yet.

A voice note that cannot be heard (the provider failed, or sandbox mode has no OPENAI_API_KEY) is kept all the same,
and she is asked to send it again or type it.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from openstall_agents.adapters import Media, SpeechToText, SpeechToTextError, language_name
from openstall_api.adapters import AdapterUnavailable
from openstall_api.models import Seller

log = logging.getLogger(__name__)

UNCLEAR = "Sorry, I could not make out your voice note. Could you send it again, or type it?"
UNCLEAR_SEVERAL = "Sorry, I could not make out {count} of your voice notes. Could you send them again, or type them?"


@dataclass(frozen=True)
class Heard:
    """What the voice notes in one message said: each heard one's words, in order; the first language heard; and how
    many could not be turned into text."""

    texts: tuple[str, ...] = ()
    language: str | None = None
    failed: int = 0

    @property
    def transcript(self) -> str | None:
        """Her words as kept on the message: each voice note's, a blank line apart. None when none was heard."""
        return "\n\n".join(self.texts) or None


def listen(voice_notes: Sequence[Media], speech: Callable[[], SpeechToText]) -> Heard:
    """Each voice note turned into text, in order. One that cannot be is counted, never raised: her message is kept
    either way. Run it outside any transaction."""
    if not voice_notes:
        return Heard()
    try:
        transcriber = speech()
    except AdapterUnavailable as error:
        log.warning("Voice notes cannot be turned into text here: %s", error)
        return Heard(failed=len(voice_notes))
    texts: list[str] = []
    language: str | None = None
    failed = 0
    for note in voice_notes:
        try:
            transcript = transcriber.transcribe(note)
        except SpeechToTextError as error:
            log.warning("A voice note (%r) could not be turned into text: %s", note, error)
            failed += 1
            continue
        except Exception:
            # A bug, not the provider: logged in full, and her message is still kept.
            log.exception("Turning a voice note (%r) into text failed unexpectedly", note)
            failed += 1
            continue
        words = transcript.text.strip()
        if not words:
            failed += 1
            continue
        texts.append(words)
        language = language or transcript.language
    return Heard(tuple(texts), language, failed)


def unclear(heard: Heard) -> list[str]:
    """The apology for voice notes that could not be heard, if any."""
    if heard.failed == 0:
        return []
    return [UNCLEAR if heard.failed == 1 else UNCLEAR_SEVERAL.format(count=heard.failed)]


def remember_language(seller: Seller, language: str | None) -> bool:
    """Her language, saved on her profile from the first voice note it is heard in. One already there (a seeded
    maker's, or heard before) stays: a single misheard voice note must not change the language OpenStall writes to
    her in."""
    if not language or seller.language:
        return False
    seller.language = language
    return True


def transcribed_words(name: str, heard: Heard, saved: bool) -> str:
    """The live feed's line, such as "Amina's voice note was turned into text, in Urdu, now saved as her language"."""
    notes = "voice note was" if len(heard.texts) == 1 else f"{len(heard.texts)} voice notes were"
    line = f"{name}'s {notes} turned into text"
    if heard.language:
        line += f", in {language_name(heard.language)}"
        if saved:
            line += ", now saved as her language"
    return line
