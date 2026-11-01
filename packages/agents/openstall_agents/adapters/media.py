"""Photos and voice notes handed to the AI adapters: bytes with their content type."""

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, repr=False)
class Media:
    """One photo or voice note, for example from WhatsApp or the /seller-chat page."""

    data: bytes
    media_type: str  # for example "image/jpeg" or "audio/ogg"

    @property
    def sha256(self) -> str:
        """A stable fingerprint, so fakes can answer per file and test failures can name a file without its bytes."""
        return hashlib.sha256(self.data).hexdigest()

    def __repr__(self) -> str:
        return f"Media({self.media_type!r}, {len(self.data)} bytes, sha256={self.sha256[:12]})"
