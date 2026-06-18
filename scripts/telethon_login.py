#!/usr/bin/env python
"""One-time Telethon login → prints a StringSession to paste into .env.

Run this ONCE with the SPARE (2nd) Telegram account that will act as the
"fetcher" userbot — the one joined to all the book channels.

    source .venv/bin/activate
    python scripts/telethon_login.py

It reads TELETHON_API_ID / TELETHON_API_HASH from .env, asks for the account's
phone number + the login code Telegram sends (and 2FA password if enabled), then
prints a long TELETHON_SESSION string. Paste that into .env — after that the bot
logs in non-interactively and never needs the code again.

⚠️ The session string is as sensitive as a password (full account access). It
goes only into .env (gitignored). Never commit or share it.
"""

from __future__ import annotations

import sys

from telethon.sessions import StringSession
from telethon.sync import TelegramClient

from bookbot.config import get_settings


def main() -> int:
    s = get_settings()
    if not (s.telethon_api_id and s.telethon_api_hash):
        print("✗ TELETHON_API_ID / TELETHON_API_HASH are not set in .env.")
        return 1

    print("→ Logging in the FETCHER account (your 2nd/spare account).")
    print("  Use the phone number of the account joined to the book channels.\n")

    with TelegramClient(StringSession(), s.telethon_api_id, s.telethon_api_hash) as client:
        me = client.get_me()
        session = client.session.save()
        print("\n✓ Logged in as:", me.first_name, f"(@{me.username})" if me.username else "")
        print("\nPaste this whole line into .env (replace the empty TELETHON_SESSION=):\n")
        print(f"TELETHON_SESSION={session}")
        print("\n⚠️  Keep it secret — it's full access to this account.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
