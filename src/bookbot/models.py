"""Data models used by the bot and the catalog layer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BookFile:
    """A single file belonging to a book.

    ``storage_path`` is set for PDFs (Supabase Storage); audio files are not
    stored, so it is ``None`` for mp3 and only ``telegram_file_id`` is kept.
    """

    format: str  # 'pdf' | 'mp3'
    storage_path: str | None = None
    size_bytes: int | None = None
    telegram_file_id: str | None = None
    id: str | None = None


@dataclass(slots=True)
class SearchResult:
    """A row returned by the `search_books` RPC."""

    id: str
    title: str
    author: str | None
    language: str | None
    formats: list[str]

    @classmethod
    def from_row(cls, row: dict) -> "SearchResult":
        return cls(
            id=row["id"],
            title=row["title"],
            author=row.get("author"),
            language=row.get("language"),
            formats=row.get("formats") or [],
        )

    @property
    def label(self) -> str:
        """Short one-line label for an inline result button."""
        base = self.title if self.author is None else f"{self.title} — {self.author}"
        badges = " ".join(f"[{f.upper()}]" for f in self.formats)
        return f"{base} {badges}".strip()
