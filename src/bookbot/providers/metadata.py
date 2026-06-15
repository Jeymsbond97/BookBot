"""Book metadata + cover lookup via OpenLibrary (keyless, unthrottled).

Used to build a rich detail card (cover image + description + author + language)
before we deliver a file, for both PDF and audio. Best-effort: Uzbek titles often
lack a cover or description on OpenLibrary, so every field is optional and the
card degrades gracefully when something is missing.

(Google Books has richer descriptions but its anonymous API is heavily rate-
limited / 429s from datacenters, so OpenLibrary is the reliable default.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
from rapidfuzz import fuzz

log = logging.getLogger(__name__)

_SEARCH_URL = "https://openlibrary.org/search.json"
_COVER_URL = "https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
_HEADERS = {"User-Agent": "BookBot/1.0 (Telegram book bot)"}
_TIMEOUT = 15.0

# OpenLibrary 3-letter language codes → our 2-letter codes, in display priority
# (a title may list many editions' languages; prefer the ones we care about).
_LANG = {"uzb": "uz", "eng": "en", "rus": "ru", "tur": "tr"}
_LANG_PRIORITY = ["uzb", "eng", "rus", "tur"]


def _pick_language(codes: list[str]) -> str | None:
    for code in _LANG_PRIORITY:
        if code in codes:
            return _LANG[code]
    return None


@dataclass(slots=True)
class BookMeta:
    title: str
    authors: list[str] = field(default_factory=list)
    description: str | None = None
    language: str | None = None
    cover_url: str | None = None
    subjects: list[str] = field(default_factory=list)
    year: int | None = None

    @property
    def author_str(self) -> str | None:
        return ", ".join(self.authors) if self.authors else None


def _best_doc(query: str, docs: list[dict]) -> dict | None:
    """Pick the doc whose title best matches the query (fuzzy)."""
    best, best_score = None, -1.0
    for d in docs:
        title = d.get("title") or ""
        s = fuzz.token_set_ratio(query.lower(), title.lower())
        if s > best_score:
            best, best_score = d, s
    return best


def _fetch_description(work_key: str) -> str | None:
    """Second call: the work record holds the long description."""
    try:
        r = httpx.get(
            f"https://openlibrary.org{work_key}.json", headers=_HEADERS, timeout=_TIMEOUT
        )
        if r.status_code != 200:
            return None
        desc = r.json().get("description")
    except Exception:
        log.info("OpenLibrary work fetch failed for %s", work_key, exc_info=True)
        return None
    if isinstance(desc, dict):  # sometimes {"type": ..., "value": "..."}
        desc = desc.get("value")
    if isinstance(desc, str):
        return desc.split("\n----")[0].strip() or None  # drop OL citation footer
    return None


def lookup(title: str, author: str | None = None) -> BookMeta | None:
    """Look up metadata for ``title`` (optionally ``author``). None if nothing."""
    query = f"{title} {author}".strip() if author else title
    try:
        r = httpx.get(
            _SEARCH_URL,
            params={
                "q": query,
                "limit": 5,
                "fields": "title,author_name,first_publish_year,language,cover_i,key,subject",
            },
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        docs = r.json().get("docs") or []
    except Exception:
        log.info("OpenLibrary search failed for %r", query, exc_info=True)
        return None

    doc = _best_doc(title, docs)
    if not doc:
        return None

    language = _pick_language(doc.get("language") or [])
    cover_url = _COVER_URL.format(cover_id=doc["cover_i"]) if doc.get("cover_i") else None
    description = _fetch_description(doc["key"]) if doc.get("key") else None

    return BookMeta(
        title=doc.get("title") or title,
        authors=doc.get("author_name") or [],
        description=description,
        language=language,
        cover_url=cover_url,
        subjects=(doc.get("subject") or [])[:5],
        year=doc.get("first_publish_year"),
    )
