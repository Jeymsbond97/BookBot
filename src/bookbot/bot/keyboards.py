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


class PageCB(CallbackData, prefix="pg"):
    page: int


class OfferCB(CallbackData, prefix="ofr"):
    """Accept a cross-format offer ("audio yo'q, PDF bor — yuboraymi?")."""

    book_id: str


class CardCB(CallbackData, prefix="card"):
    """Open a detail card for a picked result/variant.

    kind = 'db' (ref = book_id) | 'pdf' | 'yt' (ref = candidate index in FSM).
    """

    kind: str
    ref: str


class SendCB(CallbackData, prefix="snd"):
    """Confirm sending from a detail card (same kind/ref as CardCB)."""

    kind: str
    ref: str


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
    kb.row(InlineKeyboardButton(text=texts.BTN_BACK,
                                callback_data=MenuCB(action="change_format").pack()))
    return kb.as_markup()


def results_keyboard(book_ids: list[str], page: int, has_next: bool) -> InlineKeyboardMarkup:
    """Numbered result buttons (1, 2, 3 …) plus a ◀ / ▶ pagination row.

    Button labels are numbered relative to the absolute position across pages, so
    page 1 starts at 6 when PAGE_SIZE is 5. Each number maps to a book via BookCB.
    """
    from .search import PAGE_SIZE  # local import avoids a circular import at module load

    kb = InlineKeyboardBuilder()
    start = page * PAGE_SIZE
    for i, book_id in enumerate(book_ids):
        kb.button(text=str(start + i + 1), callback_data=CardCB(kind="db", ref=book_id))
    kb.adjust(5)

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=PageCB(page=page - 1).pack()))
    if has_next:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=PageCB(page=page + 1).pack()))
    if nav:
        kb.row(*nav)

    kb.row(InlineKeyboardButton(text=texts.BTN_BACK,
                                callback_data=MenuCB(action="back_to_menu").pack()))
    return kb.as_markup()


def offer_keyboard(book_id: str) -> InlineKeyboardMarkup:
    """Accept / decline buttons for a cross-format offer (Phase 3)."""
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_YES_SEND, callback_data=OfferCB(book_id=book_id))
    kb.button(text=texts.BTN_NO, callback_data=MenuCB(action="back_to_menu"))
    kb.adjust(2)
    return kb.as_markup()


def candidates_keyboard(kind: str, count: int) -> InlineKeyboardMarkup:
    """Numbered buttons (1..count) for external variants (PDF/YouTube)."""
    kb = InlineKeyboardBuilder()
    for i in range(count):
        kb.button(text=str(i + 1), callback_data=CardCB(kind=kind, ref=str(i)))
    kb.adjust(5)
    kb.row(InlineKeyboardButton(text=texts.BTN_BACK,
                                callback_data=MenuCB(action="back_to_menu").pack()))
    return kb.as_markup()


def card_keyboard(kind: str, ref: str) -> InlineKeyboardMarkup:
    """A detail card's actions: send the file, or go back to the menu."""
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_SEND_FILE, callback_data=SendCB(kind=kind, ref=ref))
    kb.button(text=texts.BTN_BACK, callback_data=MenuCB(action="back_to_menu"))
    kb.adjust(1)
    return kb.as_markup()
