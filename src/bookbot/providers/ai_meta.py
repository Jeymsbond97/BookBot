"""Generate an ACCURATE Uzbek book description + genre with OpenAI (GPT).

Pure title→GPT generation hallucinates (it invents plausible-sounding plots). To
avoid that we ground the model in real context first (retrieval-augmented):

  1. the source channel's own caption (often carries author + a "Tasnif:" blurb), and
  2. web-search snippets about the actual book (DuckDuckGo, keyless).

GPT then summarises that real material into a 5-6 sentence Uzbek review — and is
told NOT to invent facts when the context is thin. Results are cached per-process.
Falls back to None on any error / when no API key is set — the card just shows less.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache

from ddgs import DDGS
from openai import OpenAI

from ..config import get_settings

log = logging.getLogger(__name__)

_SYSTEM = (
    "Sen kitoblar bo'yicha aniq ma'lumot beradigan, sof o'zbek tilida yozadigan adabiy "
    "yordamchisan. Senga kitob nomi, (ba'zan) muallifi va MANBA ma'lumotlari (internet "
    "qidiruvi va kanal tavsifi) beriladi. Sen FAQAT JSON qaytarasan: "
    '{"description": "...", "genre": "...", "author": "..."}. '
    "MUHIM QOIDA: tavsifni FAQAT berilgan manba va aynan shu KITOB haqidagi haqiqiy "
    "bilimingga asoslanib yoz. O'zingdan voqea, qahramon, syujet TO'QIMA. "
    "description — agar manbada yoki bilimingda yetarli ma'lumot bo'lsa, kitob haqida 5-6 ta "
    "to'liq jumlali, taqrizga o'xshash matn: kitob nima haqida, asosiy mavzu va g'oyalari, "
    "kimga/nima uchun foydali, nega o'qishga arziydi. Agar ma'lumot kam bo'lsa, qisqaroq va "
    "ehtiyotkor yoz — noaniq da'volar (aniq sana, tiraj, sahifa, to'qima syujet) yozma. "
    "genre — qisqa janr (Roman, Tarixiy roman, She'riyat, Badiiy, Detektiv, Ilmiy, Diniy, "
    "Psixologiya, Shaxsiy rivojlanish, Biznes, Bolalar kitobi). "
    "author — muallifning to'liq ismi (manbadan yoki ishonchli bilimingdan); bilmasang null. "
    "Agar bu umuman kitob bo'lmasa, uchala qiymatni null qil."
)


@dataclass(slots=True)
class AiMeta:
    description: str | None
    genre: str | None
    author: str | None = None


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    return OpenAI(api_key=get_settings().openai_api_key)


def _web_context(title: str, author: str | None) -> str:
    """Real snippets about the book from the web, to ground the description."""
    who = f" {author}" if author else ""
    out: list[str] = []
    for q in (f"{title}{who} kitob mazmuni haqida", f"{title}{who} roman tahlili"):
        try:
            for r in DDGS().text(q, max_results=4):
                body = (r.get("body") or "").strip()
                if body:
                    out.append(body)
        except Exception:
            log.info("web context search failed for %r", q, exc_info=True)
        if len(out) >= 5:
            break
    # De-dupe and cap the context size.
    seen, ctx = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            ctx.append(s)
    return "\n---\n".join(ctx)[:3000]


@lru_cache(maxsize=512)
def lookup(title: str, author: str | None = None, context: str = "") -> AiMeta | None:
    """Return an accurate, source-grounded description + genre + author, or None.

    ``context`` is extra real material (e.g. the source channel's caption). Web
    snippets are fetched and combined with it before the model writes anything.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    web = _web_context(title, author)
    source = "\n\n".join(p for p in (context.strip(), web) if p) or "(manba topilmadi)"
    who = f" (muallif: {author})" if author else ""
    user = (
        f"Kitob: «{title}»{who}.\n\n"
        f"MANBA MA'LUMOTLARI (shularga asoslan, to'qima yozma):\n{source}"
    )
    try:
        resp = _client().chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            max_tokens=600,
            timeout=45,
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
