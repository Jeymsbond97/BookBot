"""Unit tests for the Telegram-channel provider's pure helpers (no network)."""

from __future__ import annotations

from dataclasses import dataclass

from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeFilename

from bookbot.providers import telegram_channels as tc


@dataclass
class _Doc:
    size: int
    mime_type: str
    attributes: list


@dataclass
class _Msg:
    id: int
    chat_id: int
    message: str
    document: object


def _pdf_msg(name: str, size: int = 5_000_000) -> _Msg:
    doc = _Doc(size=size, mime_type="application/pdf",
               attributes=[DocumentAttributeFilename(file_name=name)])
    return _Msg(id=10, chat_id=-100123, message="", document=doc)


def _audio_msg(name: str, duration: int = 3600) -> _Msg:
    doc = _Doc(size=20_000_000, mime_type="audio/mpeg",
               attributes=[DocumentAttributeFilename(file_name=name),
                           DocumentAttributeAudio(duration=duration, voice=False)])
    return _Msg(id=11, chat_id=-100123, message="", document=doc)


def test_to_candidate_pdf_cleans_title():
    c = tc._to_candidate(_pdf_msg("[@Mykitobbot] Lolazor.pdf"), "pdf", "@chan")
    assert c is not None
    assert c.title == "Lolazor"
    assert c.is_audio is False
    assert c.channel == "@chan"


def test_to_candidate_rejects_wrong_format():
    # An audio file must not surface in a PDF search and vice-versa.
    assert tc._to_candidate(_audio_msg("Otkan kunlar.mp3"), "pdf", "@c") is None
    assert tc._to_candidate(_pdf_msg("Lolazor.pdf"), "mp3", "@c") is None


def test_to_candidate_audio_duration():
    c = tc._to_candidate(_audio_msg("Otkan kunlar.mp3", duration=4242), "mp3", "@c")
    assert c is not None and c.is_audio is True
    assert c.duration == 4242
    assert c.duration_str == "1:10:42"


def test_size_mb():
    c = tc._to_candidate(_pdf_msg("Book.pdf", size=6_900_000), "pdf", "@c")
    assert round(c.size_mb, 1) == 6.6


def test_score_ranks_exact_higher():
    assert tc._score("Lolazor", "Lolazor") > tc._score("Lolazor", "Otkan kunlar")
