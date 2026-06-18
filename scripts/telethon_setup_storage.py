#!/usr/bin/env python
"""Create the private storage channel and make the bot an admin of it.

The userbot (Telethon, logged-in session in .env) creates a private channel,
invites @<bot> and grants it admin rights, then prints the channel's -100… id to
put in STORAGE_CHANNEL_ID. Idempotent-ish: if STORAGE_CHANNEL_ID is already set,
it just verifies/re-grants the bot's admin rights instead of creating a new one.

    source .venv/bin/activate
    python scripts/telethon_setup_storage.py

Needs no interactive input — it uses the saved TELETHON_SESSION.
"""

from __future__ import annotations

import sys

import httpx
from telethon import utils
from telethon.sessions import StringSession
from telethon.sync import TelegramClient
from telethon.tl.functions.channels import (
    CreateChannelRequest,
    EditAdminRequest,
)
from telethon.tl.types import ChatAdminRights, Channel

from bookbot.config import get_settings

_BOT_RIGHTS = ChatAdminRights(
    post_messages=True,
    edit_messages=True,
    delete_messages=True,
    invite_users=True,
    pin_messages=True,
    manage_call=False,
    other=True,
)


def _bot_username(token: str) -> str:
    r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()
    return r["result"]["username"]


def main() -> int:
    s = get_settings()
    if not (s.telethon_api_id and s.telethon_api_hash and s.telethon_session):
        print("✗ Telethon api_id/api_hash/session must be set in .env first.")
        return 1

    bot = _bot_username(s.telegram_bot_token)
    print(f"→ Bot to add as admin: @{bot}")

    with TelegramClient(
        StringSession(s.telethon_session), s.telethon_api_id, s.telethon_api_hash
    ) as client:
        title = "BookBot Storage"
        channel = None
        if s.storage_channel_id:
            channel = client.get_entity(int(s.storage_channel_id))
            print(f"→ Reusing storage channel from .env: {channel.title}")
        else:
            # Reuse one we created on a previous (failed) run, to avoid duplicates.
            for d in client.iter_dialogs():
                e = d.entity
                if (
                    isinstance(e, Channel)
                    and getattr(e, "broadcast", False)
                    and getattr(e, "creator", False)
                    and e.title == title
                ):
                    channel = e
                    print(f"→ Reusing existing channel: {title}")
                    break
        if channel is None:
            res = client(
                CreateChannelRequest(
                    title=title,
                    about="Private cache — fetched books the bot serves to users.",
                    megagroup=False,
                )
            )
            channel = res.chats[0]
            print(f"✓ Created channel: {channel.title}")

        # A bot can't be "invited" to a broadcast channel — granting admin rights
        # adds it directly.
        client(EditAdminRequest(channel, bot, _BOT_RIGHTS, rank="bot"))
        chan_id = utils.get_peer_id(channel)  # -100… form for the Bot API
        print(f"✓ @{bot} is now admin.\n")
        print("Put this in .env:\n")
        print(f"STORAGE_CHANNEL_ID={chan_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
