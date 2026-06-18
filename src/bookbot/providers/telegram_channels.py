"""Find books inside Telegram channels via a Telethon user account.

This is the fastest, most reliable source: many Uzbek book channels already host
the actual PDF/audio files. A logged-in **user account** (not the bot — the Bot
API can't search channel contents) searches the configured `SOURCE_CHANNELS`,
and the matched message is **forwarded into our private storage channel**; the
bot then delivers it with `copy_message` (no re-upload → no 50 MB cap, up to
2 GB). All of this is skipped gracefully when Telethon isn't configured.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    InputMessagesFilterDocument,
    InputMessagesFilterMusic,
)

from ..bot import textclean
from ..config import get_settings

log = logging.getLogger(__name__)

_client: TelegramClient | None = None
_lock = asyncio.Lock()


@dataclass(slots=True)
class ChannelCandidate:
    chat_id: int          # source channel (peer id)
    message_id: int
    title: str            # cleaned, human title
    filename: str | None
    size_bytes: int
    is_audio: bool
    duration: int = 0     # seconds (audio only)
    channel: str = ""     # source channel ref (internal; never shown to users)
    caption: str = ""     # source message text — real metadata to ground the AI

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    @property
    def duration_str(self) -> str:
        if not self.duration:
            return ""
        h, rem = divmod(self.duration, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


async def _get_client() -> TelegramClient:
    """Lazily create + connect a shared Telethon client on the running loop."""
    global _client
    async with _lock:
        s = get_settings()
        if _client is None:
            _client = TelegramClient(
                StringSession(s.telethon_session), s.telethon_api_id, s.telethon_api_hash
            )
        if not _client.is_connected():
            await _client.connect()
        return _client


def _filename(doc) -> str | None:
    for a in doc.attributes:
        if isinstance(a, DocumentAttributeFilename):
            return a.file_name
    return None


def _audio_attr(doc) -> DocumentAttributeAudio | None:
    for a in doc.attributes:
        if isinstance(a, DocumentAttributeAudio):
            return a
    return None


def _to_candidate(msg, fmt: str, channel: str) -> ChannelCandidate | None:
    doc = getattr(msg, "document", None)
    if doc is None:
        return None
    fname = _filename(doc)
    audio = _audio_attr(doc)
    mime = (doc.mime_type or "").lower()

    if fmt == "pdf":
        is_pdf = mime == "application/pdf" or (fname or "").lower().endswith(".pdf")
        if not is_pdf:
            return None
    else:  # mp3 / audio
        is_audio = bool(audio) or mime.startswith("audio/") or (fname or "").lower().endswith(
            (".mp3", ".m4a", ".ogg")
        )
        if not is_audio:
            return None

    # Build a clean title from the filename (falls back to the caption's first line).
    raw = fname or (msg.message or "").split("\n", 1)[0]
    title = textclean.clean_title(raw) or (raw or "Kitob")
    return ChannelCandidate(
        chat_id=msg.chat_id,
        message_id=msg.id,
        title=title,
        filename=fname,
        size_bytes=doc.size or 0,
        is_audio=fmt != "pdf",
        duration=(audio.duration if audio else 0) or 0,
        channel=channel,
        caption=(msg.message or "").strip(),
    )


def _score(query: str, title: str) -> float:
    return fuzz.token_set_ratio(query.lower(), title.lower())


async def search(
    query: str, fmt: str, *, per_channel: int = 4, limit: int = 8, min_score: int = 55
) -> list[ChannelCandidate]:
    """Search every source channel for files matching ``query`` in ``fmt``.

    Returns title-ranked, domain-deduped candidates (best first). Empty when
    Telethon is disabled or nothing relevant is found (caller then tries the web).
    """
    s = get_settings()
    if not s.telethon_enabled or not s.source_channel_list:
        return []
    try:
        client = await _get_client()
    except Exception:
        log.exception("Telethon connect failed")
        return []

    filters = [InputMessagesFilterDocument]
    if fmt != "pdf":
        # Audio files are often tagged as music; search that index too.
        filters = [InputMessagesFilterMusic, InputMessagesFilterDocument]

    found: list[ChannelCandidate] = []
    for channel in s.source_channel_list:
        for flt in filters:
            try:
                async for msg in client.iter_messages(
                    channel, search=query, filter=flt, limit=per_channel
                ):
                    cand = _to_candidate(msg, fmt, channel)
                    if cand:
                        found.append(cand)
            except Exception:
                log.warning("Channel search failed for %s", channel, exc_info=True)

    # Rank by title similarity; drop weak matches; dedupe by (title, size).
    ranked = sorted(found, key=lambda c: _score(query, c.title), reverse=True)
    out: list[ChannelCandidate] = []
    seen: set[tuple[str, int]] = set()
    for c in ranked:
        if _score(query, c.title) < min_score:
            continue
        key = (c.title.lower(), c.size_bytes)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= limit:
            break
    return out


async def forward_to_storage(chat_id: int, message_id: int) -> tuple[int, int]:
    """FAST path: forward the file into the storage channel by reference (no bytes
    moved → instant, any size). The source channel is hidden once the bot copies it
    out, but the file keeps its original embedded filename (Telegram won't rename a
    referenced file) — the caption is cleaned by the bot at copy time. Returns the
    storage ref."""
    s = get_settings()
    client = await _get_client()
    storage = int(s.storage_channel_id)
    sent = await client.forward_messages(storage, message_id, chat_id)
    msg = sent[0] if isinstance(sent, list) else sent
    return storage, msg.id


async def fetch_to_storage(
    chat_id: int,
    message_id: int,
    *,
    filename: str,
    caption: str,
    is_audio: bool,
    title: str | None = None,
    performer: str | None = None,
    duration: int = 0,
) -> tuple[int, int]:
    """Download the source file and RE-UPLOAD it into our storage channel with a
    clean filename + our own caption, so no source-channel watermark survives
    (a plain forward/copy keeps the original embedded filename). The userbot has
    no 50 MB cap, so this works for big audiobooks too. Returns the storage ref
    (chat_id, message_id) for the bot to copy_message from.
    """
    s = get_settings()
    client = await _get_client()
    storage = int(s.storage_channel_id)
    src = await client.get_messages(chat_id, ids=message_id)
    workdir = Path(tempfile.mkdtemp(prefix="bookbot_tg_"))
    try:
        path = await client.download_media(src, file=str(workdir / "book"))
        if not path:
            raise RuntimeError("download_media returned no file")
        attrs = [DocumentAttributeFilename(filename)]
        if is_audio:
            attrs.append(
                DocumentAttributeAudio(
                    duration=duration or 0, title=title, performer=performer
                )
            )
        sent = await client.send_file(
            storage,
            path,
            caption=caption,
            parse_mode="html",
            force_document=not is_audio,
            attributes=attrs,
        )
        return storage, sent.id
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
