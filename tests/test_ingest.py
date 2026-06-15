"""Tests for the pure helpers in the ingestion adapters (no network needed)."""

from __future__ import annotations

from bookbot.ingest.gutenberg import _pick_downloads
from bookbot.ingest.librivox import _archive_identifier


def test_pick_downloads_prefers_pdf_then_epub():
    formats = {
        "application/epub+zip": "https://example.org/book.epub",
        "application/pdf": "https://example.org/book.pdf",
        "text/html": "https://example.org/book.html",
    }
    picked = _pick_downloads(formats)
    assert picked == {
        "pdf": "https://example.org/book.pdf",
        "epub": "https://example.org/book.epub",
    }


def test_pick_downloads_skips_zip_archives():
    formats = {"application/epub+zip": "https://example.org/book.epub.zip"}
    assert _pick_downloads(formats) == {}


def test_pick_downloads_empty():
    assert _pick_downloads({}) == {}


def test_archive_identifier_from_details_url():
    assert _archive_identifier(None, "https://archive.org/details/myitem_1234") == "myitem_1234"


def test_archive_identifier_none():
    assert _archive_identifier(None, None) is None
