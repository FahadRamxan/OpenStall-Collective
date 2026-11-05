"""Speech to text: a voice note in, its text and language out (spec 3.1, step 2).

OpenAISpeechToText (openai_speech.py) is the real adapter, in sandbox mode. FakeSpeechToText stands in for it in fake
mode: it knows what fake mode's sample voice note says, and makes up a line for any other.
"""

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from openstall_agents.adapters.media import Media


@dataclass(frozen=True)
class Transcript:
    """What a voice note says, word for word, never translated."""

    text: str
    language: str | None  # ISO 639-1 code such as "ur" or "en"; None when the provider cannot tell


class SpeechToTextError(Exception):
    """A voice note could not be turned into text: the provider failed or refused it, or heard no words. The message
    says why in plain words, for the logs; it never holds a key or the audio."""


@runtime_checkable
class SpeechToText(Protocol):
    def transcribe(self, audio: Media) -> Transcript:
        """The words in one voice note, and their language. Raises SpeechToTextError when it cannot say."""
        ...


# The languages OpenAI's whisper-1 can hear, by ISO 639-1 code (ISO 639-3 where there is none: haw, yue), with their
# English names. Its verbose_json answer names the language it heard ("urdu"); the code goes on the message and on
# the seller's profile.
LANGUAGES: dict[str, str] = {
    "af": "Afrikaans", "am": "Amharic", "ar": "Arabic", "as": "Assamese", "az": "Azerbaijani",
    "ba": "Bashkir", "be": "Belarusian", "bg": "Bulgarian", "bn": "Bengali", "bo": "Tibetan",
    "br": "Breton", "bs": "Bosnian", "ca": "Catalan", "cs": "Czech", "cy": "Welsh",
    "da": "Danish", "de": "German", "el": "Greek", "en": "English", "es": "Spanish",
    "et": "Estonian", "eu": "Basque", "fa": "Persian", "fi": "Finnish", "fo": "Faroese",
    "fr": "French", "gl": "Galician", "gu": "Gujarati", "ha": "Hausa", "haw": "Hawaiian",
    "he": "Hebrew", "hi": "Hindi", "hr": "Croatian", "ht": "Haitian Creole", "hu": "Hungarian",
    "hy": "Armenian", "id": "Indonesian", "is": "Icelandic", "it": "Italian", "ja": "Japanese",
    "jv": "Javanese", "ka": "Georgian", "kk": "Kazakh", "km": "Khmer", "kn": "Kannada",
    "ko": "Korean", "la": "Latin", "lb": "Luxembourgish", "ln": "Lingala", "lo": "Lao",
    "lt": "Lithuanian", "lv": "Latvian", "mg": "Malagasy", "mi": "Maori", "mk": "Macedonian",
    "ml": "Malayalam", "mn": "Mongolian", "mr": "Marathi", "ms": "Malay", "mt": "Maltese",
    "my": "Burmese", "ne": "Nepali", "nl": "Dutch", "nn": "Nynorsk", "no": "Norwegian",
    "oc": "Occitan", "pa": "Punjabi", "pl": "Polish", "ps": "Pashto", "pt": "Portuguese",
    "ro": "Romanian", "ru": "Russian", "sa": "Sanskrit", "sd": "Sindhi", "si": "Sinhala",
    "sk": "Slovak", "sl": "Slovenian", "sn": "Shona", "so": "Somali", "sq": "Albanian",
    "sr": "Serbian", "su": "Sundanese", "sv": "Swedish", "sw": "Swahili", "ta": "Tamil",
    "te": "Telugu", "tg": "Tajik", "th": "Thai", "tk": "Turkmen", "tl": "Tagalog",
    "tr": "Turkish", "tt": "Tatar", "uk": "Ukrainian", "ur": "Urdu", "uz": "Uzbek",
    "vi": "Vietnamese", "yi": "Yiddish", "yo": "Yoruba", "yue": "Cantonese", "zh": "Chinese",
}  # fmt: skip
# Other names and codes whisper uses for the same languages.
ALIASES: dict[str, str] = {
    "myanmar": "my", "jw": "jv", "burmese": "my", "valencian": "ca", "flemish": "nl", "haitian": "ht",
    "letzeburgesch": "lb", "pushto": "ps", "panjabi": "pa", "moldavian": "ro", "moldovan": "ro",
    "sinhalese": "si", "castilian": "es", "mandarin": "zh",
}  # fmt: skip
_BY_NAME = {name.lower(): code for code, name in LANGUAGES.items()} | ALIASES


def language_code(heard: object) -> str | None:
    """The code for the language a provider names: "urdu", "Urdu" or "ur" all give "ur". None for anything else, so
    a language nobody can read is never saved on a seller's profile."""
    if not isinstance(heard, str):
        return None
    value = heard.strip().lower()
    if value in LANGUAGES:
        return value
    return _BY_NAME.get(value)


def language_name(code: str | None) -> str | None:
    """The English name of a language code, such as "Urdu" for "ur"; the code itself if it is not one we know."""
    if not code:
        return None
    return LANGUAGES.get(code, code)


class FakeSpeechToText:
    """Gives queued answers in order (a Transcript, or a SpeechToTextError to raise, as a provider might fail), then
    the transcript of a voice note it knows by its sha256 (`known`: fake mode's sample voice note), then a made-up
    line per file. Records every voice note in `calls`."""

    def __init__(
        self,
        transcripts: Sequence[Transcript | SpeechToTextError] = (),
        known: Mapping[str, Transcript] | None = None,
    ) -> None:
        self.calls: list[Media] = []
        self._queued: deque[Transcript | SpeechToTextError] = deque(transcripts)
        self._known = dict(known or {})

    def queue(self, *answers: Transcript | SpeechToTextError) -> None:
        """Answers to give, in order, before the others: a Transcript, or a SpeechToTextError to raise."""
        self._queued.extend(answers)

    def transcribe(self, audio: Media) -> Transcript:
        self.calls.append(audio)
        if self._queued:
            answer = self._queued.popleft()
            if isinstance(answer, SpeechToTextError):
                raise answer
            return answer
        known = self._known.get(audio.sha256)
        if known is not None:
            return known
        return Transcript(text=f"Fake transcript of voice note {audio.sha256[:8]}", language="en")
