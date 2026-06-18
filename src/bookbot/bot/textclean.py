"""Cleaning helpers for card text — fixes the Phase 9a bugs.

Scraped book pages (pdfbox.uz, …) give us messy data:
  - titles carry "- yuklab olish!", " pdf", "skachat" suffixes and arrive lowercase
    (because we often fall back to the user's raw query as the title);
  - ``og:description`` is frequently SEO junk the site itself truncated mid-word
    ("«…» - yuklab olish! O'zbek tilida kitoblar bo");
  - covers are placeholder images ("default-images/document-books-image.webp").

These pure helpers detect/clean that so the card can prefer the clean AI
description, a Title-Cased title, and a real cover (or none).
"""

from __future__ import annotations

import re

# ── Title ─────────────────────────────────────────────────────────────────────

# Noise that trails a scraped book title; everything from the match onward is cut.
_TITLE_TAIL = re.compile(
    r"\s*[-–—|:]?\s*(yuklab olish|yuklash|skachat|tekin|onlayn|online"
    r"|to['‘’`]liq|audiokitob|audio kitob|mp3|epub|fb2|djvu)\b.*$",
    re.IGNORECASE,
)
# Bracketed prefixes like "[PDF]" / "(PDF)" and a bare trailing ".pdf"/" pdf".
_BRACKET_PREFIX = re.compile(r"^\s*[\[(]\s*pdf\s*[\])]\s*", re.IGNORECASE)
_PDF_SUFFIX = re.compile(r"\s*\.?\bpdf\b\s*$", re.IGNORECASE)


def _title_word(w: str) -> str:
    """Title-case one word, Uzbek-aware: keep the O'/G' digraph apostrophe and
    don't choke on leading punctuation. ``"o'tkan" -> "O'tkan"``."""
    if not w:
        return w
    # Find the first alphabetic char so "«kitob" → "«Kitob".
    for i, ch in enumerate(w):
        if ch.isalpha():
            return w[:i] + ch.upper() + w[i + 1 :].lower()
    return w


def clean_title(raw: str | None) -> str:
    """Strip download-site noise from a title and Title-Case it."""
    if not raw:
        return ""
    t = raw.strip()
    t = _BRACKET_PREFIX.sub("", t)
    t = _TITLE_TAIL.sub("", t)
    t = _PDF_SUFFIX.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" -–—|:·.\t")
    if not t:
        return ""
    return " ".join(_title_word(w) for w in t.split(" "))


# ── Description ───────────────────────────────────────────────────────────────

# Phrases that mark a scraped description as SEO junk rather than real content.
_JUNK_MARKERS = (
    "yuklab olish",
    "yuklab oling",
    "kitoblar bo",       # "...O'zbek tilida kitoblar bo" (truncated)
    "skachat",
    "tekin yuklab",
    "onlayn o'qish",
    "pdf yuklab",
    "saytida",
)


def is_junk_description(text: str | None) -> bool:
    """True if a scraped description is SEO/boilerplate junk (so we fall back to
    the clean AI description instead)."""
    if not text:
        return True
    low = " ".join(text.split()).lower()
    if any(m in low for m in _JUNK_MARKERS):
        return True
    # Too short to be a real description, or truncated mid-word with no end mark.
    if len(low) < 25:
        return True
    if not low.rstrip().endswith((".", "!", "?", "…")) and low.endswith(
        (" bo", " va", " uchun", " bilan")
    ):
        return True
    return False


def clean_description(text: str | None) -> str | None:
    """Return the description if it's real, else None (junk → drop it)."""
    if is_junk_description(text):
        return None
    return " ".join(text.split())


# ── Cover ─────────────────────────────────────────────────────────────────────

_PLACEHOLDER_COVER = (
    "default-images",
    "no-image",
    "no_image",
    "noimage",
    "placeholder",
    "default.",
    "default-book",
    "document-books-image",
)


def is_placeholder_cover(url: str | None) -> bool:
    """True if a cover URL is a generic site placeholder, not a real cover."""
    if not url:
        return True
    low = url.lower()
    return any(p in low for p in _PLACEHOLDER_COVER)


def clean_cover(url: str | None) -> str | None:
    """Return the cover URL if it's a real image, else None."""
    return None if is_placeholder_cover(url) else url
