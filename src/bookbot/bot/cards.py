"""Render a rich book "detail card" (cover + metadata + description).

A card is shown after the user picks a search result / variant, before the file
is sent — for both PDF and audio. Fields come from the catalog and/or the
OpenLibrary metadata provider; every field is optional and the card adapts.
"""

from __future__ import annotations

from dataclasses import dataclass

_FMT = {"pdf": "📕 PDF", "mp3": "🎧 Audio"}
_LANG = {"uz": "🇺🇿 O'zbekcha", "en": "🇬🇧 Inglizcha", "ru": "🇷🇺 Ruscha", "tr": "🇹🇷 Turkcha"}
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
) -> Card:
    """Assemble a card caption + optional cover image url."""
    emoji = "📕" if fmt == "pdf" else "🎧"
    lines = [f"{emoji} <b>{title}</b>"]
    if author:
        lines.append(f"✍️ {author}")
    lines.append(f"🏷 {_FMT.get(fmt, fmt)}")
    if genre:
        lines.append(f"📚 Janr: {genre}")
    if language:
        lines.append(f"🌐 {_LANG.get(language, language)}")
    if duration:
        lines.append(f"⏱ {duration}")
    if site:
        lines.append(f"🔗 {site}")

    head = "\n".join(lines)
    if description:
        room = _CAPTION_LIMIT - len(head) - 4 if cover_url else 3500 - len(head) - 4
        head += "\n\n" + f"<i>{_clip(description, max(room, 0))}</i>"
    return Card(text=head, cover_url=cover_url)
