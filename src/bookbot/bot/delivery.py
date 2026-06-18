"""Deliver a book file to the user, with Telegram ``file_id`` caching.

Delivery policy (Phase 2 — PDF from Supabase Storage):

  1. If we already cached a Telegram ``file_id`` for this file → re-send by id
     (instant, no download).
  2. Otherwise download the PDF bytes from Storage, send as a document, and cache
     the ``file_id`` Telegram returns so the next user is served instantly.

Audio (mp3) delivery and the web/YouTube fallback arrive in Phases 3–5. For now a
book whose chosen-format file has neither a cached id nor a stored path is
reported as missing.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from aiogram.types import BufferedInputFile, FSInputFile, Message

from .. import db
from . import texts

log = logging.getLogger(__name__)

_CONTENT_TYPE = {"pdf": "application/pdf", "mp3": "audio/mpeg"}
_FMT_EMOJI = {"pdf": "📕", "mp3": "🎧"}


def _safe_filename(title: str, ext: str) -> str:
    """A clean, human filename from the book title (no path/odd chars)."""
    name = re.sub(r'[\\/:*?"<>|]+', " ", title).strip()
    name = re.sub(r"\s+", " ", name)[:80] or "kitob"
    return f"{name}.{ext}"


def _caption(book: dict | None, fmt: str) -> str | None:
    if not book:
        return None
    title = book.get("title") or ""
    author = book.get("author")
    emoji = _FMT_EMOJI.get(fmt, "📘")
    return f"{emoji} <b>{title}</b>" + (f"\n✍️ {author}" if author else "")


async def deliver_book(message: Message, book_id: str, fmt: str) -> bool:
    """Send the book's file to ``message.chat``. Returns success.

    Prefers the requested ``fmt``; if the book has no file in that format it
    falls back to whatever format it *does* have (the cross-format case — the
    caller has typically already offered the other format to the user).
    """
    files = await asyncio.to_thread(db.get_book_files, book_id)
    target = next((f for f in files if f.format == fmt), None)
    if target is None:
        target = files[0] if files else None
    if target is None:
        await message.answer(texts.FILE_MISSING)
        return False

    book = await asyncio.to_thread(db.get_book, book_id)
    caption = _caption(book, target.format)

    # 1) Cached file_id → instant re-send. Audio may hold comma-joined part ids.
    if target.telegram_file_id:
        try:
            if target.format == "pdf":
                await message.answer_document(target.telegram_file_id, caption=caption)
            else:
                ids = [i for i in target.telegram_file_id.split(",") if i]
                await _send_cached_audio(message, ids, caption)
            return True
        except Exception:  # cached id may be stale (file deleted on Telegram side)
            log.warning("Cached file_id failed for book %s, falling back", book_id)

    # 2) Channel-sourced book → copy_message from our storage channel. This is
    #    served straight off Telegram's servers (no re-upload), so it has no
    #    50 MB cap and is instant — perfect for big audiobooks.
    if target.tg_chat_id and target.tg_msg_id:
        try:
            await message.bot.copy_message(
                chat_id=message.chat.id,
                from_chat_id=target.tg_chat_id,
                message_id=target.tg_msg_id,
                caption=caption,
            )
            return True
        except Exception:
            log.warning("copy_message from storage failed for book %s", book_id)
            # fall through to storage_path if any, else report missing below.

    # 3) Download from Storage and upload to Telegram (PDF only for now — audio
    #    files are not stored; they arrive via the YouTube provider in Phase 5).
    if not target.storage_path:
        await message.answer(texts.FILE_MISSING)
        return False

    try:
        content = await asyncio.to_thread(db.download_file, target.storage_path)
    except Exception:
        log.exception("Storage download failed for %s", target.storage_path)
        await message.answer(texts.DELIVER_FAILED)
        return False

    # Name the file after the book (not the ugly storage uuid) so it doesn't look
    # like a sketchy random download.
    title = (book or {}).get("title") or target.storage_path.rsplit("/", 1)[-1]
    filename = _safe_filename(title, "pdf")
    sent = await message.answer_document(
        BufferedInputFile(content, filename=filename), caption=caption
    )

    # 3) Cache the returned file_id for next time.
    if sent.document and target.id:
        await asyncio.to_thread(
            db.set_telegram_file_id, target.id, sent.document.file_id
        )
    return True


# ── Audio (YouTube) delivery ──────────────────────────────────────────────────
async def _send_cached_audio(message: Message, file_ids: list[str], caption: str | None) -> None:
    """Re-send audio from cached Telegram file_id(s) — instant, no re-download."""
    total = len(file_ids)
    for i, fid in enumerate(file_ids, 1):
        part_cap = caption if total == 1 else f"{caption or ''}\n🎧 {i}/{total}".strip()
        await message.answer_audio(fid, caption=part_cap)


async def send_audio_parts(
    message: Message, paths: list[Path], title: str, performer: str | None = None
) -> list[str]:
    """Send freshly-downloaded local mp3 part(s) as audio; return their file_ids.

    For a split audiobook the parts are labelled 1/N, 2/N, … and sent in order.
    """
    total = len(paths)
    if total > 1:
        await message.answer(texts.AUDIO_PARTS_NOTE)
    file_ids: list[str] = []
    for i, path in enumerate(paths, 1):
        part_title = title if total == 1 else f"{title} — {i}/{total}"
        ext = path.suffix.lstrip(".").lower() or "mp3"
        sent = await message.answer_audio(
            FSInputFile(str(path), filename=_safe_filename(part_title, ext)),
            title=part_title,
            performer=performer,
        )
        if sent.audio:
            file_ids.append(sent.audio.file_id)
    return file_ids
