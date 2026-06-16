"""aiogram handlers.

Flow:
  /start → choose format (pdf|mp3)
  text query →
    1. DB search in the chosen format → numbered list (or single exact hit)
    2. nothing in that format but the other exists → cross-format offer/list
    3. nothing in the DB at all → search the internet for VARIANTS
         (pdf: DuckDuckGo;  mp3: YouTube) → user picks one
  pick a result/variant → detail card (cover + metadata + description)
  press 📥 Yuborish → download (if needed) + deliver + cache/save.

FSM context keys: fmt, query, page, cross_format, candidates, cand_kind.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message

from .. import db
from ..config import get_settings
from ..providers import ai_meta, metadata, pdf_web, youtube_audio
from . import cards, delivery, ranking, texts
from .keyboards import (
    CardCB,
    CategoryCB,
    FormatCB,
    MenuCB,
    OfferCB,
    PageCB,
    SendCB,
    candidates_keyboard,
    card_keyboard,
    categories_keyboard,
    format_keyboard,
    main_menu_keyboard,
    offer_keyboard,
    results_keyboard,
)
from .search import PAGE_SIZE, search_page
from .states import Flow

log = logging.getLogger(__name__)
router = Router()

_FORMAT_MSG = {"pdf": texts.FORMAT_CHOSEN_PDF, "mp3": texts.FORMAT_CHOSEN_AUDIO}


# ── Global error handler ──────────────────────────────────────────────────────
@router.error()
async def on_error(event: ErrorEvent) -> None:
    """Never leave the user staring at a 'searching…' message: on any unhandled
    exception, log it and reply with a friendly error instead of hanging."""
    log.exception("Unhandled handler error: %s", event.exception)
    upd = event.update
    target = None
    if upd.message:
        target = upd.message
    elif upd.callback_query and upd.callback_query.message:
        target = upd.callback_query.message
        try:
            await upd.callback_query.answer()
        except Exception:
            pass
    if target:
        try:
            await target.answer(texts.ERROR_GENERIC)
        except Exception:
            pass


# ── Commands ─────────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Flow.choosing_format)
    await message.answer(texts.WELCOME, reply_markup=format_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP)


# ── Format selection ─────────────────────────────────────────────────────────
@router.callback_query(FormatCB.filter())
async def on_format(query: CallbackQuery, callback_data: FormatCB, state: FSMContext) -> None:
    fmt = callback_data.value
    await state.update_data(fmt=fmt)
    await state.set_state(Flow.searching)
    await query.message.edit_text(_FORMAT_MSG[fmt], reply_markup=main_menu_keyboard())
    await query.answer()


@router.callback_query(MenuCB.filter(F.action == "change_format"))
async def on_change_format(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.choosing_format)
    await query.message.edit_text(texts.CHOOSE_FORMAT, reply_markup=format_keyboard())
    await query.answer()


@router.callback_query(MenuCB.filter(F.action == "back_to_menu"))
async def on_back_to_menu(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    fmt = data.get("fmt", "pdf")
    await state.set_state(Flow.searching)
    text = _FORMAT_MSG.get(fmt, texts.CHOOSE_FORMAT)
    # The previous message may be a photo card → can't edit_text; send fresh.
    try:
        await query.message.edit_text(text, reply_markup=main_menu_keyboard())
    except Exception:
        await query.message.answer(text, reply_markup=main_menu_keyboard())
    await query.answer()


# ── Categories ───────────────────────────────────────────────────────────────
@router.callback_query(MenuCB.filter(F.action == "categories"))
async def on_categories(query: CallbackQuery) -> None:
    categories = await asyncio.to_thread(db.get_categories)
    await query.message.edit_text(
        texts.CHOOSE_CATEGORY, reply_markup=categories_keyboard(categories)
    )
    await query.answer()


@router.callback_query(CategoryCB.filter())
async def on_category_pick(query: CallbackQuery, callback_data: CategoryCB) -> None:
    await query.answer(
        f"'{callback_data.slug}' — bu bo'lim keyingi bosqichda ishga tushadi.",
        show_alert=True,
    )


# ── Text query → DB search → cross-format → internet variants ─────────────────
@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    fmt = data.get("fmt")
    if not fmt:
        await message.answer(texts.NEED_FORMAT_FIRST, reply_markup=format_keyboard())
        return

    query = message.text.strip()
    await state.update_data(query=query, page=0, cross_format=False)
    status = await message.answer(texts.SEARCHING)

    # 1) DB in the chosen format.
    results, has_next = await search_page(query, page=0, fmt=fmt)
    if results:
        exact = ranking.best_exact(query, results)
        if exact is not None:
            await _show_card(status, state, "db", exact.id)
        else:
            await _render_results(status, query, 0, results, has_next)
        return

    # 2) Other format exists in the DB → cross-format fallback.
    alt, alt_has_next = await search_page(query, page=0, fmt=None)
    if alt:
        exact_alt = ranking.best_exact(query, alt)
        if exact_alt is not None:
            have = next((f for f in exact_alt.formats if f != fmt), None) or (
                exact_alt.formats[0] if exact_alt.formats else fmt
            )
            await status.edit_text(
                texts.cross_format_offer(exact_alt.title, fmt, have),
                reply_markup=offer_keyboard(exact_alt.id),
            )
        else:
            await state.update_data(cross_format=True)
            await _render_results(status, query, 0, alt, alt_has_next,
                                  note=texts.cross_format_list_note(fmt))
        return

    # 3) Nothing in the DB → search the internet for variants.
    if fmt == "pdf":
        await _search_web_pdf(status, state, query)
    else:
        await _search_youtube(status, state, query)


# ── DB results pagination ─────────────────────────────────────────────────────
@router.callback_query(PageCB.filter())
async def on_page(query: CallbackQuery, callback_data: PageCB, state: FSMContext) -> None:
    data = await state.get_data()
    fmt = data.get("fmt", "pdf")
    search_query = data.get("query")
    if not search_query:
        await query.answer()
        return

    search_fmt = None if data.get("cross_format") else fmt
    page = max(callback_data.page, 0)
    results, has_next = await search_page(search_query, page=page, fmt=search_fmt)
    if not results:
        await query.answer()
        return

    await state.update_data(page=page)
    await _render_results(query.message, search_query, page, results, has_next)
    await query.answer()


# ── Cross-format offer accept ─────────────────────────────────────────────────
@router.callback_query(OfferCB.filter())
async def on_offer_accept(query: CallbackQuery, callback_data: OfferCB, state: FSMContext) -> None:
    data = await state.get_data()
    fmt = data.get("fmt", "pdf")
    await query.answer(texts.SENDING)
    await delivery.deliver_book(query.message, callback_data.book_id, fmt)


# ── Pick a result/variant → show detail card ──────────────────────────────────
@router.callback_query(CardCB.filter())
async def on_card(query: CallbackQuery, callback_data: CardCB, state: FSMContext) -> None:
    await query.answer()
    await _show_card(query.message, state, callback_data.kind, callback_data.ref)


# ── Confirm → download (if needed) + deliver ──────────────────────────────────
@router.callback_query(SendCB.filter())
async def on_send(query: CallbackQuery, callback_data: SendCB, state: FSMContext) -> None:
    await query.answer(texts.SENDING)
    kind, ref = callback_data.kind, callback_data.ref
    if kind == "db":
        data = await state.get_data()
        await delivery.deliver_book(query.message, ref, data.get("fmt", "pdf"))
    elif kind == "pdf":
        await _send_web_pdf(query.message, state, int(ref))
    elif kind == "yt":
        await _send_youtube(query.message, state, int(ref))


# ── Internet search: PDF variants ─────────────────────────────────────────────
async def _search_web_pdf(status: Message, state: FSMContext, query: str) -> None:
    await status.edit_text(texts.SEARCHING_WEB_PDF)
    language = get_settings().default_language
    cands = await asyncio.to_thread(pdf_web.search_candidates, query, language)
    if not cands:
        await status.edit_text(texts.NO_VARIANTS)
        return
    await state.update_data(
        cand_kind="pdf",
        candidates=[{"title": c.title, "url": c.url, "site": c.site} for c in cands],
    )
    lines = [texts.pdf_variant_line(i + 1, c.title, c.site) for i, c in enumerate(cands)]
    await status.edit_text(
        texts.pdf_variants_header(query) + "\n\n" + "\n".join(lines),
        reply_markup=candidates_keyboard("pdf", len(cands)),
        disable_web_page_preview=True,
    )


# ── Internet search: YouTube audio variants ───────────────────────────────────
async def _search_youtube(status: Message, state: FSMContext, query: str) -> None:
    await status.edit_text(texts.SEARCHING_YOUTUBE)
    cands = await asyncio.to_thread(youtube_audio.search_candidates, query)
    if not cands:
        await status.edit_text(texts.NO_VARIANTS)
        return
    await state.update_data(
        cand_kind="yt",
        candidates=[
            {"video_id": c.video_id, "title": c.title,
             "duration": c.duration, "duration_str": c.duration_str,
             "uploader": c.uploader}
            for c in cands
        ],
    )
    lines = [
        texts.youtube_variant_line(i + 1, c.title, c.duration_str, c.uploader)
        for i, c in enumerate(cands)
    ]
    await status.edit_text(
        texts.youtube_variants_header(query) + "\n\n" + "\n".join(lines),
        reply_markup=candidates_keyboard("yt", len(cands)),
    )


# ── Confirm handlers: download + deliver ──────────────────────────────────────
async def _send_web_pdf(message: Message, state: FSMContext, index: int) -> None:
    data = await state.get_data()
    cands = data.get("candidates") or []
    if not (0 <= index < len(cands)) or data.get("cand_kind") != "pdf":
        return
    query = data.get("query", cands[index]["title"])
    max_bytes = get_settings().max_file_bytes
    default_lang = get_settings().default_language

    status = await message.answer(texts.DOWNLOADING_PDF)
    # The card step already resolved the picked candidate's PDF link(s); reuse them
    # (fast — no second page fetch). Then fall through to other candidates so the
    # user still gets a free PDF if their pick is a dead/blocked link.
    picked = cands[index]
    content, used = None, None
    if picked.get("pdf_links"):
        content = await asyncio.to_thread(pdf_web.download_links, picked["pdf_links"], max_bytes)
        if content is not None:
            used = picked
    if content is None:
        for i in [index] + [j for j in range(len(cands)) if j != index]:
            content = await asyncio.to_thread(
                pdf_web.download_validate, cands[i]["url"], max_bytes, query
            )
            if content is not None:
                used = cands[i]
                break

    if content is None:
        await status.edit_text(texts.DOWNLOAD_FAILED)
        return

    m = used.get("meta") or {}
    book_id = await asyncio.to_thread(
        db.save_pdf_book,
        query,
        content,
        author=m.get("author"),
        language=m.get("language") or default_lang,
        source="web",
        source_ref=used["url"],
        description=m.get("description"),
        cover_url=m.get("cover_url"),
    )
    await status.delete()
    await delivery.deliver_book(message, book_id, "pdf")


async def _send_youtube(message: Message, state: FSMContext, index: int) -> None:
    data = await state.get_data()
    cands = data.get("candidates") or []
    if not (0 <= index < len(cands)) or data.get("cand_kind") != "yt":
        return
    cand = cands[index]
    query = data.get("query", cand["title"])
    settings = get_settings()

    status = await message.answer(texts.DOWNLOADING_AUDIO)
    workdir = Path(tempfile.mkdtemp(prefix="bookbot_audio_"))
    try:
        # Split into ~audio_part_mb chunks (<= the 50 MB Telegram cap) so each
        # part uploads reliably.
        part_bytes = min(settings.audio_part_mb, settings.max_file_mb) * 1024 * 1024
        parts = await asyncio.to_thread(
            youtube_audio.download_audio,
            cand["video_id"], workdir, part_bytes, settings.audio_bitrate_kbps,
        )
        if not parts:
            await status.edit_text(texts.DOWNLOAD_FAILED)
            return

        meta = await asyncio.to_thread(metadata.lookup, query)
        title = meta.title if meta else cand["title"]
        performer = meta.author_str if meta else cand.get("uploader")
        await status.delete()

        file_ids = await delivery.send_audio_parts(message, parts, title, performer)
        total_bytes = sum(p.stat().st_size for p in parts)
        await asyncio.to_thread(
            db.save_audio_book,
            title,
            youtube_id=cand["video_id"],
            telegram_file_ids=file_ids,
            author=meta.author_str if meta else None,
            language=(meta.language if meta and meta.language else settings.default_language),
            source_ref=f"https://www.youtube.com/watch?v={cand['video_id']}",
            description=meta.description if meta else None,
            cover_url=meta.cover_url if meta else None,
            size_bytes=total_bytes,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ── Detail card rendering ─────────────────────────────────────────────────────
async def _show_card(message: Message, state: FSMContext, kind: str, ref: str) -> None:
    """Build and show the detail card for a DB book or an internet variant."""
    data = await state.get_data()
    fmt = data.get("fmt", "pdf")
    query = data.get("query", "")

    if kind == "db":
        book = await asyncio.to_thread(db.get_book, ref)
        if not book:
            await message.answer(texts.FILE_MISSING)
            return
        description, cover_url = book.get("description"), book.get("cover_url")
        author, language, genre = book.get("author"), book.get("language"), None
        description, cover_url, genre, language, author = await _enrich(
            book["title"], author, description=description, cover_url=cover_url,
            genre=genre, language=language)
        if description and not book.get("description"):  # persist for next time
            await asyncio.to_thread(db.update_book_meta, ref, description=description,
                                    cover_url=cover_url)
        card = cards.build_card(
            title=book["title"], fmt=fmt, author=author, language=language,
            description=description, cover_url=cover_url, genre=genre,
        )

    elif kind == "pdf":
        cands = data.get("candidates") or []
        idx = int(ref)
        if not (0 <= idx < len(cands)):
            await message.answer(texts.NOT_FOUND)
            return
        cand = cands[idx]
        title = query or cand["title"]
        # One page fetch → the page's own cover/description/genre + the PDF link(s),
        # which we cache so the confirm step doesn't fetch the page again.
        pmeta, links = await asyncio.to_thread(pdf_web.page_info, cand["url"], title)
        cand["pdf_links"] = links
        cands[idx] = cand
        await state.update_data(candidates=cands)

        cover = pmeta.cover_url if pmeta else None
        desc = pmeta.description if pmeta else None
        genre = pmeta.genre if pmeta else None
        author = pmeta.author_str if pmeta else None
        desc, cover, genre, language, author = await _enrich(
            title, author, description=desc, cover_url=cover, genre=genre, language="uz")
        cand["meta"] = {"author": author, "language": language,
                        "description": desc, "cover_url": cover}
        cands[idx] = cand
        await state.update_data(candidates=cands)
        card = cards.build_card(
            title=title, fmt="pdf", author=author, language=language,
            description=desc, cover_url=cover, genre=genre, site=cand.get("site"),
        )

    else:  # kind == "yt"
        cands = data.get("candidates") or []
        idx = int(ref)
        if not (0 <= idx < len(cands)):
            await message.answer(texts.NOT_FOUND)
            return
        cand = cands[idx]
        title = query or cand["title"]
        desc, cover, genre, language, author = await _enrich(
            title, cand.get("uploader"))
        card = cards.build_card(
            title=title, fmt="mp3", author=author, language=language,
            description=desc, cover_url=cover, genre=genre,
            duration=cand.get("duration_str"),
        )

    kb = card_keyboard(kind, ref)
    # The picked-from message is text; a card may be a photo → replace it.
    try:
        await message.delete()
    except Exception:
        pass
    if card.cover_url:
        try:
            await message.answer_photo(card.cover_url, caption=card.text, reply_markup=kb)
            return
        except Exception:
            log.info("Cover photo send failed, falling back to text card")
    await message.answer(card.text, reply_markup=kb, disable_web_page_preview=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
async def _enrich(title, author, *, description=None, cover_url=None, genre=None,
                  language=None):
    """Fill gaps: cover/language from OpenLibrary, description/genre from OpenAI —
    run concurrently (so the card isn't slowed by two sequential network calls).
    Returns (description, cover_url, genre, language, author)."""
    want_ol = (not cover_url) or (not language) or (not author)
    want_ai = (not description) or (not genre)
    ol = ai = None
    if want_ol and want_ai:
        ol, ai = await asyncio.gather(
            asyncio.to_thread(metadata.lookup, title, author, with_description=False),
            asyncio.to_thread(ai_meta.lookup, title, author),
        )
    elif want_ol:
        ol = await asyncio.to_thread(metadata.lookup, title, author, with_description=False)
    elif want_ai:
        ai = await asyncio.to_thread(ai_meta.lookup, title, author)
    if ol:
        cover_url = cover_url or ol.cover_url
        language = language or ol.language
        author = author or ol.author_str
    if ai:
        description = description or ai.description
        genre = genre or ai.genre
    return description, cover_url, genre, language, author


async def _render_results(message: Message, query: str, page: int, results, has_next,
                          note: str | None = None) -> None:
    """Edit ``message`` to show the numbered results list + pagination keyboard."""
    start = page * PAGE_SIZE
    lines = [texts.result_line(start + i + 1, r.label) for i, r in enumerate(results)]
    parts = []
    if note:
        parts.append(note)
    parts.append(texts.results_header(query, page))
    parts.append("\n".join(lines))
    parts.append(texts.RESULTS_PROMPT)
    text = "\n\n".join(parts)
    kb = results_keyboard([r.id for r in results], page, has_next)
    try:
        await message.edit_text(text, reply_markup=kb)
    except Exception:
        await message.answer(text, reply_markup=kb)
