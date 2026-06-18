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


def test_part_no_extraction():
    assert tc._part_no("10-Suhbat Amir Temur Vafoti.m4a") == 10
    assert tc._part_no("9-Suhbat Amir Temur. Izmir") == 9
    assert tc._part_no("04.Amir Temur Saltanati") == 4
    assert tc._part_no("Amir Temur 2-qism") == 2
    assert tc._part_no("3-bo'lim") == 3
    assert tc._part_no("Amir Temur va Islom") == 0  # no part number


def test_part_ordering_is_ascending():
    # Multi-part titles in scrambled order should sort 1,2,3 … by part number.
    titles = ["10-Suhbat Amir Temur", "9-Suhbat Amir Temur", "04.Amir Temur", "2-Suhbat Amir Temur"]
    ordered = sorted(titles, key=lambda t: tc._part_no(t) or 100_000)
    assert [tc._part_no(t) for t in ordered] == [2, 4, 9, 10]


def test_rank_rewards_closeness():
    # The closest (shortest exact) title ranks above one padded with extra words.
    assert tc._rank("Amir Temur", "Amir Temur") > tc._rank(
        "Amir Temur", "Amir Temur Strategiyasi va uning armiyasidagi askariy hayot"
    )
