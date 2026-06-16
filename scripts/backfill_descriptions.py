"""Backfill Uzbek descriptions for catalog books that don't have one.

For every book with an empty `description`, ask OpenAI for a 1-2 sentence Uzbek
description (+ genre) and save the description. Idempotent — skips books that
already have one. Cheap (gpt-4o-mini ≈ $0.00003/book).

Usage:
    python scripts/backfill_descriptions.py            # all books missing a description
    python scripts/backfill_descriptions.py --limit 20 # cap how many to process
"""

from __future__ import annotations

import sys

from bookbot import db
from bookbot.providers import ai_meta


def main() -> None:
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    client = db.get_client()
    res = client.table("books").select("id, title, author, description").execute()
    books = [b for b in (res.data or []) if not (b.get("description") or "").strip()]
    if limit:
        books = books[:limit]

    print(f"{len(books)} ta kitobda tavsif yo'q — to'ldirilmoqda…\n")
    done = 0
    for b in books:
        meta = ai_meta.lookup(b["title"], b.get("author"))
        if meta and meta.description:
            db.update_book_meta(b["id"], description=meta.description)
            done += 1
            print(f"✓ {b['title'][:40]:40s} | {meta.genre or '-'}")
        else:
            print(f"✗ {b['title'][:40]:40s} | (AI tavsif bera olmadi)")
    print(f"\nTugadi: {done}/{len(books)} ta kitobga tavsif yozildi.")


if __name__ == "__main__":
    main()
