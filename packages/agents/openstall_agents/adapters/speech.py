"""Speech to text: a voice note in, its text and language out (spec 3.1, step 2); and text to speech, for answering a
maker who talks to OpenStall in voice notes with a voice note of its own.

The real adapters, in sandbox mode: ElevenLabs' Scribe (elevenlabs.py) or OpenAI's whisper-1 (openai_speech.py) for
speech to text, and ElevenLabs' Eleven v4 Turbo for text to speech. FakeSpeechToText stands in for speech to text in
fake mode: it knows what fake mode's sample voice note says, and makes up a line for any other. FakeTextToSpeech
answers with a short tone, the same for the same words.
"""

import hashlib
import io
import math
import struct
import wave
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
    def transcribe(self, audio: Media, language: str | None = None) -> Transcript:
        """The words in one voice note, and their language. `language`: the language she is known to speak (ISO
        639-1), as a hint: spoken Urdu and Hindi sound alike, and without one an Urdu voice note can come back as Hindi,
        in Devanagari. Raises SpeechToTextError when it cannot say."""
        ...


class TextToSpeechError(Exception):
    """Words could not be spoken: the provider failed or refused them. The message says why, for the logs; it never
    holds a key."""


@runtime_checkable
class TextToSpeech(Protocol):
    def speak(self, text: str, language: str | None = None) -> Media:
        """The words spoken, as audio, in `language` (ISO 639-1) when given. Raises TextToSpeechError when it
        cannot."""
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
# The same languages by their three-letter codes (ISO 639-3, and the 639-2 forms some providers use): ElevenLabs'
# Scribe answers "urd" for Urdu.
THREE_LETTER: dict[str, str] = {
    "afr": "af", "amh": "am", "ara": "ar", "arb": "ar", "asm": "as", "aze": "az", "azj": "az", "bak": "ba",
    "bel": "be", "bul": "bg", "ben": "bn", "bod": "bo", "tib": "bo", "bre": "br", "bos": "bs", "cat": "ca",
    "ces": "cs", "cze": "cs", "cym": "cy", "wel": "cy", "dan": "da", "deu": "de", "ger": "de", "ell": "el",
    "gre": "el", "eng": "en", "spa": "es", "est": "et", "ekk": "et", "eus": "eu", "baq": "eu", "fas": "fa",
    "per": "fa", "pes": "fa", "fin": "fi", "fao": "fo", "fra": "fr", "fre": "fr", "glg": "gl", "guj": "gu",
    "hau": "ha", "haw": "haw", "heb": "he", "hin": "hi", "hrv": "hr", "hat": "ht", "hun": "hu", "hye": "hy",
    "arm": "hy", "ind": "id", "isl": "is", "ice": "is", "ita": "it", "jpn": "ja", "jav": "jv", "kat": "ka",
    "geo": "ka", "kaz": "kk", "khm": "km", "kan": "kn", "kor": "ko", "lat": "la", "ltz": "lb", "lin": "ln",
    "lao": "lo", "lit": "lt", "lav": "lv", "lvs": "lv", "mlg": "mg", "mri": "mi", "mao": "mi", "mkd": "mk",
    "mac": "mk", "mal": "ml", "mon": "mn", "khk": "mn", "mar": "mr", "msa": "ms", "may": "ms", "zsm": "ms",
    "mlt": "mt", "mya": "my", "bur": "my", "nep": "ne", "npi": "ne", "nld": "nl", "dut": "nl", "nno": "nn",
    "nor": "no", "nob": "no", "oci": "oc", "pan": "pa", "pnb": "pa", "pol": "pl", "pus": "ps", "por": "pt",
    "ron": "ro", "rum": "ro", "rus": "ru", "san": "sa", "snd": "sd", "sin": "si", "slk": "sk", "slo": "sk",
    "slv": "sl", "sna": "sn", "som": "so", "sqi": "sq", "alb": "sq", "srp": "sr", "sun": "su", "swe": "sv",
    "swa": "sw", "swh": "sw", "tam": "ta", "tel": "te", "tgk": "tg", "tha": "th", "tuk": "tk", "tgl": "tl",
    "fil": "tl", "tur": "tr", "tat": "tt", "ukr": "uk", "urd": "ur", "uzb": "uz", "uzn": "uz", "vie": "vi",
    "yid": "yi", "yor": "yo", "yue": "yue", "zho": "zh", "chi": "zh", "cmn": "zh",
}  # fmt: skip
_BY_NAME = {name.lower(): code for code, name in LANGUAGES.items()} | ALIASES | THREE_LETTER


def language_code(heard: object) -> str | None:
    """The code for the language a provider names: "urdu", "Urdu", "ur" or "urd" all give "ur". None for anything
    else, so a language nobody can read is never saved on a seller's profile."""
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
        self.hints: list[str | None] = []  # the language hint each voice note came with
        self._queued: deque[Transcript | SpeechToTextError] = deque(transcripts)
        self._known = dict(known or {})

    def queue(self, *answers: Transcript | SpeechToTextError) -> None:
        """Answers to give, in order, before the others: a Transcript, or a SpeechToTextError to raise."""
        self._queued.extend(answers)

    def transcribe(self, audio: Media, language: str | None = None) -> Transcript:
        self.calls.append(audio)
        self.hints.append(language)
        if self._queued:
            answer = self._queued.popleft()
            if isinstance(answer, SpeechToTextError):
                raise answer
            return answer
        known = self._known.get(audio.sha256)
        if known is not None:
            return known
        return Transcript(text=f"Fake transcript of voice note {audio.sha256[:8]}", language="en")


class FakeTextToSpeech:
    """Fake mode's voice: a short tone for each text, the same tone for the same words, as a WAV file, so the web chat
    can play a spoken answer offline. Records every (text, language) in `calls`; set `fail` to make it raise."""

    RATE = 8000

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.fail: TextToSpeechError | None = None

    def speak(self, text: str, language: str | None = None) -> Media:
        self.calls.append((text, language))
        if self.fail is not None:
            raise self.fail
        seed = hashlib.sha256(f"{language}|{text}".encode()).digest()
        pitch = 330 + seed[0] * 2  # a tone between 330 and 840 Hz
        frames = int(self.RATE * 0.4)
        samples = b"".join(
            struct.pack("<h", int(6000 * math.sin(2 * math.pi * pitch * n / self.RATE))) for n in range(frames)
        )
        out = io.BytesIO()
        with wave.open(out, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(self.RATE)
            audio.writeframes(samples)
        return Media(out.getvalue(), "audio/wav")
