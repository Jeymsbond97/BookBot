# 📚 BookBot — Telegram Book Search Bot (PDF + Audio)

A Telegram bot that finds **books** for users — as **PDF** or as **audio** — first from its own
database, and if not found, **from the internet** (Google for PDFs, YouTube for audio). Found PDFs
are saved back to the database so the next user gets them instantly. Built for an **Uzbek-first**
audience, with English as a secondary language.

> 🇺🇿 **Bu README — butun loyihaning to'liq "chizmasi" (blueprint).** Uni o'qib chiqqan odam
> loyiha nima qilishini, qanday ishlashini va qanday qurilishini boshidan oxirigacha tushunadi.
> Pastdagi **Build Roadmap** bo'limi — biz birma-bir bajaradigan reja.

---

## Table of Contents
1. [Vision — what makes this bot different](#1-vision)
2. [User journey](#2-user-journey)
3. [High-level architecture](#3-high-level-architecture)
4. [Request lifecycle (the core algorithm)](#4-request-lifecycle)
5. [Data model](#5-data-model)
6. [Components](#6-components)
7. [External sources & media pipeline](#7-external-sources--media-pipeline)
8. [Audio & Telegram file-size handling](#8-audio--telegram-file-size-handling)
9. [Categories & language](#9-categories--language)
10. [Admin features](#10-admin-features)
11. [Caching strategy](#11-caching-strategy)
12. [Tech stack & what to install](#12-tech-stack--what-to-install)
13. [Project structure](#13-project-structure)
14. [Setup](#14-setup)
15. [Environment variables](#15-environment-variables)
16. [Build roadmap (step by step)](#16-build-roadmap)
17. [Testing & verification](#17-testing--verification)
18. [Legal & responsible use](#18-legal--responsible-use)

---

## 1. Vision

Most book bots only return what is already in their storage. **BookBot is different:**

- **Database-first, internet-second.** It searches its own catalog first; if the book isn't there,
  it fetches it from the internet live, returns it to the user, and **caches it** (PDF) so it never
  has to fetch it again.
- **Two formats, one smart flow.** The user first chooses **PDF** or **Audio**. If the chosen format
  doesn't exist for a book but the *other* format does, the bot offers it instead — so the user is
  never told "not found" when something useful is actually available.
- **Fuzzy / partial search.** If the user misremembers the exact title, the bot shows similarly-named
  books in a paginated list (1, 2, 3 …).
- **Browse by category.** Even when the user *doesn't know any title*, they can ask for a topic —
  **Psychology, Self-development, Fiction, History, Religion**, etc. — and get curated books of that
  kind. (This is the headline feature missing from other bots.)
- **Uzbek-first.** The primary catalog is **Uzbek-language** books; English books are served on request.

---

## 2. User Journey

```
/start
  │
  ▼
"Salom! Qanday kitob kerak?"   ← bot asks format first
  ├─ [📕 PDF]      ┐
  ├─ [🎧 Audio]    ├─ user picks ONE → stored as the session's preferred format
  └─ [📂 Kategoriya] ┘  (or browse by category instead of searching)
  │
  ▼
User types a book name  ──►  SEARCH
  │
  ├─ Exact match in DB                → send that book directly (in chosen format)
  ├─ Several similar names in DB       → paginated list  ◀ 1 2 3 ▶  → user taps one
  ├─ Not in DB                         → fetch from internet (Google PDF / YouTube audio)
  │                                        → deliver → (PDF) save to DB for next time
  └─ Chosen format missing, other exists → "Audio yo'q, lekin PDF bor 📕 — yuboraymi?"
  │
  ▼
User taps a result → bot sends the file (PDF document / audio)
```

**Category browse path:**

```
[📂 Kategoriya] → choose: Psixologiya | Shaxsiy rivojlanish | Badiiy | Tarix | Diniy | ...
              → paginated list of books in that category (filtered by chosen format + language)
              → tap a book → receive file
```

> 🇺🇿 **Asosiy g'oya:** format avval tanlanadi (PDF yoki Audio). Keyin user kitob nomini yozadi yoki
> kategoriya tanlaydi. Aniq kitob bo'lsa — o'zini beradi; o'xshashlari ko'p bo'lsa — 1, 2, 3 ko'rinishida
> (pagination). Bazada yo'q bo'lsa — internetdan olib keladi. Tanlangan formatda bo'lmasa, ikkinchi
> format bor bo'lsa — uni taklif qiladi (masalan "audio yo'q, PDF bor").

---

## 3. High-level Architecture

```
                         ┌──────────────────────────────────────────────┐
                         │                 Telegram User                 │
                         └───────────────────────┬──────────────────────┘
                                                 │ (long polling)
                                                 ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│                              BookBot service (Python)                               │
│                                                                                     │
│   ┌──────────────┐      ┌────────────────────┐      ┌──────────────────────────┐    │
│   │ aiogram Bot  │ ───► │  Search Orchestrator│ ───► │  Source Providers        │    │
│   │ (handlers,   │      │  DB-first → fallback│      │  • PDF: Google CSE + dl  │    │
│   │  FSM, kbds)  │ ◄─── │  ranking, cross-fmt │ ◄─── │  • Audio: yt-dlp+ffmpeg  │    │
│   └──────┬───────┘      └─────────┬──────────┘      │  • Admin uploads         │    │
│          │                        │                  └──────────────────────────┘    │
│          │                        ▼                                                  │
│          │                ┌───────────────┐                                          │
│          │                │  Catalog API  │  (books, files, categories CRUD)         │
│          │                └──────┬────────┘                                          │
└──────────┼───────────────────────┼──────────────────────────────────────────────────┘
           │                       │
           ▼                       ▼
   ┌────────────────┐      ┌───────────────────────────────────────────┐
   │ Telegram CDN   │      │                  Supabase                  │
   │ (file_id cache,│      │  • Postgres: catalog + full-text/fuzzy idx │
   │  no storage)   │      │  • Storage:  PDF files only                │
   └────────────────┘      └───────────────────────────────────────────┘
```

Three logical layers:
1. **Bot layer** — conversation, format selection, category browse, pagination, file delivery.
2. **Orchestration layer** — decides DB vs internet, ranks matches, handles cross-format fallback.
3. **Source providers** — pluggable adapters that fetch from external sources (web PDF, YouTube audio,
   admin upload). New sources can be added without touching the bot.

---

## 4. Request Lifecycle

The heart of the bot is the **search orchestrator**. Pseudocode for a text query:

```python
def handle_query(text, fmt, language):          # fmt = "pdf" | "mp3"
    # 1) DB FIRST
    exact = catalog.find_exact(text, language)
    if exact:
        return deliver_or_fallback(exact, fmt)   # send chosen fmt, else offer the other

    similar = catalog.search_fuzzy(text, language, page=0)
    if similar:                                  # show paginated list, user taps one
        return show_results(similar, fmt)

    # 2) INTERNET SECOND (only when DB has nothing)
    if fmt == "pdf":
        pdf = providers.pdf_web.fetch(text, language)   # Google CSE → download → validate
        if pdf:
            book = catalog.save_pdf(pdf)                # ⇦ cached for the next user
            return deliver(book, "pdf")
        # PDF not found online → try audio as fallback
        audio = providers.youtube_audio.fetch(text)
        if audio: return deliver_audio(audio)           # do NOT store the file (see §11)

    else:  # fmt == "mp3"
        audio = providers.youtube_audio.fetch(text)
        if audio: return deliver_audio(audio)
        # audio not found → try PDF as fallback
        pdf = providers.pdf_web.fetch(text, language)
        if pdf:
            book = catalog.save_pdf(pdf)
            return deliver(book, "pdf")

    return "🔍 Topilmadi. Boshqacha yozib ko'ring."
```

**Key rules:**
- **DB is always checked first** (fast + free + already validated).
- **Internet fetch only happens on a miss**, and **PDFs are saved back** so a second user with the
  same request is served from the DB instantly.
- **Cross-format fallback** runs in both directions (audio↔pdf) so the user never leaves empty-handed
  when *some* format exists.
- **Audio is never stored as a file** — only an optional Telegram `file_id` reference is kept (see §11).

> 🇺🇿 **Binafsha misoli:** user "Binafsha" deb yozadi, PDF yo'q (publicda yo'q), lekin YouTube'da audiosi
> bor. User PDF tanlagan bo'lsa ham — bot PDF topa olmaydi, keyin audio fallback ishga tushadi, YouTube'dan
> audiosini olib kelib beradi. Aksincha ham ishlaydi: audio tanlangan, audio yo'q, lekin PDF bor — PDF beriladi.

---

## 5. Data Model

Supabase Postgres. **PDF files** live in Supabase Storage; **audio files are not stored** (only metadata
+ an optional Telegram `file_id`).

```sql
-- Catalog entry (one row per book/edition)
books (
  id           uuid pk,
  title        text not null,
  author       text,
  language     text default 'uz',          -- 'uz' primary, 'en', ...
  description  text,
  cover_url    text,
  source       text,                        -- 'admin' | 'web' | 'youtube' | 'gutenberg' ...
  source_ref   text,                        -- origin id/url (dedup + re-fetch)
  created_at   timestamptz default now(),
  search_tsv   tsvector generated …,        -- full-text over title+author
  unique (title, author, language)
)

-- Files attached to a book. PDF → stored in bucket. MP3 → NOT stored; youtube_id + cached file_id only.
book_files (
  id               uuid pk,
  book_id          uuid fk → books,
  format           text,                     -- 'pdf' | 'mp3'
  storage_path     text,                     -- set for PDF (Supabase Storage); NULL for audio
  youtube_id       text,                     -- set for audio (so we can re-fetch / compress)
  size_bytes       bigint,
  telegram_file_id text,                      -- cached after first send (instant, no storage)
  created_at       timestamptz default now(),
  unique (book_id, format)
)

-- Topic taxonomy for "browse by category"
categories (
  id    serial pk,
  slug  text unique,                          -- 'psychology', 'self-dev', 'fiction', 'history', 'religion'
  name_uz text,                               -- 'Psixologiya', 'Shaxsiy rivojlanish', ...
  name_en text
)
book_categories ( book_id uuid fk, category_id int fk, primary key(book_id, category_id) )
```

Indexes: GIN on `search_tsv` (full-text), `pg_trgm` GIN on `title`/`author` (fuzzy), btree on
`book_categories(category_id)`. A Postgres function `search_books(q, lang, fmt, lim, off)` does the
ranked search and is called from the bot via RPC.

---

## 6. Components

| Component | Responsibility |
|---|---|
| **Bot handlers** | `/start`, format selection, text search, category browse, pagination, delivery, admin upload. Uses aiogram FSM to remember the user's chosen format & current query/page. |
| **Search orchestrator** | Implements §4: DB-first lookup, fuzzy ranking, internet fallback, cross-format fallback. The only place that knows the "where to look" policy. |
| **Catalog API** | CRUD over `books` / `book_files` / `categories`. Save fetched PDFs, tag categories/language, dedup. |
| **Source providers** | Pluggable adapters with a common interface: `PdfWebProvider`, `YoutubeAudioProvider`, `AdminUploadProvider`. Each returns a normalized result the catalog can store/deliver. |
| **Storage** | Supabase Storage wrapper for PDF upload/download. |
| **Media pipeline** | `yt-dlp` (search + download audio) + `ffmpeg` (compress/split). |
| **Admin module** | Admin-only flows: upload a PDF, set title/author/category/language. |

**Provider interface (so new sources are easy to add):**

```python
class SourceProvider(Protocol):
    name: str
    fmt: str  # "pdf" | "mp3"
    def fetch(self, title: str, language: str) -> FetchResult | None: ...
    # FetchResult = { title, author, bytes|stream, ext, source_ref, size_bytes }
```

---

## 7. External Sources & Media Pipeline

### 7a. PDF from the web — DuckDuckGo (keyless)
- Use **DuckDuckGo search** via the **`ddgs`** Python library — **no API key required**, searches the
  **whole web**. (Google's Programmable Search Engine dropped whole-web search in 2026, so it is no
  longer suitable for this.)
- Query pattern: `"<title>" filetype:pdf` (for `uz`, add Uzbek hints / prioritize Uzbek book sites).
- Take the top results, download the first candidate, and **validate** it: `Content-Type: application/pdf`
  **and** the file starts with the `%PDF` magic bytes, and size ≤ `MAX_FILE_MB`.
- On success → upload to Supabase Storage → index in `books`/`book_files` → deliver.

> 🇺🇿 **PDF qidirish:** Butun internetdan **DuckDuckGo** orqali qidiramiz (`ddgs` kutubxonasi) — **kalit
> kerak emas**. `kitob nomi filetype:pdf` deb qidiradi, birinchi haqiqiy PDF faylni yuklab oladi,
> tekshiradi (rostdan PDF ekanini), keyin Supabase'ga saqlaydi. (Google PSE 2026-da butun internetni
> qidirishni o'chirgani uchun undan voz kechdik.)

### 7b. Audio from YouTube — yt-dlp + ffmpeg
This is what you asked about ("codeda nimadir yozish/o'rnatish kerakmi?"). **Yes — two things:**

1. **Install `yt-dlp`** (a Python library) — it can *search* YouTube and *download* the audio track.
2. **Install `ffmpeg`** (a system program) — it converts/compresses the audio to a small MP3.

Flow:
```
title → yt-dlp "ytsearch5:<title> audiokitob"     # search YouTube, get 5 candidates
      → pick best (title similarity + sane duration)
      → yt-dlp download bestaudio
      → ffmpeg → mono, low bitrate (e.g. 48 kbps) MP3   # keeps the file SMALL
      → send to user as audio
      → cache telegram file_id (+ youtube_id) so next time = instant, no re-download
```

> 🇺🇿 **YouTube'dan audio olish — nima qilish kerak:**
> 1. `pip install yt-dlp` — bu YouTube'dan qidirib, audiosini yuklab beradi.
> 2. `ffmpeg`ni o'rnatish kerak (Mac'da `brew install ffmpeg`) — bu audioni **eng kichik hajmga** siqadi
>    (mono + past bitrate, masalan 48 kbps). Shunda "eng kichik megabaytda" bo'ladi.
> 3. Kod YouTube'da "Binafsha audiokitob" deb qidiradi, eng mosini topadi, audiosini yuklab, siqib, userga
>    yuboradi. Faylni **bazaga saqlamaymiz** — faqat Telegram `file_id`sini eslab qolamiz (§11).

---

## 8. Audio & Telegram file-size handling

Telegram's **Bot API caps a bot's file send at 50 MB.** Audiobooks can be long, so:

- **Compress hard:** mono + 48 kbps MP3. (~1 hour ≈ ~21 MB; many audiobooks fit.)
- **If still > 50 MB**, choose one (configurable):
  - **Split into parts** with ffmpeg (Part 1/3, 2/3, …) and send sequentially, **or**
  - Run a **self-hosted Telegram Bot API server**, which raises the limit to **2000 MB** (best UX for
    long audiobooks; documented as an optional deployment in the roadmap).

> 🇺🇿 **Muhim:** Telegram bot orqali maksimum 50 MB fayl yuborish mumkin. Shuning uchun audioni qattiq
> siqamiz. Agar baribir katta bo'lsa — qismlarga bo'lib yuboramiz (1-qism, 2-qism…) yoki o'zimizning
> Bot API serverimizni o'rnatib limitni 2 GB ga ko'taramiz. Bu tanlovni keyin birga hal qilamiz.

---

## 9. Categories & Language

- **Categories** (`categories` + `book_categories`): Psixologiya, Shaxsiy rivojlanish, Badiiy, Tarix,
  Diniy, … User taps **📂 Kategoriya** → picks one → gets a paginated list filtered by the chosen
  **format** and **language**.
- **Language**: default **`uz`**. The catalog prioritizes Uzbek books. If the user asks in/for English
  (or toggles language), results switch to `en`. Internet fetch respects the active language (e.g. Uzbek
  PDF search adds Uzbek hints; English uses English sources).
- Admin-uploaded books are tagged with category + language at upload time. Web/YouTube-fetched books get
  a best-effort category (and can be re-tagged by admin later).

---

## 10. Admin features

Only the configured `ADMIN_IDS` (your Telegram user id) can:
- **Upload a PDF**: send a document to the bot → bot asks for **title, author, category, language** →
  stores it in Storage + catalog. This is how you add **newly released Uzbek books** that aren't online.
- **Re-tag / delete** catalog entries, set categories/language.
- (Future) view simple stats (most-requested titles, fetch failures).

---

## 11. Caching strategy

| Format | Stored where | Re-fetch? |
|---|---|---|
| **PDF** | Supabase **Storage** (the actual file) + `telegram_file_id` cached after first send | Never — served from DB/Storage forever |
| **Audio (MP3)** | **No file stored.** Only `youtube_id` + (optional) `telegram_file_id` in the DB | If no `file_id`, re-fetch from YouTube; with `file_id`, re-send instantly |

> 🇺🇿 **Sizning talabingiz:** audioni bazaga saqlamaymiz (hajmi katta, xotira tez to'ladi) — to'g'ri.
> Lekin bitta kichik yaxshilanish taklif qilaman: Telegram bir marta yuborilgan faylni o'zida saqlaydi va
> bizga qisqa `file_id` (atigi ~80 ta belgi matn) beradi. Shu `file_id`ni saqlasak — **fayl saqlanmaydi**
> (xotira ishlatmaydi), lekin keyingi safar YouTube'dan **qayta yuklamasdan** bir zumda yuboramiz. PDF esa
> to'liq saqlanadi. Bu sizning qoidangizni buzmaydi, faqat tezroq qiladi. Xohlasangiz audio uchun ham buni
> o'chirib, har safar YouTube'dan olib kelaveramiz.

---

## 12. Tech stack & what to install

**Python deps:** `aiogram` (bot), `supabase` (DB+Storage), `pydantic-settings` (config),
`httpx` (HTTP), `ddgs` (DuckDuckGo PDF search, keyless), `yt-dlp` (YouTube), `rapidfuzz` (ranking).

**System deps:** `ffmpeg` (audio compress/split).

**Cloud / keys you need:**
- Telegram bot token (created ✅)
- Supabase project (URL + service-role key ✅)
- **No key needed** for PDF web search (DuckDuckGo) or YouTube audio (yt-dlp).

```bash
# Python
pip install -e ".[dev]"        # installs aiogram, supabase, yt-dlp, etc.
# System (macOS)
brew install ffmpeg
```

---

## 13. Project structure (target)

```
BookBot/
├── README.md  LICENSE  .env.example  .gitignore  pyproject.toml
├── Dockerfile  docker-compose.yml
├── supabase/migrations/0001_init.sql        # books, book_files, categories, search_books()
├── src/bookbot/
│   ├── config.py            # env (tokens, keys, ADMIN_IDS, bitrate, limits)
│   ├── db.py                # Supabase client + catalog/storage helpers
│   ├── models.py            # Book, BookFile, SearchResult, FetchResult
│   ├── catalog.py           # save/dedup/tag books, category & language filters
│   ├── search/
│   │   ├── orchestrator.py  # DB-first → internet fallback → cross-format (the §4 algorithm)
│   │   └── ranking.py       # fuzzy ranking (rapidfuzz)
│   ├── providers/
│   │   ├── base.py          # SourceProvider protocol + FetchResult
│   │   ├── pdf_web.py       # Google CSE + download + %PDF validation
│   │   ├── youtube_audio.py # yt-dlp search/download + ffmpeg compress/split
│   │   └── admin_upload.py  # admin PDF upload flow
│   └── bot/
│       ├── main.py          # Dispatcher + long polling
│       ├── states.py        # FSM states (ChooseFormat, Searching, AdminUpload…)
│       ├── texts.py         # all Uzbek user-facing strings in one place
│       ├── keyboards.py     # format / results / pagination / category / format inline kbds
│       └── handlers/        # start.py search.py browse.py delivery.py admin.py
└── tests/                   # ranking, orchestrator (mocked providers), provider parsers
```

---

## 14. Setup

1. **Clone & install**
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev]"
   brew install ffmpeg
   ```
2. **Supabase**: create the project (in progress ✅) → open **SQL Editor** → run
   `supabase/migrations/0001_init.sql`.
3. **Config**: `cp .env.example .env` and fill in the values (next section).
4. **Run**: `python -m bookbot.bot.main` → open your bot in Telegram.

---

## 15. Environment variables

```bash
TELEGRAM_BOT_TOKEN=...        # from @BotFather
ADMIN_IDS=123456789           # your Telegram numeric id(s), comma-separated

SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=...      # service-role key (Settings → API)
SUPABASE_BUCKET=books

# PDF web search uses DuckDuckGo (ddgs) — no API key needed.

DEFAULT_LANGUAGE=uz           # primary language
AUDIO_BITRATE_KBPS=48         # audio compression target (smaller = lighter files)
MAX_FILE_MB=50                # Telegram bot send cap (raise if self-hosting Bot API)
CACHE_AUDIO_FILE_ID=true      # cache telegram file_id for audio (no file stored)
```

---

## 16. Build Roadmap

We build in phases — each phase is independently testable. 🇺🇿 *Biz shu tartibda birma-bir ishlaymiz.*

- **Phase 0 — Foundation.** Project scaffold, config (incl. `ADMIN_IDS`, Google keys, bitrate), Supabase
  migration with `books`/`book_files`/`categories` + `search_books()` RPC. *(Most of this scaffold already exists from v1 and will be extended.)*
- **Phase 1 — Bot skeleton & format-first flow.** `/start` → choose PDF/Audio (FSM), texts in Uzbek,
  keyboards. No search yet.
- **Phase 2 — DB search + pagination.** Text query → `search_books()` → exact match shortcut + paginated
  fuzzy list (rapidfuzz ranking) → deliver from Storage (PDF) with file_id caching.
- **Phase 3 — Cross-format fallback.** If chosen format missing but other exists → offer it.
- **Phase 4 — PDF web provider.** DuckDuckGo (`ddgs`) `filetype:pdf` search → download → `%PDF`
  validation → save to catalog → deliver. Now DB-miss PDFs are fetched & cached. No API key.
- **Phase 5 — YouTube audio provider.** `yt-dlp` search/download + `ffmpeg` compress → deliver audio →
  cache file_id (no storage). Handle >50 MB (split or document the Bot-API-server option).
- **Phase 6 — Categories & language.** Category browse keyboards + `book_categories`; language default
  `uz`, English on request; seed initial categories.
- **Phase 7 — Admin uploads.** Admin-only PDF upload flow with title/author/category/language tagging.
- **Phase 8 — Polish & deploy.** Tests, rate-limit/anti-abuse, logging, Docker, optional self-hosted
  Bot API server for large audio.

---

## 17. Testing & verification

- **Unit (no network):** ranking (`rapidfuzz`), orchestrator decision tree with mocked providers, PDF
  validation, YouTube result parsing.
- **Integration:** run the migration on a scratch Supabase project; ingest/admin-upload a couple of
  books; verify `search_books()` returns ranked results.
- **Manual end-to-end (Telegram):**
  1. `/start` → choose PDF → search a known DB title → receive PDF.
  2. Search a title **not** in DB → confirm Google-fetched PDF arrives **and** is now in the DB (second
     search is instant).
  3. Choose Audio → search "Binafsha" → confirm YouTube audio arrives, compressed.
  4. Choose Audio for a title that only has PDF → confirm cross-format fallback offers the PDF.
  5. Browse a category → confirm filtered, paginated results.
  6. As admin → upload a PDF → confirm it's searchable.

---

## 18. Legal & responsible use

🇺🇿 **Ochiq gaplashamiz (qonuniy tomoni).** Bot internetdan (Google, YouTube) kitob/audio olib kelishi
mumkin. Ko'p kitoblar va audiolar **mualliflik huquqi bilan himoyalangan** bo'lishi mumkin — ularni ruxsatsiz
tarqatish ko'p mamlakatlarda noqonuniy va Telegram qoidalariga ham zid. Bu loyihaning **operatori siz** —
mas'uliyat ham sizda. Tavsiyalar:

- Imkon qadar **ochiq/erkin litsenziyali**, **public-domain** yoki **huquq egasi o'zi yuklagan** kontentni
  ustun qo'ying (masalan, rasmiy nashriyot yuklaganlari, public domain klassikalar).
- Huquq egasidan **shikoyat/takedown** kelsa — darhol o'chirish imkoniyatini qo'shing (`source_ref` shu uchun
  saqlanadi).
- Tijoriy tarqatishdan oldin mahalliy qonunlarni va Telegram ToS'ni tekshiring.

The codebase keeps providers **pluggable** specifically so legal/licensed sources can be prioritized or
swapped in. Use it responsibly.

---

*Built with Python · aiogram · Supabase · yt-dlp · ffmpeg. MIT licensed.*
