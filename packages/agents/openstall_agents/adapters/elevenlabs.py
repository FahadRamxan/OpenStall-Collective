"""ElevenLabs, the real voice of OpenStall in sandbox mode: its Scribe turns the makers' voice notes into text, and its
Eleven v4 Turbo speaks OpenStall's answers to a maker who talks to it in voice notes.

Speech to text is one POST to /v1/speech-to-text per voice note (Scribe v2 by default). Audio tags such as "(laughter)"
are turned off, so the words are hers and nothing else; they are never translated. Scribe names the language it heard
by a three-letter code ("urd"), kept as its two-letter one ("ur"). Spoken Urdu and Hindi sound alike: checked on
2026-11-06 with the real key, an Urdu voice note with no hint came back as Hindi, in Devanagari, and with the hint "ur"
as Urdu, in Urdu script. So the caller passes the language she is known to speak (SpeechToText.transcribe).

Text to speech is one POST to /v1/text-to-speech/{voice} per answer, an MP3, with the answer's language when it is
known. The default voice is ElevenLabs' premade "Jessica" (warm, conversational), which every account has.
"""

import re

import httpx

from openstall_agents.adapters.media import Media
from openstall_agents.adapters.speech import (
    SpeechToTextError,
    TextToSpeechError,
    Transcript,
    language_code,
)

ELEVENLABS_API_BASE = "https://api.elevenlabs.io"
DEFAULT_SPEECH_MODEL = "scribe_v2"
DEFAULT_VOICE_MODEL = "eleven_v4_turbo"
DEFAULT_VOICE = "cgSgspJ2msm6clMCkdW9"  # "Jessica", one of ElevenLabs' premade voices
VOICE_FORMAT = "mp3_44100_128"
TIMEOUT_SECONDS = 60.0
# Anything shaped like an ElevenLabs key, taken out of an error message before it is logged.
KEY_SHAPE = re.compile(r"sk_[0-9a-zA-Z]{6,}")
EXTENSIONS: dict[str, str] = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/webm": "webm",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/amr": "amr",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
}


def refusal(response: httpx.Response) -> str:
    """Why ElevenLabs said no, for the logs: the status and its message, with anything shaped like a key taken out. A
    401 says only that the key was refused or lacks a permission."""
    if response.status_code == 401:
        return "401, the API key was not accepted for this"
    detail: object = None
    try:
        body = response.json()
        detail = body.get("detail") if isinstance(body, dict) else None
    except ValueError:
        pass
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("status")
    message = KEY_SHAPE.sub("sk_…", str(detail or ""))[:200]
    return f"{response.status_code}, {message}" if message else str(response.status_code)


class _ElevenLabs:
    def __init__(self, api_key: str, *, base_url: str, timeout: float) -> None:
        self._client = httpx.Client(base_url=base_url, headers={"xi-api-key": api_key}, timeout=timeout)

    def close(self) -> None:
        self._client.close()


class ElevenLabsSpeechToText(_ElevenLabs):
    """Voice notes to text through ElevenLabs' Scribe."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_SPEECH_MODEL,
        *,
        base_url: str = ELEVENLABS_API_BASE,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(api_key, base_url=base_url, timeout=timeout)
        self.model = model

    def transcribe(self, audio: Media, language: str | None = None) -> Transcript:
        kind = audio.media_type.split(";", 1)[0].strip().lower()
        extension = EXTENSIONS.get(kind, "bin")
        data = {"model_id": self.model, "tag_audio_events": "false"}
        if language:
            data["language_code"] = language
        try:
            response = self._client.post(
                "/v1/speech-to-text", data=data, files={"file": (f"voice-note.{extension}", audio.data, kind)}
            )
        except httpx.TimeoutException as error:
            raise SpeechToTextError("ElevenLabs took too long to answer.") from error
        except httpx.HTTPError as error:
            raise SpeechToTextError(f"ElevenLabs could not be reached ({type(error).__name__}).") from error
        if response.status_code != 200:
            raise SpeechToTextError(f"ElevenLabs refused the voice note: {refusal(response)}.")
        try:
            body = response.json()
        except ValueError as error:
            raise SpeechToTextError("ElevenLabs' answer was not JSON.") from error
        text = str(body.get("text") or "").strip() if isinstance(body, dict) else ""
        if not text:
            raise SpeechToTextError("ElevenLabs heard no words in the voice note.")
        return Transcript(text=text, language=language_code(body.get("language_code")))


class ElevenLabsTextToSpeech(_ElevenLabs):
    """OpenStall's answers spoken, through ElevenLabs' text to speech (Eleven v4 Turbo by default)."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_VOICE_MODEL,
        voice: str = DEFAULT_VOICE,
        *,
        base_url: str = ELEVENLABS_API_BASE,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(api_key, base_url=base_url, timeout=timeout)
        self.model = model
        self.voice = voice

    def speak(self, text: str, language: str | None = None) -> Media:
        body: dict[str, str] = {"text": text, "model_id": self.model}
        if language:
            body["language_code"] = language
        try:
            response = self._client.post(
                f"/v1/text-to-speech/{self.voice}", params={"output_format": VOICE_FORMAT}, json=body
            )
        except httpx.TimeoutException as error:
            raise TextToSpeechError("ElevenLabs took too long to answer.") from error
        except httpx.HTTPError as error:
            raise TextToSpeechError(f"ElevenLabs could not be reached ({type(error).__name__}).") from error
        if response.status_code != 200:
            raise TextToSpeechError(f"ElevenLabs could not speak it: {refusal(response)}.")
        if not response.content:
            raise TextToSpeechError("ElevenLabs answered with no audio.")
        return Media(response.content, "audio/mpeg")
