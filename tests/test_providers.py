"""Unit tests for providers + card rendering (no network)."""

from __future__ import annotations

from bookbot.bot import cards
from bookbot.providers import metadata, pdf_web
from bookbot.providers.youtube_audio import AudioCandidate


# ── PDF web candidate search ──────────────────────────────────────────────────
def test_search_candidates_ranks_dedupes_and_cleans(monkeypatch):
    monkeypatch.setattr(pdf_web, "_raw_search", lambda q, n: [
        {"title": "[PDF] Random Notes", "href": "https://other.com/x.pdf"},
        {"title": "[PDF] Atomic Habits.pdf", "href": "https://archive.org/a.pdf"},
        {"title": "Atomic Habits full", "href": "https://archive.org/dupe.pdf"},  # same domain
    ])
    cands = pdf_web.search_candidates("Atomic Habits", "en", limit=5)
    # Best title match first; "[PDF]" prefix and ".pdf" suffix stripped.
    assert cands[0].title == "Atomic Habits"
    assert cands[0].site == "archive.org"
    # archive.org appears once (deduped by domain).
    assert sum(c.site == "archive.org" for c in cands) == 1


def test_search_candidates_empty(monkeypatch):
    monkeypatch.setattr(pdf_web, "_raw_search", lambda q, n: [])
    assert pdf_web.search_candidates("Nothing", "uz") == []


def test_search_candidates_filters_presentations(monkeypatch):
    monkeypatch.setattr(pdf_web, "_raw_search", lambda q, n: [
        {"title": "Ityurak taqdimot (prezentatsiya)", "href": "https://slides.uz/p.pdf"},
        {"title": "Ityurak insho", "href": "https://essays.uz/i.pdf", "body": "insho"},
        {"title": "Ityurak", "href": "https://mykitob.uz/badiiy/ityurak/"},
    ])
    cands = pdf_web.search_candidates("Ityurak", "uz", limit=5)
    sites = [c.site for c in cands]
    assert "mykitob.uz" in sites
    assert "slides.uz" not in sites and "essays.uz" not in sites


# ── Page metadata scraping ────────────────────────────────────────────────────
def test_scrape_meta_extracts_og_and_genre():
    html = (
        '<meta property="og:image" content="/cover.jpg">'
        '<meta property="og:description" content="Tarixiy roman &amp; doston.">'
        "Muallif: Abdulla Qodiriy"
    )
    m = metadata.scrape_meta("https://site.uz/tarixiy/otkan-kunlar", html)
    assert m is not None
    assert m.cover_url == "https://site.uz/cover.jpg"  # relative resolved
    assert m.description == "Tarixiy roman & doston."  # entity unescaped
    assert m.genre == "Tarixiy"
    assert m.author_str == "Abdulla Qodiriy"


def test_scrape_meta_ignores_jsonld_author():
    html = '<meta property="og:image" content="http://x/c.jpg">' \
           '"author":{"name":"admin","@id":"https://x/#schema"}'
    m = metadata.scrape_meta("https://x.uz/badiiy/b", html)
    assert m is not None and m.author_str is None  # no garbage author


def test_scrape_meta_none_when_empty():
    assert metadata.scrape_meta("https://x.uz/p", "<html>nothing</html>") is None


# ── Metadata (OpenLibrary) pure helpers ───────────────────────────────────────
def test_pick_language_priority():
    assert metadata._pick_language(["por", "tur", "eng"]) == "en"  # eng beats tur
    assert metadata._pick_language(["uzb", "eng"]) == "uz"          # uz wins
    assert metadata._pick_language(["fra"]) is None


def test_best_doc_picks_closest_title():
    docs = [{"title": "Something Else"}, {"title": "The Alchemist"}]
    assert metadata._best_doc("alchemist", docs)["title"] == "The Alchemist"


# ── Audio candidate formatting ────────────────────────────────────────────────
def test_audio_duration_str():
    assert AudioCandidate("v", "t", 0).duration_str == "?"
    assert AudioCandidate("v", "t", 65).duration_str == "1:05"
    assert AudioCandidate("v", "t", 3661).duration_str == "1:01:01"


def test_audio_candidate_url():
    assert AudioCandidate("abc123", "t", 100).url == "https://www.youtube.com/watch?v=abc123"


# ── Card rendering ────────────────────────────────────────────────────────────
def test_build_card_includes_fields():
    card = cards.build_card(
        title="O'tkan kunlar", fmt="mp3", author="Abdulla Qodiriy",
        language="uz", duration="4:42:59", description="Tarixiy roman.",
    )
    assert "🎧" in card.text and "O'tkan kunlar" in card.text
    assert "Abdulla Qodiriy" in card.text
    assert "O'zbekcha" in card.text
    assert "4:42:59" in card.text
    assert "Tarixiy roman." in card.text
    assert card.cover_url is None


def test_build_card_shows_genre():
    card = cards.build_card(title="X", fmt="pdf", genre="Roman")
    assert "Janr: Roman" in card.text


def test_build_card_clips_long_description():
    long = "word " * 1000
    card = cards.build_card(title="X", fmt="pdf", description=long, cover_url="http://c/img.jpg")
    assert card.cover_url == "http://c/img.jpg"
    assert len(card.text) <= cards._CAPTION_LIMIT + 5
    assert card.text.rstrip().endswith("…</i>")
