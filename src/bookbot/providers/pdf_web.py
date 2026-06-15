"""PDF web provider — find real PDFs on the open web via DuckDuckGo (keyless).

Two stages, so the user picks the *right* file instead of us guessing:

  1. ``search_candidates(title)`` — run ``"<title>" filetype:pdf`` on DuckDuckGo,
     rank hits by title similarity, dedupe by domain, and return a list of
     candidates (title + url + site) WITHOUT downloading anything.
  2. ``download_validate(url)`` — once the user taps a candidate, download it
     (size-capped) and confirm it's a real PDF (``%PDF`` magic + content-type,
     and not a trivially tiny file like a slide deck).

This fixes "it grabbed a random presentation": the user sees several variants
with their source sites and chooses, and junk files are filtered out.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from ddgs import DDGS
from rapidfuzz import fuzz

log = logging.getLogger(__name__)

name = "pdf_web"
fmt = "pdf"

_MAX_CANDIDATES = 8
_PDF_MAGIC = b"%PDF"
_MIN_PDF_BYTES = 30_000  # below this it's almost certainly not a book (slide/sample)
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BookBot/1.0)"}


@dataclass(slots=True)
class PdfCandidate:
    title: str
    url: str
    site: str


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def _raw_search(query: str, max_results: int) -> list[dict]:
    try:
        return DDGS().text(query, max_results=max_results)
    except Exception:
        log.warning("ddgs search failed for %r", query, exc_info=True)
        return []


def search_candidates(title: str, language: str = "uz", limit: int = 6) -> list[PdfCandidate]:
    """Return ranked, de-duplicated PDF candidates for ``title`` (no download)."""
    results = _raw_search(f'"{title}" filetype:pdf', _MAX_CANDIDATES)
    if not results:
        results = _raw_search(f"{title} filetype:pdf", _MAX_CANDIDATES)

    scored: list[tuple[float, PdfCandidate]] = []
    seen_domains: set[str] = set()
    for item in results:
        url = item.get("href") or item.get("url")
        if not url:
            continue
        domain = _domain(url)
        if domain in seen_domains:  # one result per site keeps the list diverse
            continue
        seen_domains.add(domain)
        cand_title = (item.get("title") or title).strip()
        if cand_title.lower().startswith("[pdf]"):
            cand_title = cand_title[5:].strip()
        cand_title = cand_title.removesuffix(".pdf").strip()
        score = fuzz.token_set_ratio(title.lower(), cand_title.lower())
        scored.append((score, PdfCandidate(title=cand_title, url=url, site=domain)))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:limit]]


def download_validate(url: str, max_bytes: int) -> bytes | None:
    """Download up to ``max_bytes``; return bytes only if it's a real PDF."""
    try:
        with httpx.Client(follow_redirects=True, timeout=30.0, headers=_HEADERS) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return None
                ctype = resp.headers.get("content-type", "").lower()
                clen = resp.headers.get("content-length")
                if clen and int(clen) > max_bytes:
                    log.info("Skip %s: content-length %s > cap", url, clen)
                    return None

                chunks = bytearray()
                for chunk in resp.iter_bytes():
                    chunks += chunk
                    if len(chunks) > max_bytes:
                        log.info("Skip %s: exceeded size cap mid-download", url)
                        return None
    except Exception:
        log.info("Download failed for %s", url, exc_info=True)
        return None

    data = bytes(chunks)
    looks_pdf = data[:4] == _PDF_MAGIC or "pdf" in ctype
    if not looks_pdf or _PDF_MAGIC not in data[:1024]:
        return None
    if len(data) < _MIN_PDF_BYTES:  # too small to be a real book
        log.info("Skip %s: only %d bytes (likely not a book)", url, len(data))
        return None
    return data
