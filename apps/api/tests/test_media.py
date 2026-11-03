"""Seller media: photos and voice notes are kept once, by a hash of their bytes, and only if they are photos or audio
of a sensible size. The API serves them back."""

import hashlib

import pytest
from fastapi.testclient import TestClient

from openstall_api.main import app
from openstall_api.media import MAX_BYTES, LocalMediaStore, MediaRejected, get_media_store

client = TestClient(app)
PHOTO = b"\xff\xd8\xff\xe0 a made-up jpeg"
VOICE_NOTE = b"OggS a made-up voice note"


def test_a_photo_is_kept_under_a_hash_of_its_bytes(test_media_dir):
    stored = get_media_store().save(PHOTO, "image/jpeg")

    assert stored.key == hashlib.sha256(PHOTO).hexdigest()[:32] + ".jpg"
    assert stored.content_type == "image/jpeg"
    assert stored.size == len(PHOTO)
    assert stored.url == f"/media/uploads/{stored.key}"
    assert (test_media_dir / stored.key).read_bytes() == PHOTO


def test_the_same_file_sent_twice_is_kept_once(test_media_dir):
    store = get_media_store()

    first = store.save(VOICE_NOTE, "audio/ogg; codecs=opus")
    second = store.save(VOICE_NOTE, "audio/ogg")

    assert first == second
    assert first.key.endswith(".ogg")
    assert [path.name for path in test_media_dir.iterdir()] == [first.key]


@pytest.mark.parametrize(
    ("data", "content_type", "reason"),
    [
        (b"<svg onload=alert(1)>", "image/svg+xml", "Only photos and voice notes"),
        (b"<html></html>", "text/html", "Only photos and voice notes"),
        (b"%PDF-1.7", "application/pdf", "Only photos and voice notes"),
        (b"", "image/jpeg", "The file is empty."),
        (b"x" * (MAX_BYTES + 1), "image/jpeg", "the most we keep is 16 MB"),
    ],
)
def test_anything_but_a_sensible_photo_or_voice_note_is_refused(test_media_dir, data, content_type, reason):
    with pytest.raises(MediaRejected, match=reason):
        get_media_store().save(data, content_type)

    assert not test_media_dir.exists() or not any(test_media_dir.iterdir())


def test_a_16_mb_file_is_still_kept(tmp_path):
    stored = LocalMediaStore(tmp_path).save(b"x" * MAX_BYTES, "audio/mpeg")

    assert stored.size == MAX_BYTES


@pytest.mark.parametrize("key", ["../secrets.txt", "..\\..\\.env", "abc.jpg", "a" * 32 + ".jpg/../x"])
def test_only_names_the_store_made_can_be_read(key):
    with pytest.raises(KeyError):
        get_media_store().read(key)


def test_the_api_serves_a_stored_file_with_its_type_and_lets_browsers_keep_it():
    stored = get_media_store().save(PHOTO, "image/jpeg")

    response = client.get(stored.url)

    assert response.status_code == 200
    assert response.content == PHOTO
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "immutable" in response.headers["cache-control"]


@pytest.mark.parametrize("path", ["/media/uploads/" + "0" * 32 + ".jpg", "/media/uploads/not-a-key.jpg"])
def test_the_api_does_not_find_media_it_never_stored(path):
    assert client.get(path).status_code == 404
