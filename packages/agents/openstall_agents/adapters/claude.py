"""The real language model in sandbox mode: Claude, through Anthropic's Python SDK. Fake mode uses FakeLLM instead,
and FakeBuyer stands in for ClaudeBuyer, the buyer's AI agent.

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
from openstall_agents.buyer_agent import AgentTurn, ToolCall, ToolResult, ToolSpec
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
        return _send(self.client, params)  # type: ignore[no-any-return]


def _send(client: anthropic.Anthropic, params: dict[str, Any]) -> Any:
    """One Messages API request, with server-side fallbacks for the models that take them. Every failure an agent
    can act on comes out as LLMError, in words."""
    try:
        if params["model"] in FALLBACK_MODELS:
            message: Any = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
        else:
            message = client.messages.create(**params)
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
    return message


class ClaudeBuyer:
    """A buyer's AI agent on Claude (prompt 30): each conversation is one person's request, one Messages API
    request per turn. The model chooses the storefront's tools itself (tool_choice stays auto: current models refuse
    forced tool use), and each answer is appended to the conversation whole, so its thinking blocks stay valid on
    the next turn. Effort is medium, for a handful of tool calls; thinking stays the model's default (adaptive).
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        max_tokens: int = 16000,
        effort: str = "medium",
        timeout: float = 90.0,
        max_retries: int = 2,
        http_client: anthropic.DefaultHttpxClient | None = None,
    ) -> None:
        self.model = model
        self.label = f"Claude ({model})"
        self.max_tokens = max_tokens
        self.effort = effort
        self.client = anthropic.Anthropic(
            api_key=api_key, timeout=timeout, max_retries=max_retries, http_client=http_client
        )

    def conversation(self) -> "ClaudeBuyerConversation":
        return ClaudeBuyerConversation(self)

    def close(self) -> None:
        self.client.close()


class ClaudeBuyerConversation:
    """One request's conversation with the buyer's agent: the system prompt, the tools and every turn so far."""

    def __init__(self, buyer: ClaudeBuyer) -> None:
        self.buyer = buyer
        self.system = ""
        self.tools: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []

    def begin(self, system: str, request: str, tools: Sequence[ToolSpec]) -> AgentTurn:
        self.system = system
        self.tools = [
            {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema} for tool in tools
        ]
        self.messages.append({"role": "user", "content": request})
        return self._turn()

    def answer(self, results: Sequence[ToolResult]) -> AgentTurn:
        # Every answer to this turn's calls in one message, a failed call marked as an error rather than dropped.
        self.messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": result.call.id,
                        "content": result.text,
                        "is_error": result.is_error,
                    }
                    for result in results
                ],
            }
        )
        return self._turn()

    def _turn(self) -> AgentTurn:
        params: dict[str, Any] = {
            "model": self.buyer.model,
            "max_tokens": self.buyer.max_tokens,
            "system": self.system,
            "tools": self.tools,
            "messages": self.messages,
            "output_config": {"effort": self.buyer.effort},
        }
        message = _send(self.buyer.client, params)
        # The whole answer goes back next turn, unchanged: thinking blocks are only valid in the conversation that
        # made them, exactly as they came.
        self.messages.append({"role": "assistant", "content": message.content})
        said = "".join(block.text for block in message.content if block.type == "text")
        calls = tuple(
            ToolCall(block.id, block.name, dict(block.input)) for block in message.content if block.type == "tool_use"
        )
        if message.stop_reason == "tool_use" and not calls:
            raise LLMError("the model asked for a tool but named none")
        return AgentTurn(said, calls)


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
