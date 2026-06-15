"""Tests for search pagination and result models (no live Supabase needed)."""

from __future__ import annotations

import pytest

from bookbot import db
from bookbot.bot import search as search_mod
from bookbot.models import SearchResult


def _fake_rows(n: int) -> list[SearchResult]:
    return [
        SearchResult(id=f"id-{i}", title=f"Book {i}", author="Author", language="en",
                     formats=["pdf"])
        for i in range(n)
    ]


def test_from_row_and_label():
    r = SearchResult.from_row(
        {"id": "x", "title": "Dracula", "author": "Bram Stoker",
         "language": "en", "formats": ["pdf", "epub"]}
    )
    assert r.id == "x"
    assert r.label == "Dracula — Bram Stoker [PDF] [EPUB]"


def test_label_without_author():
    r = SearchResult(id="x", title="Anon", author=None, language="en", formats=[])
    assert r.label == "Anon"


@pytest.mark.asyncio
async def test_search_page_detects_next(monkeypatch):
    # Return PAGE_SIZE + 1 rows → has_next should be True, but only PAGE_SIZE returned.
    def fake_search(query, limit, offset):
        assert limit == search_mod.PAGE_SIZE + 1
        return _fake_rows(search_mod.PAGE_SIZE + 1)

    monkeypatch.setattr(db, "search_books", fake_search)
    results, has_next = await search_mod.search_page("anything", page=0)
    assert len(results) == search_mod.PAGE_SIZE
    assert has_next is True


@pytest.mark.asyncio
async def test_search_page_last_page(monkeypatch):
    def fake_search(query, limit, offset):
        assert offset == search_mod.PAGE_SIZE  # page 1
        return _fake_rows(2)

    monkeypatch.setattr(db, "search_books", fake_search)
    results, has_next = await search_mod.search_page("anything", page=1)
    assert len(results) == 2
    assert has_next is False
