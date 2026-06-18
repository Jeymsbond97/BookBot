"""Unit tests for the Phase 9a card-cleaning helpers."""

from __future__ import annotations

from bookbot.bot import textclean


# ── clean_title ───────────────────────────────────────────────────────────────
def test_clean_title_strips_download_suffix():
    assert textclean.clean_title("Til ofatlari - yuklab olish!") == "Til Ofatlari"


def test_clean_title_titlecases_uzbek_digraphs():
    # O'/G' digraphs keep their apostrophe; only the first letter is upper-cased.
    assert textclean.clean_title("o'tkan kunlar") == "O'tkan Kunlar"
    assert textclean.clean_title("g'azzoliy hikoyalari") == "G'azzoliy Hikoyalari"


def test_clean_title_strips_pdf_and_brackets():
    assert textclean.clean_title("[PDF] Atomic Habits.pdf") == "Atomic Habits"
    assert textclean.clean_title("Sariq devni minib pdf") == "Sariq Devni Minib"


def test_clean_title_strips_channel_tags():
    # Telegram book channels watermark filenames with [@channel] tags.
    assert textclean.clean_title("[@Mykitobbot] Lolazor.pdf") == "Lolazor"
    assert textclean.clean_title("go'ro'g'li  [@kitob_pdf_yuklabot].pdf") == "Go'ro'g'li"
    assert textclean.clean_title("Oybegim mening [@kitoblar_pdf].PDF") == "Oybegim Mening"


def test_clean_title_empty():
    assert textclean.clean_title("") == ""
    assert textclean.clean_title(None) == ""


# ── descriptions ──────────────────────────────────────────────────────────────
def test_junk_description_detected():
    assert textclean.is_junk_description(
        "«Til ofatlari» - yuklab olish! O'zbek tilida kitoblar bo"
    )
    assert textclean.is_junk_description("PDF yuklab olish saytida")
    assert textclean.is_junk_description("")
    assert textclean.is_junk_description("juda qisqa")  # under 25 chars


def test_real_description_kept():
    real = "Imom G'azzoliyning til odobi haqidagi nasihatlari to'plami."
    assert not textclean.is_junk_description(real)
    assert textclean.clean_description(real) == real


def test_junk_description_cleaned_to_none():
    assert textclean.clean_description("O'zbek tilida kitoblar bo") is None


# ── covers ────────────────────────────────────────────────────────────────────
def test_placeholder_cover_detected():
    assert textclean.is_placeholder_cover(
        "https://pdfbox.uz/default-images/document-books-image.webp"
    )
    assert textclean.is_placeholder_cover("https://x.uz/img/no-image.png")
    assert textclean.is_placeholder_cover(None)
    assert textclean.clean_cover("https://x.uz/placeholder.jpg") is None


def test_real_cover_kept():
    url = "https://mykitob.uz/uploads/covers/otkan-kunlar.jpg"
    assert not textclean.is_placeholder_cover(url)
    assert textclean.clean_cover(url) == url
