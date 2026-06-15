"""Thin wrapper around the Supabase client (Postgres + Storage).

Both the ingestion CLI and the bot share this module. The Supabase Python client
is synchronous; the bot calls these helpers inside ``asyncio.to_thread`` so it
never blocks the event loop (see ``bot/search.py`` and ``bot/handlers.py``).
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from .config import get_settings
from .models import Book, BookFile, SearchResult


@lru_cache(maxsize=1)
def get_client() -> Client:
    """Return a cached Supabase client authenticated with the service-role key."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_key)


# ── Catalog writes (ingestion) ───────────────────────────────────────────────
def upsert_book(book: Book) -> str:
    """Insert or update a book by its (source, source_id) key. Returns the book id."""
    client = get_client()
    payload = {
        "title": book.title,
        "author": book.author,
        "language": book.language,
        "source": book.source,
        "source_id": book.source_id,
        "description": book.description,
        "cover_url": book.cover_url,
    }
    res = (
        client.table("books")
        .upsert(payload, on_conflict="source,source_id")
        .execute()
    )
    return res.data[0]["id"]


def upsert_book_file(book_id: str, file: BookFile) -> None:
    """Insert or update a file row for a book, keyed by (book_id, format)."""
    client = get_client()
    payload = {
        "book_id": book_id,
        "format": file.format,
        "storage_path": file.storage_path,
        "size_bytes": file.size_bytes,
    }
    client.table("book_files").upsert(payload, on_conflict="book_id,format").execute()


def book_file_exists(book_id: str, fmt: str) -> bool:
    """True if a file of the given format already exists for the book (idempotent ingest)."""
    client = get_client()
    res = (
        client.table("book_files")
        .select("id")
        .eq("book_id", book_id)
        .eq("format", fmt)
        .limit(1)
        .execute()
    )
    return bool(res.data)


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
def search_books(query: str, limit: int, offset: int) -> list[SearchResult]:
    """Call the ``search_books`` Postgres function and return typed results."""
    client = get_client()
    res = client.rpc(
        "search_books", {"q": query, "lim": limit, "off": offset}
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


def get_book(book_id: str) -> dict | None:
    """Return a book row (title/author) by id, or None."""
    client = get_client()
    res = (
        client.table("books")
        .select("id, title, author")
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
