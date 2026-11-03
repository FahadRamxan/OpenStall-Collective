"""Media over HTTP, with caching headers: GET /media/uploads/{key} serves a photo or voice note a seller sent, and
SeedPhotos serves the seed photos under /media/seed/ (main.py mounts it)."""

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from openstall_api.media import ALLOWED_TYPES, URL_PREFIX, get_media_store

router = APIRouter(tags=["media"])

TYPE_OF_EXTENSION = {extension: kind for kind, extension in ALLOWED_TYPES.items()}

# A seed photo is a placeholder that the team replaces under the same name, so unlike an upload it can change: keep it
# for an hour, then ask again with its ETag (an unchanged photo is a 304 with no body).
SEED_PHOTO_CACHE = "public, max-age=3600"


class SeedPhotos(StaticFiles):
    """Static files with a Cache-Control header on every file served, unchanged (304) answers included."""

    def file_response(
        self, full_path: str | os.PathLike[str], stat_result: os.stat_result, scope: Scope, status_code: int = 200
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = SEED_PHOTO_CACHE
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


@router.get(URL_PREFIX + "/{key}")
def get_media(key: str) -> FileResponse:
    try:
        path = get_media_store().path(key)
    except KeyError:
        raise HTTPException(status_code=404) from None
    if not path.is_file():
        raise HTTPException(status_code=404)
    # A file's name is the hash of its bytes, so it never changes: browsers may keep it for good.
    return FileResponse(
        path,
        media_type=TYPE_OF_EXTENSION[path.suffix],
        headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"},
    )
