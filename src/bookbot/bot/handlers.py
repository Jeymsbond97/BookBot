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
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message

from .. import db
from ..categories import category_for_genre
from ..config import get_settings
from ..providers import ai_meta, metadata, pdf_web, telegram_channels, youtube_audio
from . import cards, delivery, ranking, textclean, texts
from .keyboards import (
    AdminCatCB,
    AdminLangCB,
    CardCB,
    CategoryCB,
    CatPageCB,
    FormatCB,
    LangCB,
    MenuCB,
    OfferCB,
    PageCB,
    SendCB,
    admin_categories_keyboard,
    admin_language_keyboard,
    browse_keyboard,
    candidates_keyboard,
    card_keyboard,
    categories_keyboard,
    format_keyboard,
    language_keyboard,
    main_menu_keyboard,
    offer_keyboard,
    results_keyboard,
)
from .search import PAGE_SIZE, browse_page, search_page
from .states import AdminUpload, Flow

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


# ── Admin: upload a PDF into the catalog (Phase 7) ─────────────────────────────
def _is_admin(message: Message) -> bool:
    return bool(message.from_user) and get_settings().is_admin(message.from_user.id)


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message):
        await message.answer(texts.ADMIN_ONLY)
        return
    await message.answer(texts.ADMIN_HELP)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    cur = await state.get_state()
    if cur and cur.startswith("AdminUpload"):
        await state.set_state(Flow.searching)
        await message.answer(texts.ADMIN_CANCELLED, reply_markup=main_menu_keyboard())
    else:
        await message.answer(texts.ADMIN_CANCELLED)


@router.message(F.document)
async def on_admin_document(message: Message, state: FSMContext) -> None:
    """An admin sending a PDF starts the upload wizard. Non-admins are told it's
    admin-only (so a normal user who sends a file isn't ignored)."""
    if not _is_admin(message):
        await message.answer(texts.ADMIN_ONLY)
        return
    doc = message.document
    is_pdf = (doc.mime_type == "application/pdf") or (
        (doc.file_name or "").lower().endswith(".pdf")
    )
    if not is_pdf:
        await message.answer(texts.ADMIN_NOT_PDF)
        return

    from pathlib import PurePath

    suggested = PurePath(doc.file_name or "kitob").stem
    await state.set_state(AdminUpload.title)
    await state.update_data(
        up_file_id=doc.file_id, up_suggested=suggested, up_filename=doc.file_name
    )
    await message.answer(texts.admin_ask_title(suggested))


@router.message(StateFilter(AdminUpload.title), F.text)
async def on_admin_title(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    title = message.text.strip()
    if title == "-":
        title = data.get("up_suggested") or "Kitob"
    await state.update_data(up_title=title)
    await state.set_state(AdminUpload.author)
    await message.answer(texts.ADMIN_ASK_AUTHOR)


@router.message(StateFilter(AdminUpload.author), F.text)
async def on_admin_author(message: Message, state: FSMContext) -> None:
    author = message.text.strip()
    author = None if author == "-" else author
    await state.update_data(up_author=author)
    await state.set_state(AdminUpload.category)
    categories = await asyncio.to_thread(db.get_categories)
    await message.answer(texts.ADMIN_ASK_CATEGORY,
                         reply_markup=admin_categories_keyboard(categories))


@router.callback_query(StateFilter(AdminUpload.category), AdminCatCB.filter())
async def on_admin_category(query: CallbackQuery, callback_data: AdminCatCB, state: FSMContext) -> None:
    cat = await asyncio.to_thread(db.get_category, callback_data.slug)
    await state.update_data(
        up_cat_slug=callback_data.slug,
        up_cat_name=(cat or {}).get("name_uz") or callback_data.slug,
    )
    await state.set_state(AdminUpload.language)
    await query.message.edit_text(texts.ADMIN_ASK_LANGUAGE,
                                  reply_markup=admin_language_keyboard())
    await query.answer()


@router.callback_query(StateFilter(AdminUpload.language), AdminLangCB.filter())
async def on_admin_language(query: CallbackQuery, callback_data: AdminLangCB, state: FSMContext) -> None:
    data = await state.get_data()
    await query.answer()
    status = await query.message.edit_text(texts.ADMIN_SAVING)

    # Download the PDF bytes from Telegram, then store like any other PDF.
    try:
        buf = await query.bot.download(data["up_file_id"])
        content = buf.read()
    except Exception:
        log.exception("Admin PDF download failed")
        await status.edit_text(texts.DOWNLOAD_FAILED)
        await state.set_state(Flow.searching)
        return

    title = data.get("up_title") or data.get("up_suggested") or "Kitob"
    slug = data.get("up_cat_slug")
    book_id = await asyncio.to_thread(
        db.save_pdf_book,
        title,
        content,
        author=data.get("up_author"),
        language=callback_data.value,
        source="admin",
        source_ref=data.get("up_filename"),
    )
    if slug:
        await asyncio.to_thread(db.set_book_category, book_id, slug)

    await state.set_state(Flow.searching)
    await status.edit_text(
        texts.admin_saved(title, data.get("up_cat_name")),
        reply_markup=main_menu_keyboard(data.get("lang")),
    )


# ── Format selection ─────────────────────────────────────────────────────────
@router.callback_query(FormatCB.filter())
async def on_format(query: CallbackQuery, callback_data: FormatCB, state: FSMContext) -> None:
    fmt = callback_data.value
    await state.update_data(fmt=fmt)
    await state.set_state(Flow.searching)
    data = await state.get_data()
    await query.message.edit_text(
        _FORMAT_MSG[fmt], reply_markup=main_menu_keyboard(data.get("lang"))
    )
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
    kb = main_menu_keyboard(data.get("lang"))
    # The previous message may be a photo card → can't edit_text; send fresh.
    try:
        await query.message.edit_text(text, reply_markup=kb)
    except Exception:
        await query.message.answer(text, reply_markup=kb)
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
async def on_category_pick(query: CallbackQuery, callback_data: CategoryCB, state: FSMContext) -> None:
    await _render_browse(query.message, state, callback_data.slug, 0)
    await query.answer()


@router.callback_query(CatPageCB.filter())
async def on_cat_page(query: CallbackQuery, callback_data: CatPageCB, state: FSMContext) -> None:
    await _render_browse(query.message, state, callback_data.slug, max(callback_data.page, 0))
    await query.answer()


# ── Language filter ────────────────────────────────────────────────────────────
@router.callback_query(MenuCB.filter(F.action == "language"))
async def on_language_menu(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await query.message.edit_text(
        texts.LANGUAGE_PROMPT, reply_markup=language_keyboard(data.get("lang"))
    )
    await query.answer()


@router.callback_query(LangCB.filter())
async def on_language_set(query: CallbackQuery, callback_data: LangCB, state: FSMContext) -> None:
    lang = None if callback_data.value == "all" else callback_data.value
    await state.update_data(lang=lang)
    await query.message.edit_text(
        texts.language_set(lang), reply_markup=main_menu_keyboard(lang)
    )
    await query.answer()


# ── Text query → DB search → cross-format → internet variants ─────────────────
@router.message(
    F.text & ~F.text.startswith("/"),
    StateFilter(Flow.choosing_format, Flow.searching, None),
)
async def on_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    fmt = data.get("fmt")
    if not fmt:
        await message.answer(texts.NEED_FORMAT_FIRST, reply_markup=format_keyboard())
        return
    lang = data.get("lang")

    query = message.text.strip()
    await state.update_data(query=query, page=0, cross_format=False)
    status = await message.answer(texts.SEARCHING)

    # 1) DB in the chosen format.
    results, has_next = await search_page(query, page=0, fmt=fmt, language=lang)
    if results:
        exact = ranking.best_exact(query, results)
        if exact is not None:
            await _show_card(status, state, "db", exact.id)
        else:
            await _render_results(status, query, 0, results, has_next)
        return

    # 2) Other format exists in the DB → cross-format fallback.
    alt, alt_has_next = await search_page(query, page=0, fmt=None, language=lang)
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

    # 3) Nothing in the DB → try Telegram book channels first (fast, real files,
    #    no size cap), then fall back to the open web / YouTube.
    if await _search_channels(status, state, query, fmt):
        return
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
    results, has_next = await search_page(
        search_query, page=page, fmt=search_fmt, language=data.get("lang")
    )
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
    elif kind == "tg":
        await _send_channel(query.message, state, int(ref))
    elif kind == "pdf":
        await _send_web_pdf(query.message, state, int(ref))
    elif kind == "yt":
        await _send_youtube(query.message, state, int(ref))


# ── Telegram channel search (preferred source) ────────────────────────────────
async def _search_channels(status: Message, state: FSMContext, query: str, fmt: str) -> bool:
    """Search the configured book channels. Returns True if it showed a variant
    list (so the caller skips the web/YouTube fallback)."""
    if not get_settings().telethon_enabled:
        return False
    await status.edit_text(texts.SEARCHING_CHANNELS)
    try:
        cands = await telegram_channels.search(query, fmt)
    except Exception:
        log.exception("Telegram channel search failed")
        return False
    if not cands:
        return False
    await state.update_data(
        cand_kind="tg",
        candidates=[
            {"chat_id": c.chat_id, "message_id": c.message_id, "title": c.title,
             "size_bytes": c.size_bytes, "is_audio": c.is_audio,
             "duration": c.duration, "duration_str": c.duration_str,
             "channel": c.channel, "caption": c.caption}
            for c in cands
        ],
    )
    lines = [
        texts.channel_variant_line(
            i + 1, c.title, c.size_mb, c.duration_str if c.is_audio else ""
        )
        for i, c in enumerate(cands)
    ]
    await status.edit_text(
        texts.channel_variants_header(query) + "\n\n" + "\n".join(lines),
        reply_markup=candidates_keyboard("tg", len(cands), direct=True),
    )
    return True


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
async def _send_channel(message: Message, state: FSMContext, index: int) -> None:
    """One-tap delivery of a channel result: enrich → re-upload into storage with a
    clean filename + rich caption (no source watermark) → save → deliver."""
    data = await state.get_data()
    cands = data.get("candidates") or []
    if not (0 <= index < len(cands)) or data.get("cand_kind") != "tg":
        return
    cand = cands[index]
    is_audio = bool(cand.get("is_audio"))
    fmt = "mp3" if is_audio else "pdf"
    title = textclean.clean_title(data.get("query") or cand["title"]) or cand["title"]

    status = await message.answer(texts.SENDING)

    # AI tasnif (5-6 jumla) + author/genre/language/cover — grounded in the source
    # channel caption + web snippets so it's accurate, not invented.
    desc, cover, genre, language, author = await _enrich(
        title, None, context=cand.get("caption", "")
    )
    language = language or get_settings().default_language
    size_mb = (cand.get("size_bytes") or 0) / (1024 * 1024)
    caption = cards.build_card(
        title=title, fmt=fmt, author=author, language=language, description=desc,
        genre=genre, size_mb=size_mb,
        duration=(cand.get("duration_str") if is_audio else None),
        for_caption=True,
    ).text
    try:
        if get_settings().rebrand_files:
            # Clean filename (re-upload). Slower on a slow network, instant after.
            filename = delivery._safe_filename(title, "mp3" if is_audio else "pdf")
            storage_chat, storage_msg = await telegram_channels.fetch_to_storage(
                cand["chat_id"], cand["message_id"],
                filename=filename, caption=caption, is_audio=is_audio,
                title=title, performer=author, duration=cand.get("duration") or 0,
            )
        else:
            # Instant forward (keeps original filename; caption cleaned at copy time).
            storage_chat, storage_msg = await telegram_channels.forward_to_storage(
                cand["chat_id"], cand["message_id"],
            )
    except Exception:
        log.exception("Channel fetch→storage failed")
        await status.edit_text(texts.DOWNLOAD_FAILED)
        return

    book_id = await asyncio.to_thread(
        db.save_telegram_book,
        title,
        fmt,
        tg_chat_id=storage_chat,
        tg_msg_id=storage_msg,
        author=author,
        language=language,
        description=desc,
        cover_url=cover,
        size_bytes=cand.get("size_bytes"),
    )
    slug = category_for_genre(genre)
    if slug:
        await asyncio.to_thread(db.set_book_category, book_id, slug)
    await status.delete()
    await delivery.deliver_book(message, book_id, fmt)


async def _send_web_pdf(message: Message, state: FSMContext, index: int) -> None:
    data = await state.get_data()
    cands = data.get("candidates") or []
    if not (0 <= index < len(cands)) or data.get("cand_kind") != "pdf":
        return
    raw_query = data.get("query", cands[index]["title"])
    query = textclean.clean_title(raw_query) or raw_query
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
    slug = category_for_genre(m.get("genre"))
    if slug:
        await asyncio.to_thread(db.set_book_category, book_id, slug)
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
        book_id = await asyncio.to_thread(
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
        slug = category_for_genre(cand.get("genre"))
        if slug:
            await asyncio.to_thread(db.set_book_category, book_id, slug)
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
            title=textclean.clean_title(book["title"]) or book["title"],
            fmt=fmt, author=author, language=language,
            description=description, cover_url=cover_url, genre=genre,
        )

    elif kind == "pdf":
        cands = data.get("candidates") or []
        idx = int(ref)
        if not (0 <= idx < len(cands)):
            await message.answer(texts.NOT_FOUND)
            return
        cand = cands[idx]
        title = textclean.clean_title(query or cand["title"]) or cand["title"]
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
                        "description": desc, "cover_url": cover, "genre": genre}
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
        title = textclean.clean_title(query or cand["title"]) or cand["title"]
        desc, cover, genre, language, author = await _enrich(
            title, cand.get("uploader"))
        cand["genre"] = genre
        cands[idx] = cand
        await state.update_data(candidates=cands)
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
                  language=None, context=""):
    """Fill gaps: cover/language from OpenLibrary, description/genre/author from OpenAI
    (grounded in ``context`` — e.g. the source channel caption — + web snippets) —
    run concurrently. Returns (description, cover_url, genre, language, author)."""
    # Drop scraped SEO junk / placeholder covers up front so the clean AI
    # description and a real OpenLibrary cover are fetched to replace them.
    description = textclean.clean_description(description)
    cover_url = textclean.clean_cover(cover_url)
    want_ol = (not cover_url) or (not language) or (not author)
    want_ai = (not description) or (not genre)
    ol = ai = None
    if want_ol and want_ai:
        ol, ai = await asyncio.gather(
            asyncio.to_thread(metadata.lookup, title, author, with_description=False),
            asyncio.to_thread(ai_meta.lookup, title, author, context),
        )
    elif want_ol:
        ol = await asyncio.to_thread(metadata.lookup, title, author, with_description=False)
    elif want_ai:
        ai = await asyncio.to_thread(ai_meta.lookup, title, author, context)
    if ol:
        cover_url = cover_url or ol.cover_url
        language = language or ol.language
        author = author or ol.author_str
    if ai:
        description = description or ai.description
        genre = genre or ai.genre
        author = author or ai.author
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


async def _render_browse(message: Message, state: FSMContext, slug: str, page: int) -> None:
    """Show a category's books as a numbered, paginated list (reuses the card flow)."""
    data = await state.get_data()
    fmt = data.get("fmt")  # keep the user's chosen format filter; None = any
    cat = await asyncio.to_thread(db.get_category, slug)
    name = (cat or {}).get("name_uz") or slug

    results, has_next = await browse_page(slug, page, fmt=fmt, language=data.get("lang"))
    if not results:
        try:
            await message.edit_text(texts.category_empty(name),
                                    reply_markup=main_menu_keyboard(data.get("lang")))
        except Exception:
            await message.answer(texts.category_empty(name),
                                 reply_markup=main_menu_keyboard(data.get("lang")))
        return

    start = page * PAGE_SIZE
    lines = [texts.result_line(start + i + 1, r.label) for i, r in enumerate(results)]
    text = texts.browse_header(name, page) + "\n\n" + "\n".join(lines) + "\n\n" + texts.RESULTS_PROMPT
    kb = browse_keyboard([r.id for r in results], slug, page, has_next)
    try:
        await message.edit_text(text, reply_markup=kb)
    except Exception:
        await message.answer(text, reply_markup=kb)
