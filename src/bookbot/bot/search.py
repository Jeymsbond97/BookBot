"""Search logic for the bot — wraps the Postgres ``search_books`` RPC.

The Supabase client is synchronous, so each call is offloaded to a thread to keep
the aiogram event loop responsive.

We over-fetch by one row (PAGE_SIZE + 1) to cheaply detect whether a *next* page
exists without a second COUNT query.
"""

from __future__ import annotations

import asyncio

from .. import db
from ..models import SearchResult
from . import ranking

PAGE_SIZE = 5


async def search_page(
    query: str,
    page: int,
    fmt: str | None = None,
    language: str | None = None,
) -> tuple[list[SearchResult], bool]:
    """Return (results_for_page, has_next_page) for a 0-indexed page number.

    Results are filtered by ``fmt`` / ``language`` (None = no filter) and the
    current page is re-ordered by fuzzy relevance for display.
    """
    offset = page * PAGE_SIZE
    rows = await asyncio.to_thread(
        db.search_books, query, PAGE_SIZE + 1, offset, fmt, language
    )
    has_next = len(rows) > PAGE_SIZE
    page_rows = ranking.rerank(query, rows[:PAGE_SIZE])
    return page_rows, has_next


async def browse_page(
    slug: str,
    page: int,
    fmt: str | None = None,
    language: str | None = None,
) -> tuple[list[SearchResult], bool]:
    """Return (books_for_page, has_next_page) for a category (0-indexed page).

    Like :func:`search_page` but lists a category instead of a text query; rows
    are already newest-first from the DB, so no relevance re-ranking is applied.
    """
    offset = page * PAGE_SIZE
    rows = await asyncio.to_thread(
        db.browse_books, slug, PAGE_SIZE + 1, offset, fmt, language
    )
    has_next = len(rows) > PAGE_SIZE
    return rows[:PAGE_SIZE], has_next
