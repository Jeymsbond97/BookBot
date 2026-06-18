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
    "Sen kitoblar bo'yicha bilimdon, sof o'zbek tilida yozadigan adabiy yordamchisan. "
    "Foydalanuvchi kitob nomini (va ba'zan muallifini) beradi. Sen FAQAT JSON qaytarasan: "
    '{"description": "...", "genre": "...", "author": "..."}. '
    "description — kitob haqida 5-6 ta to'liq jumladan iborat, taqrizga o'xshash, qiziqarli "
    "matn yoz: kitob nima haqida, asosiy mavzu va g'oyalari, kimga va nima uchun foydali, "
    "nega o'qishga arziydi. Sof, ravon o'zbek tilida. "
    "genre — qisqa janr (masalan: Roman, Tarixiy roman, She'riyat, Badiiy, Detektiv, Ilmiy, "
    "Diniy, Psixologiya, Shaxsiy rivojlanish, Biznes, Bolalar kitobi). "
    "author — muallifning to'liq ismi, agar ishonchli bilsang; bilmasang null. "
    "Agar bu umuman kitob bo'lmasa (taqdimot, hujjat, referat), uchala qiymatni null qil. "
    "Aks holda, kitob nomidan mavzusini anglab, foydali va aniq tavsif ber — to'qima ma'lumot "
    "(aniq sana, tiraj, sahifa soni) yozma, umumiy mazmunga e'tibor qarat."
)


@dataclass(slots=True)
class AiMeta:
    description: str | None
    genre: str | None
    author: str | None = None


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
            max_tokens=600,
            timeout=40,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        log.warning("OpenAI metadata lookup failed for %r", title, exc_info=True)
        return None

    desc = (data.get("description") or "").strip() or None
    genre = (data.get("genre") or "").strip() or None
    ai_author = (data.get("author") or "").strip() or None
    if not (desc or genre):
        return None
    return AiMeta(description=desc, genre=genre, author=ai_author)
