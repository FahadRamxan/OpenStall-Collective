"""Interfaces to the AI services the agents use, each with a deterministic fake for tests and offline demos.

The API's adapter registry (openstall_api.adapters) picks the fake or the real implementation by OPENSTALL_MODE.
"""

from openstall_agents.adapters.embedder import Embedder, FakeEmbedder
from openstall_agents.adapters.image_search import FakeImageSearch, ImageSearch, WebMatches
from openstall_agents.adapters.llm import LLM, FakeLLM, LLMCall, LLMError
from openstall_agents.adapters.media import Media
from openstall_agents.adapters.speech import FakeSpeechToText, SpeechToText, Transcript

__all__ = [
    "LLM",
    "Embedder",
    "FakeEmbedder",
    "FakeImageSearch",
    "FakeLLM",
    "FakeSpeechToText",
    "ImageSearch",
    "LLMCall",
    "LLMError",
    "Media",
    "SpeechToText",
    "Transcript",
    "WebMatches",
]
