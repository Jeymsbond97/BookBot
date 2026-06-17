"""All user-facing strings, in Uzbek, kept in one place for easy editing."""

from __future__ import annotations

# ── Buttons ───────────────────────────────────────────────────────────────────
BTN_PDF = "📕 PDF kitob"
BTN_AUDIO = "🎧 Audio kitob"
BTN_CATEGORIES = "📂 Kategoriyalar"
BTN_BACK = "⬅️ Orqaga"
BTN_YES_SEND = "✅ Ha, yubor"
BTN_NO = "❌ Yo'q"
BTN_SEND_FILE = "📥 Yuborish"
BTN_LANGUAGE = "🌐 Til"

# ── Language filter (Phase 6) ──────────────────────────────────────────────────
LANG_UZ = "🇺🇿 O'zbekcha"
LANG_EN = "🇬🇧 Inglizcha"
LANG_ALL = "🌐 Barchasi"

_LANG_SHORT = {"uz": "O'zbekcha", "en": "Inglizcha"}


def lang_button(lang: str | None) -> str:
    """Main-menu language button label, showing the active filter."""
    return f"🌐 Til: {_LANG_SHORT.get(lang or '', 'Barchasi')}"


LANGUAGE_PROMPT = "🌐 Qaysi tildagi kitoblar ko'rsatilsin?"


def language_set(lang: str | None) -> str:
    return f"🌐 Til tanlandi: <b>{_LANG_SHORT.get(lang or '', 'Barchasi')}</b>"

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


def browse_header(name: str, page: int) -> str:
    """Header above a category's book listing."""
    head = f"📂 <b>{name}</b> bo'limidagi kitoblar:"
    if page > 0:
        head += f"  <i>(sahifa {page + 1})</i>"
    return head


def category_empty(name: str) -> str:
    return (
        f"📂 <b>{name}</b> bo'limida hozircha kitob yo'q.\n\n"
        "Kitob nomini yozib qidirib ko'ring — topsam, shu bo'limga qo'shib qo'yaman."
    )

# Shown if the user types before choosing a format.
NEED_FORMAT_FIRST = "Avval format tanlang: 📕 PDF yoki 🎧 Audio."

HELP = (
    "ℹ️ <b>Qanday foydalanaman?</b>\n\n"
    "1️⃣ Format tanlang — 📕 PDF yoki 🎧 Audio\n"
    "2️⃣ Kitob nomini yozing yoki 📂 Kategoriyadan tanlang\n"
    "3️⃣ Chiqqan ro'yxatdan kerakligini bosing — men yuboraman\n\n"
    "Buyruqlar: /start — boshidan, /help — yordam"
)

# ── Search ──────────────────────────────────────────────────────────────────
SEARCHING = "🔎 Qidirilmoqda…"

SEARCHING_WEB = "🌐 Bazada yo'q ekan — internetdan qidiryapman… (biroz kuting)"

NOT_FOUND = (
    "🔍 <b>Topilmadi.</b>\n\n"
    "Bazada ham, internetda ham topa olmadim. Boshqacha yozib ko'ring yoki "
    "kitob nomini to'liqroq kiriting."
)

# Internet-fetched PDF served to a user who asked for audio (cross-format).
def web_pdf_offer(title: str) -> str:
    return (
        "🎧 Audio topilmadi, lekin internetdan <b>📕 PDF</b> topdim.\n\n"
        f"«{title}» — yuboraymi?"
    )


def results_header(query: str, page: int) -> str:
    """Header line shown above the numbered results list."""
    head = f"🔎 “{query}” bo'yicha natijalar:"
    if page > 0:
        head += f"  <i>(sahifa {page + 1})</i>"
    return head


def result_line(number: int, label: str) -> str:
    return f"<b>{number}.</b> {label}"


RESULTS_PROMPT = "Kerakli kitob raqamini bosing 👇"


# ── Cross-format fallback (Phase 3) ──────────────────────────────────────────
FMT_LABEL = {"pdf": "📕 PDF", "mp3": "🎧 Audio"}


def cross_format_offer(title: str, chosen: str, have: str) -> str:
    """Single-hit offer: chosen format missing but the other exists."""
    return (
        f"{FMT_LABEL.get(chosen, chosen)} topilmadi, "
        f"lekin <b>{FMT_LABEL.get(have, have)}</b> bor.\n\n"
        f"«{title}» — yuboraymi?"
    )


def cross_format_list_note(chosen: str) -> str:
    """Header for a multi-hit list found only in the other format(s)."""
    return (
        f"{FMT_LABEL.get(chosen, chosen)} topilmadi, "
        "lekin quyidagilar boshqa formatda bor 👇"
    )


SENDING = "📤 Yuborilmoqda…"

DELIVER_FAILED = "⚠️ Kechirasiz, faylni yuborib bo'lmadi. Keyinroq urinib ko'ring."

FILE_MISSING = "⚠️ Bu kitobning tanlangan formatdagi fayli topilmadi."


# ── Variants (internet candidates) ───────────────────────────────────────────
SEARCHING_WEB_PDF = "🌐 Bazada yo'q — internetdan PDF variantlarini qidiryapman…"
SEARCHING_YOUTUBE = "🎧 Bazada yo'q — YouTube'dan audio variantlarini qidiryapman…"


def pdf_variants_header(query: str) -> str:
    return (
        f"🌐 “{query}” bo'yicha internetdan topildi.\n"
        "Quyidagilardan birini tanlang (manbasi ko'rsatilgan) 👇"
    )


def youtube_variants_header(query: str) -> str:
    return (
        f"🎧 “{query}” bo'yicha YouTube'da topildi.\n"
        "Birini tanlang — <i>yuklab olish biroz vaqt oladi (uzun audio bo'lsa bir necha daqiqa)</i> 👇"
    )


def pdf_variant_line(n: int, title: str, site: str) -> str:
    return f"<b>{n}.</b> {title}\n     <i>{site}</i>"


def youtube_variant_line(n: int, title: str, duration: str, uploader: str | None) -> str:
    who = f" · {uploader}" if uploader else ""
    return f"<b>{n}.</b> {title}\n     <i>⏱ {duration}{who}</i>"


# ── Download / delivery progress ──────────────────────────────────────────────
DOWNLOADING_PDF = "📥 Yuklab olinmoqda va tekshirilmoqda…"
DOWNLOADING_AUDIO = (
    "📥 Audio yuklanyapti va siqilyapti… bu biroz vaqt oladi (1–3 daqiqa), kuting ⏳"
)
DOWNLOAD_FAILED = "⚠️ Yuklab bo'lmadi — bu variant ishlamadi. Boshqasini tanlab ko'ring."
ERROR_GENERIC = "⚠️ Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring yoki /start bosing."
AUDIO_PARTS_NOTE = "📚 Audio katta — qismlarga bo'lib yuboraman:"
NO_VARIANTS = "🔍 Internetdan ham hech narsa topilmadi. Boshqacha yozib ko'ring."


# ── Admin upload (Phase 7) ─────────────────────────────────────────────────────
ADMIN_ONLY = "⛔️ Bu amal faqat adminlar uchun."
ADMIN_NOT_PDF = "⚠️ Faqat <b>PDF</b> fayl yuboring."
ADMIN_HELP = (
    "🛠 <b>Admin — kitob qo'shish</b>\n\n"
    "Menga shunchaki <b>PDF fayl</b> yuboring — keyin nomi, muallifi, mavzusi va "
    "tilini so'rayman, so'ng katalogga saqlayman.\n\n"
    "Bekor qilish uchun: /cancel"
)
ADMIN_SKIP_HINT = "O'tkazib yuborish uchun «-» belgisini yuboring."


def admin_ask_title(suggested: str) -> str:
    return (
        "📕 PDF qabul qilindi.\n\n"
        f"<b>Kitob nomi?</b>\nTaklif: <code>{suggested}</code>\n"
        "Shuni ishlatish uchun «-» yuboring, yoki to'g'ri nomni yozing."
    )


ADMIN_ASK_AUTHOR = "✍️ <b>Muallifi?</b>\n" + ADMIN_SKIP_HINT
ADMIN_ASK_CATEGORY = "📂 <b>Mavzusi?</b> Tanlang 👇"
ADMIN_ASK_LANGUAGE = "🌐 <b>Tili?</b>"
ADMIN_SAVING = "💾 Saqlanyapti…"
ADMIN_CANCELLED = "❌ Bekor qilindi."


def admin_saved(title: str, category: str | None) -> str:
    cat = f"\n📂 Mavzu: {category}" if category else ""
    return f"✅ Saqlandi!\n\n📕 <b>{title}</b>{cat}\n\nEndi foydalanuvchilar uni topadi."
