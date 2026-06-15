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
from aiogram.types import CallbackQuery, Message

from .. import db
from ..config import get_settings
from ..providers import metadata, pdf_web, youtube_audio
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
    cand = cands[index]
    query = data.get("query", cand["title"])
    language = get_settings().default_language

    status = await message.answer(texts.DOWNLOADING_PDF)
    content = await asyncio.to_thread(
        pdf_web.download_validate, cand["url"], get_settings().max_file_bytes
    )
    if content is None:
        await status.edit_text(texts.DOWNLOAD_FAILED)
        return

    meta = await asyncio.to_thread(metadata.lookup, query)
    book_id = await asyncio.to_thread(
        db.save_pdf_book,
        meta.title if meta else query,
        content,
        author=meta.author_str if meta else None,
        language=(meta.language if meta and meta.language else language),
        source="web",
        source_ref=cand["url"],
        description=meta.description if meta else None,
        cover_url=meta.cover_url if meta else None,
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
        parts = await asyncio.to_thread(
            youtube_audio.download_audio,
            cand["video_id"], workdir, settings.max_file_bytes, settings.audio_bitrate_kbps,
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
        description = book.get("description")
        cover_url = book.get("cover_url")
        author = book.get("author")
        language = book.get("language")
        # Enrich missing description/cover from OpenLibrary (best-effort).
        if not description or not cover_url:
            meta = await asyncio.to_thread(metadata.lookup, book["title"], author)
            if meta:
                description = description or meta.description
                cover_url = cover_url or meta.cover_url
                language = language or meta.language
                author = author or meta.author_str
        card = cards.build_card(
            title=book["title"], fmt=fmt, author=author, language=language,
            description=description, cover_url=cover_url,
        )
    else:
        cands = data.get("candidates") or []
        idx = int(ref)
        if not (0 <= idx < len(cands)):
            await message.answer(texts.NOT_FOUND)
            return
        cand = cands[idx]
        meta = await asyncio.to_thread(metadata.lookup, query)
        card = cards.build_card(
            title=(meta.title if meta else cand["title"]),
            fmt=("pdf" if kind == "pdf" else "mp3"),
            author=(meta.author_str if meta else cand.get("uploader")),
            language=(meta.language if meta else None),
            description=(meta.description if meta else None),
            cover_url=(meta.cover_url if meta else None),
            duration=(cand.get("duration_str") if kind == "yt" else None),
            site=(cand.get("site") if kind == "pdf" else None),
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
