"""All user-facing strings, in Uzbek, kept in one place for easy editing."""

from __future__ import annotations

# ── Buttons ───────────────────────────────────────────────────────────────────
BTN_PDF = "📕 PDF kitob"
BTN_AUDIO = "🎧 Audio kitob"
BTN_CATEGORIES = "📂 Kategoriyalar"
BTN_BACK = "⬅️ Orqaga"

# ── Messages ───────────────────────────────────────────────────────────────────
WELCOME = (
    "📚 <b>Assalomu alaykum!</b>\n\n"
    "Men kitob qidirib topib beradigan botman — <b>PDF</b> yoki <b>audio</b> ko'rinishida.\n\n"
    "Avval qanday format kerakligini tanlang 👇"
)

CHOOSE_FORMAT = "Qanday kitob kerak?"

FORMAT_CHOSEN_PDF = (
    "📕 <b>PDF rejimi</b> tanlandi.\n\n"
    "Endi kitob <b>nomini</b> yoki <b>muallifini</b> yozing — men qidiraman.\n"
    "Yoki <b>📂 Kategoriyalar</b> tugmasi orqali mavzu bo'yicha tanlang."
)

FORMAT_CHOSEN_AUDIO = (
    "🎧 <b>Audio rejimi</b> tanlandi.\n\n"
    "Endi kitob <b>nomini</b> yozing — men audiosini qidiraman.\n"
    "Yoki <b>📂 Kategoriyalar</b> tugmasi orqali mavzu bo'yicha tanlang."
)

CHOOSE_CATEGORY = "📂 Mavzuni tanlang:"

# Shown if the user types before choosing a format.
NEED_FORMAT_FIRST = "Avval format tanlang: 📕 PDF yoki 🎧 Audio."

HELP = (
    "ℹ️ <b>Qanday foydalanaman?</b>\n\n"
    "1️⃣ Format tanlang — 📕 PDF yoki 🎧 Audio\n"
    "2️⃣ Kitob nomini yozing yoki 📂 Kategoriyadan tanlang\n"
    "3️⃣ Chiqqan ro'yxatdan kerakligini bosing — men yuboraman\n\n"
    "Buyruqlar: /start — boshidan, /help — yordam"
)
