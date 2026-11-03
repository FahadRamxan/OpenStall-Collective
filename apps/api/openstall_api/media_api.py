"""Seller media over HTTP: GET /media/uploads/{key} serves a stored photo or voice note."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from openstall_api.media import ALLOWED_TYPES, URL_PREFIX, get_media_store

router = APIRouter(tags=["media"])

TYPE_OF_EXTENSION = {extension: kind for kind, extension in ALLOWED_TYPES.items()}


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
