"""Text embeddings, used to group searches nobody could serve (spec 3.8, Demand Radar).

The real adapter comes with Demand Radar. FakeEmbedder stands in for it in fake mode.
"""

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

DIMENSIONS = 256


@runtime_checkable
class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One unit-length vector per text, in the same order."""
        ...


class FakeEmbedder:
    """Counts each word into one of a fixed number of slots, so texts that share words point the same way.

    The slot comes from SHA-256, not hash(), which Python seeds differently in every process. Records each call's
    texts in `calls`.
    """

    def __init__(self, dimensions: int = DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.calls: list[tuple[str, ...]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(tuple(texts))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in re.findall(r"\w+", text.lower()):
            slot = int.from_bytes(hashlib.sha256(word.encode()).digest()[:8], "big") % self.dimensions
            vector[slot] += 1.0
        length = math.sqrt(sum(value * value for value in vector))
        return [value / length for value in vector] if length else vector
