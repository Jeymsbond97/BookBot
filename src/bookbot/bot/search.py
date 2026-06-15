"""Search logic for the bot — wraps the Postgres ``search_books`` RPC.

The Supabase client is synchronous, so each call is offloaded to a thread to keep
the aiogram event loop responsive.

We over-fetch by one row (PAGE_SIZE + 1) to cheaply detect whether a *next* page
exists without a second COUNT query.
"""

from __future__ import annotations

import asyncio

from ..models import SearchResult
from .. import db

PAGE_SIZE = 5


async def search_page(query: str, page: int) -> tuple[list[SearchResult], bool]:
    """Return (results_for_page, has_next_page) for a 0-indexed page number."""
    offset = page * PAGE_SIZE
    rows = await asyncio.to_thread(
        db.search_books, query, PAGE_SIZE + 1, offset
    )
    has_next = len(rows) > PAGE_SIZE
    return rows[:PAGE_SIZE], has_next
