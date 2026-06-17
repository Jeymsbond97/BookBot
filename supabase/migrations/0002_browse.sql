-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ BookBot — Phase 6: browse books by category                                ║
-- ║ Run this in the Supabase dashboard → SQL Editor → New query → Run.          ║
-- ╚══════════════════════════════════════════════════════════════════════════╝

-- List books tagged with a category, newest first. Mirrors search_books' return
-- shape (so the bot reuses SearchResult + the same list→card→send flow).
-- Optional filters: language (NULL = any) and format (NULL = any; otherwise only
-- books that have a file in that format are returned).
create or replace function public.browse_books(
  cat_slug text,
  lang     text default null,
  fmt      text default null,
  lim      int  default 5,
  off      int  default 0
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
  select
    b.id,
    b.title,
    b.author,
    b.language,
    coalesce(array_agg(distinct f.format order by f.format)
             filter (where f.format is not null), '{}') as formats,
    0::real as rank
  from public.books b
  join public.book_categories bc on bc.book_id = b.id
  join public.categories c       on c.id = bc.category_id
  left join public.book_files f  on f.book_id = b.id
  where c.slug = cat_slug
    and (lang is null or b.language = lang)
  group by b.id
  having (fmt is null or fmt = any(
           array_agg(distinct f.format) filter (where f.format is not null)))
  order by b.created_at desc, b.title asc
  limit greatest(lim, 1)
  offset greatest(off, 0);
$$;
