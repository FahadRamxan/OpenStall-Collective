"""The language model: text and photos in, plain text or JSON out (spec 3.1, 3.3, 3.4 and 3.6).

The real adapter (Claude, model from LLM_MODEL) comes with the listing builder. FakeLLM stands in for it in fake mode.
"""

import copy
import json
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from openstall_agents.adapters.media import Media

JSONObject = dict[str, Any]


@runtime_checkable
class LLM(Protocol):
    """A model that reads text and images and answers in plain text or in JSON."""

    def generate_text(self, prompt: str, *, system: str | None = None, images: Sequence[Media] = ()) -> str:
        """The model's answer as plain text."""
        ...

    def generate_json(
        self,
        prompt: str,
        *,
        schema: Mapping[str, Any],
        system: str | None = None,
        images: Sequence[Media] = (),
    ) -> JSONObject:
        """The model's answer as a JSON object that matches `schema`, a JSON Schema."""
        ...


@dataclass(frozen=True)
class LLMCall:
    """One request made to FakeLLM, as the code under test made it."""

    kind: Literal["text", "json"]
    prompt: str
    system: str | None
    images: tuple[Media, ...]
    schema: Mapping[str, Any] | None


Reply = str | JSONObject
Responder = Callable[[LLMCall], Reply]


class FakeLLM:
    """A stand-in model: no network and no randomness, and every request is recorded in `calls`.

    Each answer is the next queued reply if there is one, then the responder's answer if one is set, then a fixed
    default: an echo of the prompt for text, an empty object for JSON. A JSON reply may be given as a JSON string,
    like raw model output.
    """

    def __init__(self, replies: Sequence[Reply] = (), responder: Responder | None = None) -> None:
        self.calls: list[LLMCall] = []
        self.responder = responder
        self._queued: deque[Reply] = deque(replies)

    def queue(self, *replies: Reply) -> None:
        """Answers to give, in order, before the responder or the default."""
        self._queued.extend(replies)

    def generate_text(self, prompt: str, *, system: str | None = None, images: Sequence[Media] = ()) -> str:
        reply = self._answer(LLMCall("text", prompt, system, tuple(images), None))
        if not isinstance(reply, str):
            raise TypeError(f"FakeLLM: a text request needs a str reply, got {type(reply).__name__}")
        return reply

    def generate_json(
        self,
        prompt: str,
        *,
        schema: Mapping[str, Any],
        system: str | None = None,
        images: Sequence[Media] = (),
    ) -> JSONObject:
        reply = self._answer(LLMCall("json", prompt, system, tuple(images), schema))
        if isinstance(reply, str):
            reply = json.loads(reply)
        if not isinstance(reply, dict):
            raise TypeError(f"FakeLLM: a JSON request needs an object reply, got {type(reply).__name__}")
        # A copy, so code that edits the answer cannot change a reply a test is still holding.
        return copy.deepcopy(reply)

    def _answer(self, call: LLMCall) -> Reply:
        self.calls.append(call)
        if self._queued:
            return self._queued.popleft()
        if self.responder is not None:
            return self.responder(call)
        return {} if call.kind == "json" else f"Fake reply to: {call.prompt[:80]}"
