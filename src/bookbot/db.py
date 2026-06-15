"""Thin wrapper around the Supabase client (Postgres + Storage).

The Supabase Python client is synchronous; the bot calls these helpers inside
``asyncio.to_thread`` so it never blocks the event loop (see ``bot/search.py``,
``bot/handlers.py`` and ``bot/delivery.py``).
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from .config import get_settings
from .models import BookFile, SearchResult


@lru_cache(maxsize=1)
def get_client() -> Client:
    """Return a cached Supabase client authenticated with the service-role key."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_key)


# ── Categories ───────────────────────────────────────────────────────────────
def get_categories() -> list[dict]:
    """Return all categories ordered by id (slug + localized names)."""
    client = get_client()
    res = (
        client.table("categories")
        .select("slug, name_uz, name_en")
        .order("id")
        .execute()
    )
    return res.data or []


# ── Search & reads (bot) ─────────────────────────────────────────────────────
def search_books(
    query: str,
    limit: int,
    offset: int,
    fmt: str | None = None,
    language: str | None = None,
) -> list[SearchResult]:
    """Call the ``search_books`` Postgres function and return typed results.

    ``fmt`` ('pdf' | 'mp3') restricts results to books that have a file in that
    format; ``language`` ('uz' | 'en' | …) restricts by language. ``None`` for
    either means "no filter".
    """
    client = get_client()
    res = client.rpc(
        "search_books",
        {"q": query, "lang": language, "fmt": fmt, "lim": limit, "off": offset},
    ).execute()
    return [SearchResult.from_row(row) for row in (res.data or [])]


def get_book_files(book_id: str) -> list[BookFile]:
    """Return all files for a book."""
    client = get_client()
    res = (
        client.table("book_files")
        .select("id, format, storage_path, size_bytes, telegram_file_id")
        .eq("book_id", book_id)
        .order("format")
        .execute()
    )
    return [
        BookFile(
            id=row["id"],
            format=row["format"],
            storage_path=row["storage_path"],
            size_bytes=row.get("size_bytes"),
            telegram_file_id=row.get("telegram_file_id"),
        )
        for row in (res.data or [])
    ]


def get_book_file(file_id: str) -> BookFile | None:
    """Return a single file row by its id."""
    client = get_client()
    res = (
        client.table("book_files")
        .select("id, format, storage_path, size_bytes, telegram_file_id")
        .eq("id", file_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    return BookFile(
        id=row["id"],
        format=row["format"],
        storage_path=row["storage_path"],
        size_bytes=row.get("size_bytes"),
        telegram_file_id=row.get("telegram_file_id"),
    )


def find_book_by_title(title: str, language: str | None = None) -> str | None:
    """Return an existing book id matching ``title`` (case-insensitive), or None."""
    client = get_client()
    q = client.table("books").select("id").ilike("title", title)
    if language:
        q = q.eq("language", language)
    res = q.limit(1).execute()
    return res.data[0]["id"] if res.data else None


def _upsert_book_row(
    title: str,
    *,
    author: str | None,
    language: str,
    source: str,
    source_ref: str | None,
    description: str | None,
    cover_url: str | None,
) -> str:
    """Find-or-create a book row (dedup by title+language); update metadata."""
    client = get_client()
    payload = {
        "title": title,
        "author": author,
        "language": language,
        "source": source,
        "source_ref": source_ref,
        "description": description,
        "cover_url": cover_url,
    }
    book_id = find_book_by_title(title, language)
    if book_id is None:
        res = client.table("books").insert(payload).execute()
        return res.data[0]["id"]
    # Keep existing row but fill in any newly-found metadata.
    updates = {k: v for k, v in payload.items() if v is not None}
    if updates:
        client.table("books").update(updates).eq("id", book_id).execute()
    return book_id


def save_pdf_book(
    title: str,
    content: bytes,
    *,
    author: str | None = None,
    language: str = "uz",
    source: str = "web",
    source_ref: str | None = None,
    description: str | None = None,
    cover_url: str | None = None,
) -> str:
    """Persist a fetched PDF: upload bytes to Storage + insert book/file rows.

    Deduplicates by (title, language) so a re-fetch of the same book reuses the
    existing catalog entry instead of creating a copy. Returns the book id.
    """
    client = get_client()
    book_id = _upsert_book_row(
        title, author=author, language=language, source=source,
        source_ref=source_ref, description=description, cover_url=cover_url,
    )
    storage_path = f"web/{book_id}.pdf"
    upload_file(storage_path, content, "application/pdf")
    client.table("book_files").upsert(
        {
            "book_id": book_id,
            "format": "pdf",
            "storage_path": storage_path,
            "size_bytes": len(content),
        },
        on_conflict="book_id,format",
    ).execute()
    return book_id


def save_audio_book(
    title: str,
    *,
    youtube_id: str,
    telegram_file_ids: list[str],
    author: str | None = None,
    language: str = "uz",
    source_ref: str | None = None,
    description: str | None = None,
    cover_url: str | None = None,
    size_bytes: int | None = None,
) -> str:
    """Persist audio metadata (NO file stored): book row + book_file with the
    YouTube id and cached Telegram file_id(s) (comma-joined for split parts).
    """
    client = get_client()
    book_id = _upsert_book_row(
        title, author=author, language=language, source="youtube",
        source_ref=source_ref, description=description, cover_url=cover_url,
    )
    client.table("book_files").upsert(
        {
            "book_id": book_id,
            "format": "mp3",
            "youtube_id": youtube_id,
            "telegram_file_id": ",".join(telegram_file_ids) or None,
            "size_bytes": size_bytes,
        },
        on_conflict="book_id,format",
    ).execute()
    return book_id


def get_book(book_id: str) -> dict | None:
    """Return a book row (title/author/language/description/cover) by id, or None."""
    client = get_client()
    res = (
        client.table("books")
        .select("id, title, author, language, description, cover_url")
        .eq("id", book_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def set_telegram_file_id(file_id: str, telegram_file_id: str) -> None:
    """Persist the cached Telegram file_id after the first successful send."""
    client = get_client()
    client.table("book_files").update(
        {"telegram_file_id": telegram_file_id}
    ).eq("id", file_id).execute()


# ── Storage ──────────────────────────────────────────────────────────────────
def upload_file(storage_path: str, content: bytes, content_type: str) -> None:
    """Upload bytes to the books bucket, overwriting if present."""
    settings = get_settings()
    client = get_client()
    client.storage.from_(settings.supabase_bucket).upload(
        path=storage_path,
        file=content,
        file_options={"content-type": content_type, "upsert": "true"},
    )


def download_file(storage_path: str) -> bytes:
    """Download a file's bytes from the books bucket."""
    settings = get_settings()
    client = get_client()
    return client.storage.from_(settings.supabase_bucket).download(storage_path)
