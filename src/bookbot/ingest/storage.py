"""Helpers for downloading source files and storing them in Supabase Storage."""

from __future__ import annotations

import httpx

from ..config import get_settings
from ..models import BookFile
from .. import db

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "epub": "application/epub+zip",
    "mp3": "audio/mpeg",
}


def storage_path_for(book_id: str, fmt: str) -> str:
    """Deterministic path within the bucket: ``{book_id}/{fmt}.{fmt}``."""
    return f"{book_id}/{fmt}.{fmt}"


def fetch_and_store(book_id: str, fmt: str, url: str, client: httpx.Client) -> int | None:
    """Download ``url`` and upload it to storage. Returns the size in bytes.

    Returns ``None`` (and skips upload) if the file exceeds ``MAX_FILE_MB`` so we
    never store something the Telegram Bot API cannot send.
    """
    settings = get_settings()
    resp = client.get(url, follow_redirects=True, timeout=120)
    resp.raise_for_status()
    content = resp.content

    if len(content) > settings.max_file_bytes:
        return None

    path = storage_path_for(book_id, fmt)
    db.upload_file(path, content, CONTENT_TYPES.get(fmt, "application/octet-stream"))
    db.upsert_book_file(
        book_id, BookFile(format=fmt, storage_path=path, size_bytes=len(content))
    )
    return len(content)
