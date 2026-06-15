"""Ingest public-domain ebooks from Project Gutenberg via the Gutendex API.

Gutendex (https://gutendex.com) is a free JSON API over the Gutenberg catalog.
We pull metadata, pick the best PDF/EPUB download links, and store the files.
"""

from __future__ import annotations

import time

import httpx

from ..config import get_settings
from ..models import Book
from .. import db
from .storage import fetch_and_store

GUTENDEX_URL = "https://gutendex.com/books"

# Preferred MIME → our format label. Order matters (best first).
FORMAT_MAP: list[tuple[str, str]] = [
    ("application/pdf", "pdf"),
    ("application/epub+zip", "epub"),
]


def _pick_downloads(formats: dict[str, str]) -> dict[str, str]:
    """Map a Gutendex ``formats`` dict to {our_format: url} for the types we want."""
    picked: dict[str, str] = {}
    for mime, label in FORMAT_MAP:
        for key, url in formats.items():
            # keys look like 'application/epub+zip' sometimes with '; charset' suffix
            if key.startswith(mime) and label not in picked and not url.endswith(".zip"):
                picked[label] = url
    return picked


def ingest(limit: int, lang: str = "en") -> int:
    """Fetch up to ``limit`` ebooks for the given language. Returns count ingested."""
    settings = get_settings()
    ingested = 0
    url: str | None = f"{GUTENDEX_URL}?languages={lang}&mime_type=application"

    with httpx.Client(headers={"User-Agent": "BookBot/0.1 (+public-domain ingest)"}) as http:
        while url and ingested < limit:
            resp = http.get(url, timeout=60, follow_redirects=True)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("results", []):
                if ingested >= limit:
                    break

                downloads = _pick_downloads(item.get("formats", {}))
                if not downloads:
                    continue  # nothing we can serve

                authors = item.get("authors") or []
                author = authors[0]["name"] if authors else None
                languages = item.get("languages") or [lang]

                book = Book(
                    title=item["title"],
                    author=author,
                    language=languages[0],
                    source="gutenberg",
                    source_id=str(item["id"]),
                    description=", ".join(item.get("subjects", [])[:5]) or None,
                )
                book_id = db.upsert_book(book)

                for fmt, dl_url in downloads.items():
                    if db.book_file_exists(book_id, fmt):
                        continue
                    try:
                        size = fetch_and_store(book_id, fmt, dl_url, http)
                        if size is None:
                            print(f"  ↳ skipped {fmt} (too large): {book.title}")
                        else:
                            print(f"  ↳ stored {fmt} ({size // 1024} KB): {book.title}")
                    except Exception as exc:  # keep going on individual failures
                        print(f"  ↳ failed {fmt} for {book.title}: {exc}")
                    time.sleep(settings.ingest_delay_seconds)

                ingested += 1
                print(f"[{ingested}/{limit}] {book.title} — {book.author or 'Unknown'}")

            url = data.get("next")

    return ingested
