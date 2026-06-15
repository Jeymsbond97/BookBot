# 📋 BookBot — Progress & Next Steps

> 🇺🇿 Bu fayl — qayerga kelganimiz va nima qolganini ko'rsatadi. Ertaga shu yerdan davom etamiz.
> To'liq loyiha tavsifi: **README.md**. Bosqichlar ro'yxati: README §16 (Build Roadmap).

_Last updated: 2026-06-15_

---

## ✅ Done so far

### Phase 0 — Foundation (DONE)
- Project scaffolded: `pyproject.toml`, package layout under `src/bookbot/`, tests, Docker.
- **`.env` filled & verified** — Telegram token, `ADMIN_IDS`, Supabase URL / service key / bucket.
- **Supabase connected**: `books` bucket created (private); migration `supabase/migrations/0001_init.sql`
  applied → tables `books`, `book_files`, `categories` (7 seeded), `book_categories`, and the
  `search_books()` RPC all verified working.
- **ffmpeg installed** (v8.1.1) — needed for audio compression in Phase 5.

### Phase 1 — Format-first bot flow (DONE)
- `/start` → choose **📕 PDF** or **🎧 Audio** (stored in FSM).
- Main menu: **📂 Kategoriyalar** / **🔄 Formatni o'zgartirish**; 7 categories listed.
- `/help`; "choose format first" guard; text query shows a Phase-2 placeholder.
- Files: `bot/handlers.py`, `bot/keyboards.py`, `bot/states.py`, `bot/texts.py`, `bot/main.py`.
- Verified live in Telegram (@jeymsbooks_bot) — works ✅.

### Key decisions locked in
- **PDF search = DuckDuckGo (`ddgs`), keyless.** (Google PSE dropped whole-web search in 2026 — dropped.)
- **Audio = YouTube via `yt-dlp` + `ffmpeg`, keyless.** Audio files are NOT stored; only a Telegram
  `file_id` is cached (no storage cost).
- **No API keys needed** for any search source.
- **Uzbek-first** (`DEFAULT_LANGUAGE=uz`); English on request.

---

## 🔜 What's left (next sessions)

- **Phase 2 — DB search + pagination** ← _START HERE TOMORROW_
  - Wire `search_books()` RPC into the bot: text query → ranked results, filtered by chosen format.
  - Exact-match shortcut + paginated fuzzy list (◀ 1 2 3 ▶) using `rapidfuzz` for ranking.
  - Deliver PDF from Supabase Storage with `telegram_file_id` caching.
  - (We currently have 0 books in DB — may add a couple of test PDFs via admin upload or a seed to test.)
- **Phase 3 — Cross-format fallback** (chosen format missing → offer the other).
- **Phase 4 — PDF web provider** (`ddgs` `filetype:pdf` → download → `%PDF` validation → save & cache).
- **Phase 5 — YouTube audio provider** (`yt-dlp` search/download + `ffmpeg` compress → send → cache
  file_id; handle >50 MB via split or self-hosted Bot API server).
- **Phase 6 — Categories & language** (browse by category listing; uz/en filtering).
- **Phase 7 — Admin uploads** (admin sends a PDF → tag title/author/category/language → store).
- **Phase 8 — Polish & deploy** (tests, rate-limit/anti-abuse, logging, Docker, optional Bot API server).

### Dependencies still to add (when their phase starts)
- `ddgs` (Phase 4), `yt-dlp` (Phase 5), `rapidfuzz` (Phase 2) → add to `pyproject.toml` `dependencies`.

### Cleanup note
- Original v1 ingestion code (`src/bookbot/ingest/gutenberg.py`, `librivox.py`, `cli.py`, `storage.py`)
  and `bot/search.py` are leftovers from the first design. They'll be replaced/removed as Phases 2–5
  build the new providers. Not used by the running bot.

---

## ▶️ How to resume

```bash
cd /Users/tokhirbek/Documents/PROJECTS/BookBot
source .venv/bin/activate        # venv already created with deps installed
python -m bookbot.bot.main       # run the bot (long polling) → test in @jeymsbooks_bot
pytest                            # run tests
```

`.env` is already filled (gitignored — never committed). Supabase project is live.
