"""Generate a short Uzbek book description + genre with OpenAI (GPT).

Web scraping and OpenLibrary rarely have descriptions for Uzbek books, so this is
the reliable source: given a title (and author), GPT returns a 1–2 sentence Uzbek
description and a genre. Results are cached per-process so repeated views of the
same book don't re-spend tokens.

Falls back to None on any error or when no API key is configured — the card then
simply shows less, never breaks.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache

from openai import OpenAI

from ..config import get_settings

log = logging.getLogger(__name__)

_SYSTEM = (
    "Sen kitoblar bo'yicha bilimdon yordamchisan. Foydalanuvchi kitob nomini "
    "(va ba'zan muallifini) beradi. Sen FAQAT JSON qaytarasan: "
    '{"description": "...", "genre": "..."}. '
    "description — kitob nima haqida ekanini 1-2 jumlada, sof o'zbek tilida, jozibali "
    "tarzda yoz. genre — qisqa janr (masalan: Roman, Tarixiy roman, She'riyat, Badiiy, "
    "Detektiv, Ilmiy, Diniy, Psixologiya, Biznes, Bolalar kitobi). "
    "Agar kitobni aniq bilmasang, description va genre qiymatini null qil — to'qib chiqarma."
)


@dataclass(slots=True)
class AiMeta:
    description: str | None
    genre: str | None


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    return OpenAI(api_key=get_settings().openai_api_key)


@lru_cache(maxsize=512)
def lookup(title: str, author: str | None = None) -> AiMeta | None:
    """Return AI-generated description + genre for a book, or None."""
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    who = f" (muallif: {author})" if author else ""
    try:
        resp = _client().chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Kitob: «{title}»{who}."},
            ],
            response_format={"type": "json_object"},
            max_tokens=300,
            timeout=30,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        log.warning("OpenAI metadata lookup failed for %r", title, exc_info=True)
        return None

    desc = (data.get("description") or "").strip() or None
    genre = (data.get("genre") or "").strip() or None
    if not (desc or genre):
        return None
    return AiMeta(description=desc, genre=genre)
