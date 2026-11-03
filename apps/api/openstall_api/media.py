"""Seller media: the photos and voice notes sellers send in chats, kept in a MediaStore.

LocalMediaStore keeps them in a folder (MEDIA_DIR). On Render that folder is a persistent disk (render.yaml), so media
survives deploys. Files are named by a hash of their bytes, so the same photo sent twice is stored once, and names
cannot be guessed. Only photos and audio are accepted: never HTML or SVG, which a browser could run as a page.
"""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from openstall_api.settings import ENV_FILE, get_settings

MAX_BYTES = 16 * 1024 * 1024  # WhatsApp's own limit for photos and voice notes
URL_PREFIX = "/media/uploads"

# What a seller may send, and the file extension each is stored under.
ALLOWED_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "audio/ogg": ".ogg",  # WhatsApp voice notes
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/amr": ".amr",
    "audio/webm": ".webm",  # voice recorded in the browser on /seller-chat
    "audio/wav": ".wav",
}
KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{2,4}$")


class MediaRejected(ValueError):
    """A file we do not keep: the wrong kind, empty, or too big. The message can be shown to the seller."""


@dataclass(frozen=True)
class StoredMedia:
    key: str  # the file's name in the store, such as 3f9a...c1.jpg
    content_type: str
    size: int

    @property
    def url(self) -> str:
        """Where the API serves it, as a path: the web app adds the API's address."""
        return f"{URL_PREFIX}/{self.key}"


class MediaStore(Protocol):
    def save(self, data: bytes, content_type: str) -> StoredMedia: ...

    def read(self, key: str) -> bytes: ...


def media_type(content_type: str) -> str:
    """"image/jpeg; charset=binary" -> "image/jpeg"."""
    return content_type.split(";", 1)[0].strip().lower()


class LocalMediaStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, data: bytes, content_type: str) -> StoredMedia:
        kind = media_type(content_type)
        if kind not in ALLOWED_TYPES:
            raise MediaRejected(f"Only photos and voice notes can be kept, not {kind or 'this kind of file'}.")
        if not data:
            raise MediaRejected("The file is empty.")
        if len(data) > MAX_BYTES:
            raise MediaRejected(f"The file is {len(data) / 1024 / 1024:.1f} MB; the most we keep is 16 MB.")
        key = hashlib.sha256(data).hexdigest()[:32] + ALLOWED_TYPES[kind]
        path = self.root / key
        if not path.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            partial = path.with_name(f".{key}.{os.getpid()}.part")  # written whole, then renamed into place
            partial.write_bytes(data)
            os.replace(partial, path)
        return StoredMedia(key=key, content_type=kind, size=len(data))

    def read(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def path(self, key: str) -> Path:
        if not KEY_PATTERN.match(key):
            raise KeyError(f"No media called {key!r}")
        return self.root / key


def media_root() -> Path:
    """MEDIA_DIR, with a relative path taken from the repo root, so it does not depend on where the API starts."""
    root = Path(get_settings().MEDIA_DIR)
    return root if root.is_absolute() else ENV_FILE.parent / root


def get_media_store() -> LocalMediaStore:
    return LocalMediaStore(media_root())
