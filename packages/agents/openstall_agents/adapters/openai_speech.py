"""OpenAI's speech to text: the real SpeechToText, in sandbox mode (spec 3.1, step 2).

One POST to /v1/audio/transcriptions per voice note. The default model, whisper-1, answers in verbose_json, the only
format that also names the language it heard ("urdu"), which goes on the seller's profile. Any other model
(SPEECH_MODEL) answers in plain json, so its language is not known. The words are kept as she said them: this calls
transcriptions, never translations.

Checked against openai-python's types on 2026-11-05: whisper-1 shuts down on 2027-02-26, after judging; the newer
gpt-4o-transcribe models accept only json.
"""

import re

import httpx

from openstall_agents.adapters.media import Media
from openstall_agents.adapters.speech import SpeechToTextError, Transcript, language_code

OPENAI_API_BASE = "https://api.openai.com/v1"
DEFAULT_SPEECH_MODEL = "whisper-1"
TIMEOUT_SECONDS = 60.0

# OpenAI reads a voice note's format from its file name: flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav or webm. WhatsApp
# voice notes are ogg; the browser records webm (or mp4 on Safari). AMR and raw AAC are not accepted.
EXTENSIONS: dict[str, str] = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/webm": "webm",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
}
# Anything shaped like an OpenAI key, taken out of an error message before it is logged.
KEY_SHAPE = re.compile(r"sk-[A-Za-z0-9_*\-]+")


class OpenAISpeechToText:
    """Voice notes to text through OpenAI's transcriptions endpoint."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_SPEECH_MODEL,
        *,
        base_url: str = OPENAI_API_BASE,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self.model = model
        self._client = httpx.Client(
            base_url=base_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout
        )

    @property
    def names_language(self) -> bool:
        """Whether this model's answer says which language it heard: whisper's verbose_json does."""
        return self.model.startswith("whisper")

    def transcribe(self, audio: Media, language: str | None = None) -> Transcript:
        kind = audio.media_type.split(";", 1)[0].strip().lower()
        extension = EXTENSIONS.get(kind)
        if extension is None:
            raise SpeechToTextError(f"OpenAI cannot read {kind or 'untyped'} voice notes.")
        try:
            response = self._client.post(
                "/audio/transcriptions",
                data={
                    "model": self.model,
                    "response_format": "verbose_json" if self.names_language else "json",
                    **({"language": language} if language else {}),
                },
                files={"file": (f"voice-note.{extension}", audio.data, kind)},
            )
        except httpx.TimeoutException as error:
            raise SpeechToTextError("OpenAI took too long to answer.") from error
        except httpx.HTTPError as error:
            raise SpeechToTextError(f"OpenAI could not be reached ({type(error).__name__}).") from error
        if response.status_code != 200:
            raise SpeechToTextError(f"OpenAI refused the voice note: {refusal(response)}.")
        try:
            body = response.json()
        except ValueError as error:
            raise SpeechToTextError("OpenAI's answer was not JSON.") from error
        text = str(body.get("text") or "").strip() if isinstance(body, dict) else ""
        if not text:
            raise SpeechToTextError("OpenAI heard no words in the voice note.")
        return Transcript(text=text, language=language_code(body.get("language")))


def refusal(response: httpx.Response) -> str:
    """Why OpenAI said no, for the logs: the status, and its message with anything shaped like a key taken out. A 401
    says only that the key was refused, since OpenAI's message for it quotes part of the key."""
    if response.status_code == 401:
        return "401, the API key was not accepted"
    message = ""
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        error = None
    if isinstance(error, dict):
        message = KEY_SHAPE.sub("sk-…", str(error.get("message") or ""))[:200]
    return f"{response.status_code}, {message}" if message else str(response.status_code)
