# 📋 BookBot — Progress & Next Steps

> 🇺🇿 Bu fayl — qayerga kelganimiz va nima qolganini ko'rsatadi. Ertaga shu yerdan davom etamiz.
> To'liq loyiha tavsifi: **README.md**. Bosqichlar ro'yxati: README §16 (Build Roadmap).

_Last updated: 2026-06-16 (Phase 5 + variants/cards from user feedback done)_

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

### Phase 2 — DB search + pagination (DONE)
- `rapidfuzz` added to `pyproject.toml` and installed in the venv.
- `db.search_books()` now passes the `lang` + `fmt` filters the RPC expects (was
  only sending `q/lim/off`). Results are filtered by the chosen format.
- `bot/search.py` `search_page()` takes `fmt`/`language`, over-fetches `PAGE_SIZE+1`
  to detect a next page, and re-ranks the page with `rapidfuzz`.
- New `bot/ranking.py`: `best_exact()` (deliver a near-exact unique hit straight
  away) + `rerank()` for display order.
- Text query → search → either deliver the exact hit or show a numbered list with
  ◀ / ▶ pagination (`results_keyboard`). Query + page kept in FSM.
- New `bot/delivery.py`: sends PDF from Supabase Storage, then caches the Telegram
  `file_id` so the next send is instant. (Audio + cross-format come in Phases 3–5.)
- New `scripts/seed_test_book.py`: seeds one real valid-PDF test book (idempotent;
  `--delete` to remove). One test book currently seeded: **"BookBot Test Kitob"**.
- Verified headlessly: search (incl. fuzzy/typo) finds it, exact-match fires, mp3
  filter correctly excludes the PDF-only book, and the PDF downloads from Storage
  (`%PDF`, 590 bytes). 13 unit tests pass; ruff clean.
  ⏳ _Still to confirm live in Telegram:_ tap a result → PDF arrives → `file_id`
  gets cached (needs the running bot + a real chat).

### Phase 3 — Cross-format fallback (DONE)
- When the chosen format returns nothing, the bot re-searches **without** the format
  filter (`search_page(..., fmt=None)`):
  - **Single clear hit** → offers the format it actually has with ✅/❌ buttons
    ("🎧 Audio topilmadi, lekin 📕 PDF bor. «…» — yuboraymi?") via `offer_keyboard`.
  - **Several hits** → shows the normal numbered list with a note + format badges,
    so the user picks knowingly. Pagination tracks a `cross_format` FSM flag so it
    keeps searching without the filter.
- `delivery.deliver_book()` now prefers the requested format and **falls back** to
  whatever format the book has (caption emoji + audio/document send follow the
  actual file format).
- New: `OfferCB` + `offer_keyboard` (keyboards), `cross_format_offer()` /
  `cross_format_list_note()` (texts), `on_offer_accept` handler.
- Verified headlessly: Audio mode + "BookBot Test Kitob" (PDF-only) → `mp3` search
  empty, unfiltered finds it, offer text renders correctly. 13 tests pass; ruff clean.
  ⏳ _Live check:_ Audio mode → search the test book → accept the PDF offer.
  (Reverse "offer audio" is fully testable once Phase 5 brings audio into the DB.)

### Phase 4 — PDF web provider (DONE)
- `ddgs` added to deps + installed. New `src/bookbot/providers/` package:
  - `base.py` — `SourceProvider` protocol + normalized `FetchResult` dataclass.
  - `pdf_web.py` — `fetch(title, language)`: DuckDuckGo `"<title>" filetype:pdf`
    search (keyless) → download each candidate size-capped at `MAX_FILE_MB` →
    validate (`%PDF` magic + content-type) → return first valid. Network errors on
    a candidate just skip to the next; retries once without quotes.
- `db.save_pdf_book()` — uploads bytes to Storage (`web/<book_id>.pdf`) + inserts
  book/file rows, **dedupes by (title, language)** so a re-fetch reuses the entry.
  (Uses the real schema columns directly — not the legacy `upsert_book`.)
- Wired into `handlers._try_web_pdf`: when the DB (filtered **and** unfiltered) has
  nothing → search the web. PDF mode delivers it directly; Audio mode offers it
  ("internetdan PDF topdim — yuboraymi?"). Saved PDFs are now cached for next time.
- Verified end-to-end headlessly: fetched a real 3.8 MB public-domain PDF from the
  web, saved to Storage + catalog, confirmed searchable + re-downloadable (bytes
  match), then cleaned up. 17 tests pass; new code ruff clean.
  ⏳ _Live check:_ PDF mode → search a title NOT in the DB → PDF arrives from the
  web AND a second search is now instant (served from DB).

### Phase 5 — YouTube audio provider (DONE)
- `yt-dlp` added to deps + installed. New `providers/youtube_audio.py`:
  - `search_candidates(query)` — `ytsearchN:<query> audiokitob` (flat = fast),
    filters by sane duration, returns video candidates (id, title, duration, uploader).
  - `download_audio(video_id, workdir, max_bytes, bitrate)` — downloads best audio,
    **one explicit ffmpeg pass → mono + 48 kbps MP3** (guaranteed mono — the yt-dlp
    postprocessor left it stereo), then **splits into part_000/001/… if over the cap**
    (ffmpeg segment, `-c copy`, drops empty tail segments).
  - Verified live: "O'tkan kunlar" → 42-min candidate → 14.65 MB **mono** mp3; split
    logic tested with synthetic files (even parts, all under cap).
- Audio is NOT stored; `db.save_audio_book()` keeps a book row + `book_files` row with
  `youtube_id` + **comma-joined Telegram file_ids** (multi-part cache, no storage).
- `delivery.send_audio_parts()` sends parts labelled 1/N…; `deliver_book` re-sends
  cached audio by splitting the joined file_ids.

### Variants + detail cards + metadata (from user feedback — DONE)
Addresses the 4 issues raised after testing:
1. **YouTube wasn't searched** → audio mode now searches YouTube on a DB miss.
2. **PDF grabbed junk (a presentation)** → web PDF now returns **multiple ranked,
   domain-deduped variants** (min-size filter drops slide decks); the user picks.
3. **Show all variants** → both PDF and audio show a numbered variant list
   (source site / duration shown); user chooses.
4. **Book description + design** → new `providers/metadata.py` (OpenLibrary, keyless)
   + `bot/cards.py`: after picking a result/variant, a **detail card** is shown —
   cover image + title + author + 🏷 type + 🌐 language + ⏱ duration (audio) +
   description — then a **📥 Yuborish** button delivers it. Works for DB books and
   internet variants; description/cover are saved to the catalog.
- New callbacks: `CardCB` (open card) + `SendCB` (confirm). Flow:
  search → variant/result list → pick → card → 📥 → download (if needed) + deliver + save.
- 16 unit tests pass (candidate ranking, language priority, card rendering, duration
  formatting); ruff clean. Live-verified data layer (save audio/pdf + metadata +
  mp3 search) end-to-end.
  ⏳ _Live check needed in Telegram (restart bot first):_ audio search → variant list →
  card → 📥 → audio arrives (split if long); PDF search of a non-DB title → variants →
  card → PDF arrives + 2nd search instant.

### Cleanup (DONE)
- Removed dead v1 ingestion code (`src/bookbot/ingest/`, `tests/test_ingest.py`,
  `bookbot-ingest` script) and the broken v1 `db.upsert_book*` (used a non-existent
  `source_id` column). `models.Book` removed; `BookFile.storage_path` now optional.
  Lint is now clean across the whole tree.

### Search-quality + reliability fixes (2026-06-16, after live testing)
- **Bug:** raw `InlineKeyboardButton(callback_data=CB(...))` (back/pagination) crashed
  every list build (needs `.pack()`) → user saw a frozen "searching…". Fixed + added
  a global `@router.error` handler + `tests/test_keyboards.py` regression guard.
- **Audio upload timeout:** raised Telegram request timeout 60s → 600s
  (`request_timeout_seconds`); audio now split into smaller ~20 MB parts
  (`audio_part_mb`) for reliable uploads on slow links.
- **PDF search overhaul** (`providers/pdf_web.py`) — the big one. `"<title>" filetype:pdf`
  returned paid stores (uzum/asaxiy) + junk and missed free Uzbek PDFs (which sit behind
  download pages, not direct `.pdf` URLs). Now:
  - Discovery = **site-restricted queries** for reliable free sites (mykitob.uz,
    kitobxon.com) + general "pdf yuklab olish" queries, so the actual *book page* surfaces.
  - **Blocklist** paid/news/PDF-tool/aggregator domains; **boost** known free book sites;
    rank by title similarity; dedupe by domain.
  - `download_validate` fetches the page HTML and **extracts the real PDF link**
    (direct `.pdf` OR download-monitor `/download/NNN/`), using **browser headers +
    Referer** (fixes 403s). Validates `%PDF` + size.
  - Confirm handler **falls through candidates** — if the picked link is dead/blocked,
    auto-tries the others so the user still gets a free PDF.
  - Verified live: ityurak → mykitob.uz 912 KB; Mehrobdan chayon → mykitob 3.1 MB;
    Sariq devni minib → ziyonet 9.7 MB. All real free book PDFs ✅.
- ⏳ Known limit: some sites block bots (captcha/JS) — the fall-through handles it by
  trying other candidates. Coverage is good but not 100%.

### Card quality + relevance + speed (2026-06-16, round 2 of feedback)
- **Cover + description + genre from the book's OWN page** (`metadata.scrape_meta`):
  Uzbek sites have rich OpenGraph tags (cover image + Uzbek description) that
  OpenLibrary lacks. `pdf_web.page_info(url)` fetches the page once → scraped meta +
  resolved PDF link(s); the card shows cover/description/🏷 type/📚 Janr/author, and
  the confirm step **reuses the cached link** (no second page fetch = faster).
- **PDF filename = book title** (`delivery._safe_filename`) instead of the ugly
  storage uuid, so it doesn't look like a sketchy random download. Audio parts too.
- **Filter out non-books** — slide decks / taqdimot / insho / referat / konspekt are
  dropped from candidates; dropped the bare `filetype:pdf` query that dragged them in.
- **Speed:** fewer + parallel queries (~9s); card reuses the one page fetch; OpenLibrary
  only as a fallback when the page lacks cover/description.
- Auto-save: delivered PDFs (`save_pdf_book`) and audio (`save_audio_book`) are already
  cached to the DB with description/cover, so a later request for the same book is served
  from the catalog.
- 24 unit tests pass (added scrape_meta, not-a-book filter, genre card); ruff clean.
  ⏳ Author is best-effort (only a visible "Muallif:" label is trusted — avoids JSON-LD
  garbage); often absent for Uzbek pages.

### AI descriptions via OpenAI (2026-06-16)
- Web/OpenLibrary lack descriptions for Uzbek books, so descriptions/genre now come
  from **OpenAI GPT** (`providers/ai_meta.py`, `gpt-4o-mini`, ~$0.00003/book). It
  returns a 1–2 sentence Uzbek description + genre, refuses to hallucinate for
  non-books (returns null), and is `lru_cache`d per process.
- `_ai_fill()` in handlers fills a missing description/genre on every card (DB / PDF /
  audio), preferring real scraped/DB data and falling back to AI. New AI descriptions
  are persisted to the catalog (`db.update_book_meta`), so a book is described once.
- Config: `OPENAI_API_KEY` + `OPENAI_MODEL` (in `.env`, gitignored; documented in
  `.env.example`). `openai` added to deps.
- `scripts/backfill_descriptions.py` — one-off: fills descriptions for existing books
  that lack one. Ran it: 3/6 real books described (test/junk entries correctly skipped).
- Note: covers are still best-effort (an LLM can't supply a real cover image) — they
  come from the book page's og:image or OpenLibrary when available.
- ⚠️ The OpenAI key was pasted in chat — user should rotate it.

### Key decisions locked in
- **PDF search = DuckDuckGo (`ddgs`), keyless.** (Google PSE dropped whole-web search in 2026 — dropped.)
- **Audio = YouTube via `yt-dlp` + `ffmpeg`, keyless.** Audio files are NOT stored; only a Telegram
  `file_id` is cached (no storage cost).
- **No API keys needed** for any search source.
- **Uzbek-first** (`DEFAULT_LANGUAGE=uz`); English on request.

---

## 🔜 What's left (next sessions)

- **Phase 6 — Categories & language** ← _START HERE NEXT_ (browse by category listing; uz/en filtering).
- **Phase 7 — Admin uploads** (admin sends a PDF → tag title/author/category/language → store).
- **Phase 8 — Polish & deploy** (tests, rate-limit/anti-abuse, logging, Docker, optional Bot API server).

### Dependencies — all added
- ✅ `rapidfuzz` (Phase 2), `ddgs` (Phase 4), `yt-dlp` (Phase 5). `ffmpeg`+`ffprobe` installed.
- Metadata uses OpenLibrary via `httpx` (no new dep). Google Books was dropped (anonymous 429s).

### Notes
- Dead v1 ingestion code + broken `db.upsert_book*` have been **removed** (see Cleanup above).
  Writes now go through `db.save_pdf_book` / `db.save_audio_book`, which use the real schema.
- Metadata (cover + description) is best-effort: Uzbek titles often lack a cover/description on
  OpenLibrary, so the card degrades gracefully (no cover → text card; no description → just metadata).
- Long audiobooks are split into parts (50 MB cap). Optional future upgrade: self-hosted Telegram
  Bot API server raises the cap to 2 GB (Phase 8) so big audio sends as one file.

---

## ▶️ How to resume

```bash
cd /Users/tokhirbek/Documents/PROJECTS/BookBot
source .venv/bin/activate        # venv already created with deps installed
python -m bookbot.bot.main       # run the bot (long polling) → test in @jeymsbooks_bot
pytest                            # run tests
```

`.env` is already filled (gitignored — never committed). Supabase project is live.
