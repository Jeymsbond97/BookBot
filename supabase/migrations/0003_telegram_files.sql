-- Phase T — Telegram-first fetch.
-- A book whose file lives in a Telegram channel is delivered by copy_message
-- from our private storage channel (no re-upload → no 50 MB cap). We store the
-- storage message reference so the bot can re-serve it instantly next time,
-- without re-running the userbot search/forward.
--
-- Run this in the Supabase SQL Editor (like 0002_browse.sql).

alter table book_files add column if not exists tg_chat_id bigint;
alter table book_files add column if not exists tg_msg_id  bigint;

comment on column book_files.tg_chat_id is 'Storage channel id (-100…) holding the forwarded file';
comment on column book_files.tg_msg_id  is 'Message id in the storage channel to copy_message from';
