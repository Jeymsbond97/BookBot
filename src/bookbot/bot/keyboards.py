"""Inline keyboard builders and typed callback data for the bot."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import texts


# ── Callback data ─────────────────────────────────────────────────────────────
class FormatCB(CallbackData, prefix="fmt"):
    """Choosing the preferred format. value = 'pdf' | 'mp3'."""

    value: str


class MenuCB(CallbackData, prefix="menu"):
    """Top-level menu navigation. action = 'categories' | 'change_format'."""

    action: str


class CategoryCB(CallbackData, prefix="cat"):
    """Picking a category to browse. slug = category slug."""

    slug: str


# Reused from Phase 2 onward (search results / pagination / file download).
class BookCB(CallbackData, prefix="bk"):
    book_id: str


class FileCB(CallbackData, prefix="fl"):
    file_id: str


class PageCB(CallbackData, prefix="pg"):
    page: int


# ── Builders ──────────────────────────────────────────────────────────────────
def format_keyboard() -> InlineKeyboardMarkup:
    """The first prompt: choose PDF or Audio."""
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_PDF, callback_data=FormatCB(value="pdf"))
    kb.button(text=texts.BTN_AUDIO, callback_data=FormatCB(value="mp3"))
    kb.adjust(2)
    return kb.as_markup()


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Shown after a format is chosen: browse categories or switch format."""
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_CATEGORIES, callback_data=MenuCB(action="categories"))
    kb.button(text="🔄 Formatni o'zgartirish", callback_data=MenuCB(action="change_format"))
    kb.adjust(1)
    return kb.as_markup()


def categories_keyboard(categories: list[dict]) -> InlineKeyboardMarkup:
    """One button per category (two per row) + a back button."""
    kb = InlineKeyboardBuilder()
    for c in categories:
        kb.button(text=c["name_uz"], callback_data=CategoryCB(slug=c["slug"]))
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text=texts.BTN_BACK, callback_data=MenuCB(action="change_format")))
    return kb.as_markup()
