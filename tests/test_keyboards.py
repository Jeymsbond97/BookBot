"""Keyboards must build without error and emit string callback_data.

Regression guard: a raw InlineKeyboardButton was once given a CallbackData object
instead of its .pack()ed string, which crashed the handler at runtime (newer
aiogram/pydantic rejects non-string callback_data) — the user just saw a frozen
"searching…" message. These tests build every keyboard and assert all
callback_data values are strings.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from bookbot.bot import keyboards as k


def _all_callback_data(markup: InlineKeyboardMarkup) -> list:
    return [
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data is not None
    ]


def _assert_ok(markup: InlineKeyboardMarkup) -> None:
    assert isinstance(markup, InlineKeyboardMarkup)
    cbs = _all_callback_data(markup)
    assert cbs, "keyboard has no callback buttons"
    assert all(isinstance(c, str) for c in cbs), f"non-string callback_data: {cbs}"


def test_simple_keyboards_build():
    _assert_ok(k.format_keyboard())
    _assert_ok(k.main_menu_keyboard())
    _assert_ok(k.categories_keyboard([{"name_uz": "Psixologiya", "slug": "psychology"}]))
    _assert_ok(k.offer_keyboard("book-1"))
    _assert_ok(k.card_keyboard("db", "book-1"))


def test_results_keyboard_with_pagination():
    # page 1 with a next page → both ◀️ and ▶️ plus the back button.
    _assert_ok(k.results_keyboard(["a", "b", "c"], page=1, has_next=True))
    # first page, no next → no nav row, still a back button.
    _assert_ok(k.results_keyboard(["a"], page=0, has_next=False))


def test_candidates_keyboard_build():
    _assert_ok(k.candidates_keyboard("yt", 5))
    _assert_ok(k.candidates_keyboard("pdf", 3))
