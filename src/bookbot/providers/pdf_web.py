"""PDF web provider — find FREE book PDFs on the open web (keyless).

The naive ``"<title>" filetype:pdf`` approach failed for Uzbek books: free sites
(mykitob.uz, pdfbox.uz, mutolaa.com, …) host the PDF *behind a download page/button*
(e.g. a WordPress download-monitor link ``/download/714/``), not as a directly
indexed ``.pdf`` URL — so search returned paid stores (uzum, asaxiy) and junk.

New strategy:
  1. ``search_candidates(title)`` — run a few discovery queries ("<title> pdf
     yuklab olish", …), **drop paid-store / junk domains**, **boost known free book
     sites**, rank by title similarity, dedupe by domain → list of candidate PAGES.
  2. ``download_validate(url)`` — if the url is already a PDF, download it; otherwise
     fetch the page HTML and **extract the real PDF link** (direct ``.pdf`` or a
     download endpoint), follow it, and confirm it's a real PDF.
"""

from __future__ import annotations

import io
import logging
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from ddgs import DDGS
from rapidfuzz import fuzz

log = logging.getLogger(__name__)

name = "pdf_web"
fmt = "pdf"

_PDF_MAGIC = b"%PDF"
_ZIP_MAGIC = b"PK\x03\x04"
_MIN_PDF_BYTES = 30_000  # below this it's almost certainly not a book
# Many free book sites reject non-browser requests (403) or require a Referer on
# their download endpoints, so present as a real browser.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
    "Accept-Language": "uz,ru;q=0.9,en;q=0.8",
}


def _with_referer(url: str) -> dict:
    h = dict(_HEADERS)
    p = urlparse(url)
    if p.scheme and p.netloc:
        h["Referer"] = f"{p.scheme}://{p.netloc}/"
    return h

# Reliable free book sites — we run a site-restricted query for each so the actual
# *book page* surfaces (general queries tend to return their category/home pages),
# and we know how to extract the PDF from them.
_RELIABLE_SITES = (
    "avloniy.uz",   # Avloniy digital library — real downloadable PDFs (best source)
    "pdfbox.uz",    # serves the PDF inside a ZIP (handled in _pdf_from_zip)
    "mykitob.uz",
    "ziyouz.com",
    "n.ziyouz.com",
    "qr.natlib.uz",
    "unilibrary.uz",
)


def _queries(title: str) -> list[str]:
    site_qs = [f"{title} site:{s}" for s in _RELIABLE_SITES]
    # "kitob pdf" keeps results book-shaped (a bare filetype:pdf dragged in random
    # slide decks / essays / unrelated PDFs).
    general = [f"{title} kitob pdf yuklab olish", f"{title} kitobi pdf"]
    return site_qs + general


# Not books: slide decks, essays, lesson plans, abstracts, test banks…
_NOT_A_BOOK = (
    "taqdimot", "prezentatsiya", "prezentatsiyalar", "slayd", "slide", ".ppt",
    "powerpoint", "insho", "referat", "konspekt", "dars ishlanma", "ishlanma",
    "mustaqil ish", "kurs ishi", "kurs ish", "bitiruv", "mavzusida", "test savol",
)

# Paid stores, news, PDF-tool sites, aggregators — never a free book download.
_BLOCKED = (
    "uzum.uz", "asaxiy.uz", "birbir.uz", "olx.uz", "market", "shop",
    "wikipedia.org", "kun.uz", "uzpedia.uz", "daryo.uz", "gazeta.uz",
    "scribd.com", "academia.edu", "researchgate", "slideshare",
    "11zon.com", "pandatoolz", "ilovepdf", "smallpdf", "pdfdrive.to",
    "uslegalforms", "tgstat.com", "t.me", "youtube.com", "facebook.com",
    "instagram.com", "play.google", "books.google", "amazon.",
    "apkpure", "olcha.uz", "prezi.com", "cyberleninka", "abituriyentlar.uz",
)
# Known free Uzbek e-book sites — ranked first when present.
_FREE_BOOST = (
    "avloniy.uz", "mykitob.uz", "pdfbox.uz",
    "ziyouz.com", "n.ziyouz.com", "ziyonet.uz", "n.ziyonet.uz", "qr.natlib.uz",
    "natlib.uz", "unilibrary.uz", "kitoblar", "ekitob", "e-kitob",
    "asaxiykutubxona", "kutubxona", "oasap.uz", "uzbekkino",
)


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


def _raw_search(query: str, max_results: int, retries: int = 2) -> list[dict]:
    """Run one DuckDuckGo query. DDGS rate-limits bursts of concurrent queries
    (raising), which silently dropped good sources (avloniy/pdfbox) from the
    results. Retry on *exception* (rate-limit) with backoff; a genuinely empty
    result returns [] without retrying."""
    for attempt in range(retries + 1):
        try:
            return DDGS().text(query, max_results=max_results)
        except Exception:
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
                continue
            log.warning("ddgs search failed for %r", query, exc_info=True)
    return []


def _clean_title(raw: str, fallback: str) -> str:
    t = (raw or fallback).strip()
    if t.lower().startswith("[pdf]"):
        t = t[5:].strip()
    return t.removesuffix(".pdf").strip()


def search_candidates(title: str, language: str = "uz", limit: int = 6) -> list[PdfCandidate]:
    """Return ranked, domain-deduped candidate pages likely to host a free PDF."""
    queries = _queries(title)
    # Run the queries concurrently so adding more reliable sites doesn't slow the
    # search down (capped concurrency to stay friendly with DuckDuckGo).
    raw: list[dict] = []
    # Cap concurrency low: DuckDuckGo rate-limits bursts, and a throttled query
    # returns nothing — which previously dropped the best free-PDF sources.
    with ThreadPoolExecutor(max_workers=3) as ex:
        for res in ex.map(lambda q: _raw_search(q, 6), queries):
            raw += res

    best_by_domain: dict[str, tuple[float, PdfCandidate]] = {}
    for item in raw:
        url = item.get("href") or item.get("url")
        if not url:
            continue
        domain = _domain(url)
        if not domain or any(b in domain for b in _BLOCKED):
            continue
        haystack = f"{url} {item.get('title', '')} {item.get('body', '')}".lower()
        if any(bad in haystack for bad in _NOT_A_BOOK):  # slide deck / essay / etc.
            continue
        cand_title = _clean_title(item.get("title"), title)
        score = fuzz.token_set_ratio(title.lower(), cand_title.lower())
        if any(f in domain for f in _FREE_BOOST):
            score += 40  # float known free book sites to the top
        prev = best_by_domain.get(domain)
        if prev is None or score > prev[0]:
            best_by_domain[domain] = (score, PdfCandidate(cand_title, url, domain))

    ranked = sorted(best_by_domain.values(), key=lambda x: x[0], reverse=True)
    return [c for _, c in ranked[:limit]]


# ── PDF extraction + download ─────────────────────────────────────────────────
_ASSET_RE = re.compile(r"\.(css|js|png|jpe?g|gif|svg|woff2?|ico)(\?|$)", re.I)
_PDF_HREF_RE = re.compile(r"""href=["']([^"']+\.pdf[^"']*)["']""", re.I)
_DL_HREF_RE = re.compile(
    r"""href=["']([^"']*(?:/download/\d+|download|yuklab|skachat)[^"']*)["']""", re.I
)


def _pdf_links_on_page(page_url: str, html: str, title: str | None = None) -> list[str]:
    """Extract likely PDF/download links from a page, most-specific first.

    When ``title`` is given and the page lists many books (e.g. a category page),
    links whose URL slug matches the searched title are tried first.
    """
    out: list[str] = []
    for href in _PDF_HREF_RE.findall(html):
        out.append(urljoin(page_url, href))
    for href in _DL_HREF_RE.findall(html):
        if _ASSET_RE.search(href) or "plugins" in href or "themes" in href:
            continue
        if "qanday-yuklab-olish" in href:  # "how to download" help page, not a file
            continue
        out.append(urljoin(page_url, href))
    # dedupe, preserve order
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)

    if title:  # float links whose slug matches the searched title (category pages)
        words = [w for w in re.split(r"\W+", title.lower()) if len(w) > 2]
        def slug_score(u: str) -> int:
            low = u.lower()
            return sum(1 for w in words if w in low)
        uniq.sort(key=slug_score, reverse=True)
    return uniq


def _try_download(url: str, max_bytes: int) -> bytes | None:
    """Download ``url`` if it streams a real PDF (magic + size), else None."""
    try:
        with httpx.Client(follow_redirects=True, timeout=30.0,
                          headers=_with_referer(url)) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return None
                ctype = resp.headers.get("content-type", "").lower()
                clen = resp.headers.get("content-length")
                if clen and int(clen) > max_bytes:
                    return None
                # Not a PDF response and not HTML we'd parse → skip early.
                chunks = bytearray()
                for chunk in resp.iter_bytes():
                    chunks += chunk
                    if len(chunks) > max_bytes:
                        return None
    except Exception:
        log.info("download failed for %s", url, exc_info=True)
        return None

    data = bytes(chunks)
    if data[:4] == _PDF_MAGIC and len(data) >= _MIN_PDF_BYTES:
        return data
    if "pdf" in ctype and _PDF_MAGIC in data[:1024] and len(data) >= _MIN_PDF_BYTES:
        return data
    # Many free Uzbek book sites (pdfbox.uz, …) serve the PDF inside a ZIP.
    if data[:4] == _ZIP_MAGIC:
        return _pdf_from_zip(data, max_bytes)
    return None


def _pdf_from_zip(data: bytes, max_bytes: int) -> bytes | None:
    """Return the largest valid PDF inside a downloaded ZIP, or None."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        return None
    members = sorted(
        (i for i in zf.infolist() if i.filename.lower().endswith(".pdf")),
        key=lambda i: i.file_size,
        reverse=True,
    )
    for info in members:
        if info.file_size > max_bytes or info.file_size < _MIN_PDF_BYTES:
            continue
        try:
            content = zf.read(info)
        except Exception:
            continue
        if content[:4] == _PDF_MAGIC:
            return content
    return None


def _fetch_html(url: str) -> str | None:
    try:
        r = httpx.get(url, follow_redirects=True, timeout=20.0, headers=_with_referer(url))
        if r.status_code == 200 and "html" in r.headers.get("content-type", "").lower():
            return r.text
    except Exception:
        log.info("html fetch failed for %s", url, exc_info=True)
    return None


def page_info(url: str, title: str | None = None) -> tuple[object | None, list[str]]:
    """Fetch a candidate page once → (scraped BookMeta, resolved PDF links).

    Used when showing the detail card so we get the page's own cover/description
    AND the download link in a single request (the confirm step reuses the links,
    so we don't fetch the page twice). A direct ``.pdf`` url yields itself.
    """
    from . import metadata  # local import avoids any import-order coupling

    if urlparse(url).path.lower().endswith(".pdf"):
        return None, [url]
    html = _fetch_html(url)
    if not html:
        return None, []
    meta = metadata.scrape_meta(url, html)
    links = _pdf_links_on_page(url, html, title)
    return meta, links


def download_validate(url: str, max_bytes: int, title: str | None = None) -> bytes | None:
    """Get a real PDF from ``url`` — directly, or by extracting it from the page."""
    # 1) Maybe the url is the PDF itself.
    direct = _try_download(url, max_bytes)
    if direct is not None:
        return direct

    # 2) Otherwise treat it as a page: extract PDF/download links and try them.
    html = _fetch_html(url)
    if not html:
        return None
    return download_links(_pdf_links_on_page(url, html, title), max_bytes)


def download_links(links: list[str], max_bytes: int) -> bytes | None:
    """Try each already-resolved link in order; return the first real PDF."""
    for link in links[:6]:
        data = _try_download(link, max_bytes)
        if data is not None:
            return data
    return None
