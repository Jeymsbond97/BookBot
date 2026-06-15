"""Ingest public-domain audiobooks from LibriVox.

LibriVox exposes a JSON feed (https://librivox.org/api/feed/audiobooks). Each
audiobook links to an Internet Archive item; the Archive metadata API lists the
individual MP3 chapter files. We store the first/representative MP3 chapter so the
file stays within Telegram's 50 MB send limit. (Whole-book zips are usually too
big; per-chapter MP3s fit naturally — see README "Telegram limits".)
"""

from __future__ import annotations

import time

import httpx

from ..config import get_settings
from ..models import Book
from .. import db
from .storage import fetch_and_store

LIBRIVOX_FEED = "https://librivox.org/api/feed/audiobooks"
ARCHIVE_META = "https://archive.org/metadata/{identifier}"


def _archive_identifier(url_zip: str | None, url_iarchive: str | None) -> str | None:
    """Extract the Internet Archive identifier from a LibriVox record."""
    if url_iarchive:
        # e.g. https://archive.org/details/some_identifier
        return url_iarchive.rstrip("/").split("/")[-1]
    return None


def _first_mp3(identifier: str, http: httpx.Client) -> tuple[str, int | None] | None:
    """Return (download_url, size_bytes) for the first MP3 chapter of an item."""
    resp = http.get(ARCHIVE_META.format(identifier=identifier), timeout=60)
    resp.raise_for_status()
    meta = resp.json()
    server = meta.get("server")
    directory = meta.get("dir")
    if not server or not directory:
        return None
    for f in meta.get("files", []):
        name = f.get("name", "")
        if name.lower().endswith(".mp3"):
            size = int(f["size"]) if f.get("size") else None
            return f"https://{server}{directory}/{name}", size
    return None


def ingest(limit: int) -> int:
    """Fetch up to ``limit`` audiobooks. Returns count ingested."""
    settings = get_settings()
    ingested = 0
    offset = 0
    page = 25

    with httpx.Client(headers={"User-Agent": "BookBot/0.1 (+public-domain ingest)"}) as http:
        while ingested < limit:
            resp = http.get(
                LIBRIVOX_FEED,
                params={"format": "json", "limit": page, "offset": offset},
                timeout=60,
            )
            resp.raise_for_status()
            books = resp.json().get("books", [])
            if not books:
                break
            offset += page

            for item in books:
                if ingested >= limit:
                    break

                identifier = _archive_identifier(
                    item.get("url_zip_file"), item.get("url_iarchive")
                )
                if not identifier:
                    continue

                book = Book(
                    title=item.get("title", "Untitled"),
                    author=(item.get("authors") or [{}])[0].get("last_name"),
                    language=item.get("language", "English"),
                    source="librivox",
                    source_id=str(item.get("id")),
                    description=(item.get("description") or "").strip()[:500] or None,
                )
                book_id = db.upsert_book(book)

                if db.book_file_exists(book_id, "mp3"):
                    ingested += 1
                    continue

                try:
                    found = _first_mp3(identifier, http)
                    if not found:
                        print(f"  ↳ no MP3 found for {book.title}")
                    else:
                        mp3_url, _ = found
                        size = fetch_and_store(book_id, "mp3", mp3_url, http)
                        if size is None:
                            print(f"  ↳ skipped mp3 (too large): {book.title}")
                        else:
                            print(f"  ↳ stored mp3 ({size // 1024} KB): {book.title}")
                except Exception as exc:
                    print(f"  ↳ failed mp3 for {book.title}: {exc}")

                time.sleep(settings.ingest_delay_seconds)
                ingested += 1
                print(f"[{ingested}/{limit}] {book.title} — {book.author or 'Unknown'}")

    return ingested
