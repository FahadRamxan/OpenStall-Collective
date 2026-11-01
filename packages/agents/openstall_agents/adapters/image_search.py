"""Reverse image search: where else a product photo appears on the web (spec 3.7, photo originality).

Only through an official API, never by scraping. The real adapter comes with the photo originality check;
FakeImageSearch stands in for it in fake mode.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from openstall_agents.adapters.media import Media


@dataclass(frozen=True)
class WebMatches:
    """Where a photo was found. All empty means it was found nowhere."""

    full_matches: tuple[str, ...] = ()  # image URLs of exact copies
    partial_matches: tuple[str, ...] = ()  # image URLs of cropped or edited copies
    pages: tuple[str, ...] = ()  # web pages that show the photo

    @property
    def found(self) -> bool:
        return bool(self.full_matches or self.partial_matches or self.pages)


@runtime_checkable
class ImageSearch(Protocol):
    def find_matches(self, image: Media) -> WebMatches:
        """Copies of this photo on the web."""
        ...


class FakeImageSearch:
    """Finds nothing, except for photos a test has registered with add_matches. Records each photo in `calls`."""

    def __init__(self) -> None:
        self.calls: list[Media] = []
        self._matches: dict[str, WebMatches] = {}

    def add_matches(self, image: Media, matches: WebMatches) -> None:
        """What to find for this photo (the same bytes), from now on."""
        self._matches[image.sha256] = matches

    def find_matches(self, image: Media) -> WebMatches:
        self.calls.append(image)
        return self._matches.get(image.sha256, WebMatches())
