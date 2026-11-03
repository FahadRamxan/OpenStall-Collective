"""The real language model in sandbox mode: Claude, through Anthropic's Python SDK. Fake mode uses FakeLLM instead.

One request per call. A JSON answer uses structured outputs (output_config.format), so the first text block is JSON
that matches the schema. These are short answers (a price and a sentence, a few lines of explanation), so effort is
low. Every failure the agents can act on comes out as LLMError: a refusal, a cut-off answer, a timeout, a refused or
failed request. The SDK retries what is worth retrying (connection errors, 408, 409, 429 and 5xx) before that.
"""

import base64
import json
from collections.abc import Mapping, Sequence
from typing import Any

import anthropic
from anthropic.types import Message

from openstall_agents.adapters.llm import JSONObject, LLMError
from openstall_agents.adapters.media import Media

# The models that take server-side fallbacks on the Claude API: a request one of them declines is answered by a model
# the API picks for that kind of refusal, inside the same call.
FALLBACK_MODELS = frozenset({"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"
IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})


class ClaudeLLM:
    """The LLM protocol on Claude. The model comes from LLM_MODEL (default claude-sonnet-5-5)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        max_tokens: int = 4096,
        effort: str = "low",
        timeout: float = 30.0,
        max_retries: int = 2,
        http_client: anthropic.DefaultHttpxClient | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self.client = anthropic.Anthropic(
            api_key=api_key, timeout=timeout, max_retries=max_retries, http_client=http_client
        )

    def generate_text(self, prompt: str, *, system: str | None = None, images: Sequence[Media] = ()) -> str:
        return _text(self._create(prompt, system, images, {"effort": self.effort}))

    def generate_json(
        self,
        prompt: str,
        *,
        schema: Mapping[str, Any],
        system: str | None = None,
        images: Sequence[Media] = (),
    ) -> JSONObject:
        output_config = {"effort": self.effort, "format": {"type": "json_schema", "schema": dict(schema)}}
        text = _text(self._create(prompt, system, images, output_config))
        try:
            answer = json.loads(text)
        except json.JSONDecodeError as error:
            raise LLMError("the model's answer was not JSON") from error
        if not isinstance(answer, dict):
            raise LLMError("the model's answer was not a JSON object")
        return answer

    def close(self) -> None:
        self.client.close()

    def _create(
        self, prompt: str, system: str | None, images: Sequence[Media], output_config: dict[str, Any]
    ) -> Message:
        content: list[dict[str, Any]] = [_image_block(image) for image in images]
        content.append({"type": "text", "text": prompt})
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": content}],
            "output_config": output_config,
        }
        if system:
            params["system"] = system
        try:
            if self.model in FALLBACK_MODELS:
                message: Any = self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
            else:
                message = self.client.messages.create(**params)
        except anthropic.APITimeoutError as error:
            raise LLMError("the model took too long to answer") from error
        except anthropic.APIConnectionError as error:
            raise LLMError("the model could not be reached") from error
        except anthropic.RateLimitError as error:
            raise LLMError("the model is rate limited; try again shortly") from error
        except anthropic.APIStatusError as error:
            raise LLMError(f"the model's API refused the request ({error.status_code})") from error
        if message.stop_reason == "refusal":
            raise LLMError("the model declined to answer")
        if message.stop_reason == "max_tokens":
            raise LLMError("the model's answer was cut off")
        return message  # type: ignore[no-any-return]


def _image_block(image: Media) -> dict[str, Any]:
    if image.media_type not in IMAGE_TYPES:
        raise LLMError(f"the model cannot read {image.media_type} files")
    data = base64.standard_b64encode(image.data).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": image.media_type, "data": data}}


def _text(message: Any) -> str:
    texts = [block.text for block in message.content if block.type == "text"]
    if not texts:
        raise LLMError("the model's answer had no text")
    return "".join(texts)
