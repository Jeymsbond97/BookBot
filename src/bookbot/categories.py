"""Best-effort mapping from a free-text (AI/scraped) genre to a catalog category.

Auto-fetched books (web PDF / YouTube audio) have no category tag, so the
category-browse listings would be empty. We map their loose Uzbek ``genre``
string onto one of the seeded category slugs (see ``0001_init.sql``) by keyword,
so browsing actually surfaces them. Admin uploads (Phase 7) set the category
explicitly and don't rely on this.
"""

from __future__ import annotations

# keyword (lower-cased, matched as a substring of the genre) → category slug.
_KEYWORDS: list[tuple[str, str]] = [
    ("psixolog", "psychology"),
    ("shaxsiy", "self-dev"),
    ("rivojlan", "self-dev"),
    ("motivatsiya", "self-dev"),
    ("biznes", "business"),
    ("iqtisod", "business"),
    ("moliya", "business"),
    ("tarix", "history"),
    ("din", "religion"),
    ("islom", "religion"),
    ("ma'naviy", "religion"),
    ("ilm", "science"),
    ("fan", "science"),
    ("texnolog", "science"),
    ("roman", "fiction"),
    ("badiiy", "fiction"),
    ("she'r", "fiction"),
    ("she", "fiction"),
    ("hikoya", "fiction"),
    ("detektiv", "fiction"),
    ("qissa", "fiction"),
    ("bolalar", "fiction"),
]


def category_for_genre(genre: str | None) -> str | None:
    """Return a category slug for a loose genre string, or None if no match."""
    if not genre:
        return None
    g = genre.strip().lower()
    for keyword, slug in _KEYWORDS:
        if keyword in g:
            return slug
    return None
