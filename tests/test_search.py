"""Tests for search pagination, ranking and result models (no live Supabase)."""

from __future__ import annotations

import pytest

from bookbot import db
from bookbot.bot import ranking
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
    def fake_search(query, limit, offset, fmt=None, language=None):
        assert limit == search_mod.PAGE_SIZE + 1
        assert fmt == "pdf"
        return _fake_rows(search_mod.PAGE_SIZE + 1)

    monkeypatch.setattr(db, "search_books", fake_search)
    results, has_next = await search_mod.search_page("anything", page=0, fmt="pdf")
    assert len(results) == search_mod.PAGE_SIZE
    assert has_next is True


@pytest.mark.asyncio
async def test_search_page_last_page(monkeypatch):
    def fake_search(query, limit, offset, fmt=None, language=None):
        assert offset == search_mod.PAGE_SIZE  # page 1
        return _fake_rows(2)

    monkeypatch.setattr(db, "search_books", fake_search)
    results, has_next = await search_mod.search_page("anything", page=1)
    assert len(results) == 2
    assert has_next is False


# ── Ranking ──────────────────────────────────────────────────────────────────
def _res(title: str, author: str | None = None) -> SearchResult:
    return SearchResult(id=title, title=title, author=author, language="uz", formats=["pdf"])


def test_best_exact_returns_close_unique_hit():
    results = [_res("O'tkan kunlar"), _res("Mehrobdan chayon")]
    hit = ranking.best_exact("otkan kunlar", results)
    assert hit is not None and hit.title == "O'tkan kunlar"


def test_best_exact_none_when_ambiguous():
    # Two near-identical titles → don't guess, show the list instead.
    results = [_res("Sahar"), _res("Sahar 2")]
    assert ranking.best_exact("sahar", results) is None


def test_best_exact_none_when_no_close_match():
    results = [_res("Alkimyogar"), _res("Jonathan Livingston")]
    assert ranking.best_exact("kapitalizm", results) is None


def test_rerank_orders_by_relevance():
    results = [_res("Boshqa kitob"), _res("Atomic Habits"), _res("Yana boshqa")]
    ranked = ranking.rerank("atomic habits", results)
    assert ranked[0].title == "Atomic Habits"
