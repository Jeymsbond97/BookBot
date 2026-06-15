"""Common provider interface + the normalized result they return.

A provider knows *one* way to find a book (web PDF, YouTube audio, admin upload).
Keeping them behind a single protocol lets the orchestrator add or swap sources
without touching the bot — and lets licensed sources be prioritized later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class FetchResult:
    """A fetched file plus the metadata needed to catalog and deliver it."""

    title: str
    content: bytes
    fmt: str  # 'pdf' | 'mp3'
    source: str  # 'web' | 'youtube' | 'admin'
    source_ref: str  # origin url/id (dedup + re-fetch + takedown)
    author: str | None = None
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.size_bytes is None:
            self.size_bytes = len(self.content)


class SourceProvider(Protocol):
    name: str
    fmt: str  # 'pdf' | 'mp3'

    def fetch(self, title: str, language: str) -> FetchResult | None: ...
