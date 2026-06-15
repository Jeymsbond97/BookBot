"""Data models shared across the bot and ingestion code."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BookFile:
    """A single downloadable file belonging to a book."""

    format: str  # 'pdf' | 'epub' | 'mp3'
    storage_path: str
    size_bytes: int | None = None
    telegram_file_id: str | None = None
    id: str | None = None


@dataclass(slots=True)
class Book:
    """A catalog entry, optionally with its files attached."""

    title: str
    source: str  # 'gutenberg' | 'librivox' | 'archive'
    source_id: str
    author: str | None = None
    language: str = "en"
    description: str | None = None
    cover_url: str | None = None
    id: str | None = None
    files: list[BookFile] = field(default_factory=list)


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
