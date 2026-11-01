"""Speech to text: a voice note in, its text and language out (spec 3.1, step 2).

The real adapter uses the provider recorded in docs/day-one-checks.md. FakeSpeechToText stands in for it in fake mode.
"""

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from openstall_agents.adapters.media import Media


@dataclass(frozen=True)
class Transcript:
    """What a voice note says, word for word, never translated."""

    text: str
    language: str | None  # ISO 639-1 code such as "ur" or "en"; None when the provider cannot tell


@runtime_checkable
class SpeechToText(Protocol):
    def transcribe(self, audio: Media) -> Transcript:
        """The words in one voice note, and their language."""
        ...


class FakeSpeechToText:
    """Gives queued transcripts in order, then a fixed one per file. Records every voice note in `calls`."""

    def __init__(self, transcripts: Sequence[Transcript] = ()) -> None:
        self.calls: list[Media] = []
        self._queued: deque[Transcript] = deque(transcripts)

    def queue(self, *transcripts: Transcript) -> None:
        """Transcripts to give, in order, before the default."""
        self._queued.extend(transcripts)

    def transcribe(self, audio: Media) -> Transcript:
        self.calls.append(audio)
        if self._queued:
            return self._queued.popleft()
        return Transcript(text=f"Fake transcript of voice note {audio.sha256[:8]}", language="en")
