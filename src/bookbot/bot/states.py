"""FSM states for the bot conversation."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Flow(StatesGroup):
    """Main user flow.

    We mostly keep lightweight data in the FSM *context* (chosen format, last
    query, page) rather than relying on distinct states, but `choosing_format`
    and `searching` make the flow explicit and testable.
    """

    choosing_format = State()
    searching = State()


class AdminUpload(StatesGroup):
    """Admin PDF upload wizard (Phase 7): admin sends a PDF, then the bot asks
    for title → author → category → language before storing it in the catalog."""

    title = State()
    author = State()
    category = State()
    language = State()
