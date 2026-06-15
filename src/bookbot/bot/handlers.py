"""aiogram handlers — Phase 1: format-first flow (/start, format & category menus).

Search, delivery and providers are added in later phases. The user's chosen format
is stored in the FSM context under the key ``fmt`` ('pdf' | 'mp3').
"""

from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import db
from . import texts
from .keyboards import (
    CategoryCB,
    FormatCB,
    MenuCB,
    categories_keyboard,
    format_keyboard,
    main_menu_keyboard,
)
from .states import Flow

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
    # Phase 6 will list books for the chosen category. For now, acknowledge.
    await query.answer(
        f"'{callback_data.slug}' — bu bo'lim keyingi bosqichda ishga tushadi.",
        show_alert=True,
    )


# ── Text query (search arrives in Phase 2) ───────────────────────────────────
@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    fmt = data.get("fmt")
    if not fmt:
        await message.answer(texts.NEED_FORMAT_FIRST, reply_markup=format_keyboard())
        return
    label = "PDF" if fmt == "pdf" else "Audio"
    await message.answer(
        f"🔎 <b>{label}</b> rejimida “{message.text.strip()}” qidirilmoqda…\n\n"
        "<i>(Qidiruv funksiyasi keyingi bosqichda — Phase 2 — ulanadi.)</i>",
        reply_markup=main_menu_keyboard(),
    )
