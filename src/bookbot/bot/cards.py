"""Render a rich book "detail card" (cover + metadata + description).

A card is shown after the user picks a search result / variant, before the file
is sent — for both PDF and audio. Fields come from the catalog and/or the
metadata providers; every field is optional and the card hides what it lacks.

Layout (Phase 9b — clean, ordered, one idea per line):

    [cover]
    📖 <b>Til ofatlari</b>
    ✍️ Abu Homid G'azzoliy
    🏷 Diniy  ·  🌐 O'zbekcha  ·  📄 PDF
    ⏱ 4:42:59   ·   📊 6.9 MB
    🔗 mykitob.uz

    <i>Toza, to'liq AI tavsif — 2-3 jumla.</i>
"""

from __future__ import annotations

from dataclasses import dataclass

_FMT = {"pdf": "📄 PDF", "mp3": "🎧 Audio"}
_LANG = {"uz": "O'zbekcha", "en": "Inglizcha", "ru": "Ruscha", "tr": "Turkcha"}
_CAPTION_LIMIT = 1000  # Telegram photo-caption cap is 1024; leave headroom.


@dataclass(slots=True)
class Card:
    text: str
    cover_url: str | None


def _clip(desc: str, budget: int) -> str:
    desc = " ".join(desc.split())
    if len(desc) <= budget:
        return desc
    return desc[: budget - 1].rsplit(" ", 1)[0] + "…"


def _fmt_size(size_mb: float | None) -> str | None:
    if not size_mb or size_mb <= 0:
        return None
    return f"{size_mb:.1f} MB" if size_mb < 100 else f"{size_mb:.0f} MB"


def build_card(
    *,
    title: str,
    fmt: str,
    author: str | None = None,
    language: str | None = None,
    description: str | None = None,
    cover_url: str | None = None,
    duration: str | None = None,
    site: str | None = None,
    genre: str | None = None,
    size_mb: float | None = None,
    for_caption: bool = False,
) -> Card:
    """Assemble a card caption + optional cover image url.

    ``for_caption=True`` clips the description to fit a Telegram media caption
    (used when the text is attached directly to the delivered file)."""
    lines = [f"📖 <b>{title.strip()}</b>"]
    if author:
        lines.append(f"✍️ {author}")
    # Genre and language each on their own line (kept separate from the file info).
    if genre:
        lines.append(f"🏷 {genre}")
    if language:
        lines.append(f"🌐 {_LANG.get(language, language)}")

    # File facts together on one line: format · duration (audio) · size.
    facts = [_FMT.get(fmt, fmt)]
    if duration:
        facts.append(f"⏱ {duration}")
    size = _fmt_size(size_mb)
    if size:
        facts.append(f"📊 {size}")
    lines.append("  ·  ".join(facts))

    if site:
        lines.append(f"🔗 {site}")

    head = "\n".join(lines)
    if description:
        capped = cover_url or for_caption
        room = _CAPTION_LIMIT - len(head) - 4 if capped else 3500 - len(head) - 4
        head += "\n\n" + f"<i>{_clip(description, max(room, 0))}</i>"
    return Card(text=head, cover_url=cover_url)
