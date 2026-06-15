-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ BookBot — initial schema (PDF + audio, categories, Uzbek-first)           ║
-- ║ Run this in the Supabase dashboard → SQL Editor → New query → Run.         ║
-- ╚══════════════════════════════════════════════════════════════════════════╝

-- Fuzzy / partial matching for typo-tolerant title search.
create extension if not exists pg_trgm;

-- ── Catalog ──────────────────────────────────────────────────────────────────
create table if not exists public.books (
  id           uuid primary key default gen_random_uuid(),
  title        text not null,
  author       text,
  language     text not null default 'uz',     -- 'uz' primary, 'en', ...
  description  text,
  cover_url    text,
  source       text,                            -- 'admin' | 'web' | 'youtube' | ...
  source_ref   text,                            -- origin id/url (dedup + re-fetch + takedown)
  created_at   timestamptz default now(),
  -- generated full-text vector over title + author
  search_tsv   tsvector generated always as (
                 to_tsvector('simple',
                   coalesce(title, '') || ' ' || coalesce(author, ''))
               ) stored,
  unique (title, author, language)
);

-- Files attached to a book.
--   PDF  → storage_path set (file lives in Supabase Storage 'books' bucket).
--   MP3  → storage_path NULL; youtube_id set; file NOT stored (only optional file_id cache).
create table if not exists public.book_files (
  id               uuid primary key default gen_random_uuid(),
  book_id          uuid not null references public.books(id) on delete cascade,
  format           text not null,               -- 'pdf' | 'mp3'
  storage_path     text,                         -- set for PDF
  youtube_id       text,                         -- set for audio
  size_bytes       bigint,
  telegram_file_id text,                          -- cached after first send (instant re-send)
  created_at       timestamptz default now(),
  unique (book_id, format)
);

-- ── Categories (browse by topic) ─────────────────────────────────────────────
create table if not exists public.categories (
  id      serial primary key,
  slug    text unique not null,
  name_uz text not null,
  name_en text
);

create table if not exists public.book_categories (
  book_id     uuid not null references public.books(id) on delete cascade,
  category_id int  not null references public.categories(id) on delete cascade,
  primary key (book_id, category_id)
);

-- ── Indexes ──────────────────────────────────────────────────────────────────
create index if not exists books_search_idx   on public.books using gin (search_tsv);
create index if not exists books_title_trgm    on public.books using gin (title gin_trgm_ops);
create index if not exists books_author_trgm   on public.books using gin (author gin_trgm_ops);
create index if not exists books_language_idx  on public.books (language);
create index if not exists book_files_book_idx on public.book_files (book_id);
create index if not exists book_cats_cat_idx   on public.book_categories (category_id);

-- ── Seed the initial categories ──────────────────────────────────────────────
insert into public.categories (slug, name_uz, name_en) values
  ('psychology', 'Psixologiya',          'Psychology'),
  ('self-dev',   'Shaxsiy rivojlanish',  'Self-development'),
  ('fiction',    'Badiiy',               'Fiction'),
  ('history',    'Tarix',                'History'),
  ('religion',   'Diniy',                'Religion'),
  ('science',    'Ilm-fan',              'Science'),
  ('business',   'Biznes',               'Business')
on conflict (slug) do nothing;

-- ── Search function (called by the bot via RPC) ──────────────────────────────
-- Ranked title/author search with full-text + trigram fuzzy matching.
-- Optional filters: language (NULL = any) and format (NULL = any; otherwise only
-- books that have a file in that format are returned).
create or replace function public.search_books(
  q     text,
  lang  text default null,
  fmt   text default null,
  lim   int  default 5,
  off   int  default 0
)
returns table (
  id        uuid,
  title     text,
  author    text,
  language  text,
  formats   text[],
  rank      real
)
language sql
stable
as $$
  with term as (select nullif(trim(q), '') as t)
  select
    b.id,
    b.title,
    b.author,
    b.language,
    coalesce(array_agg(distinct f.format order by f.format)
             filter (where f.format is not null), '{}') as formats,
    (
      ts_rank(b.search_tsv,
              websearch_to_tsquery('simple', coalesce((select t from term), '')))
      + greatest(
          similarity(b.title, coalesce((select t from term), '')),
          similarity(coalesce(b.author, ''), coalesce((select t from term), ''))
        )
    )::real as rank
  from public.books b
  left join public.book_files f on f.book_id = b.id
  where
    (lang is null or b.language = lang)
    and (
      (select t from term) is null
      or b.search_tsv @@ websearch_to_tsquery('simple', (select t from term))
      or b.title  % (select t from term)
      or b.author % (select t from term)
    )
  group by b.id
  having (fmt is null or fmt = any(
           array_agg(distinct f.format) filter (where f.format is not null)))
  order by rank desc, b.title asc
  limit greatest(lim, 1)
  offset greatest(off, 0);
$$;

-- ── Storage bucket for PDF files (private) ───────────────────────────────────
insert into storage.buckets (id, name, public)
values ('books', 'books', false)
on conflict (id) do nothing;

-- NOTE: the bot/ingest use the SERVICE-ROLE key, which bypasses RLS, so no
-- policies are required. Add RLS policies before exposing tables to anon clients.
