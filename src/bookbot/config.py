"""Application configuration loaded from environment / .env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed settings read from environment variables or a .env file."""

    telegram_bot_token: str
    admin_ids: str = ""  # comma-separated Telegram numeric ids

    supabase_url: str
    supabase_service_key: str
    supabase_bucket: str = "books"

    # OpenAI — generates Uzbek book descriptions + genre when web/OpenLibrary lack them.
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Behaviour / tuning.
    default_language: str = "uz"
    audio_bitrate_kbps: int = 48
    max_file_mb: int = 50
    # Target size per audio part. Smaller than the 50 MB Telegram cap so each part
    # uploads quickly/reliably on a slow link (long audiobooks → more, smaller parts).
    audio_part_mb: int = 20
    cache_audio_file_id: bool = True
    ingest_delay_seconds: float = 1.0
    # Telegram request timeout (seconds) — big enough to upload large audio parts
    # over a slow connection without aborting.
    request_timeout_seconds: float = 600.0
    # Optional proxy for reaching Telegram when it's blocked on the network
    # (e.g. "socks5://127.0.0.1:1080" or "http://user:pass@host:port"). Empty = direct.
    telegram_proxy: str = ""

    # ── Telethon "fetcher" (user account) — finds books in Telegram channels and
    # forwards big files (up to 2 GB) into a private storage channel the bot copies
    # from. All optional: if api_id/session/storage are unset, the channel provider
    # is simply skipped and the bot falls back to web/YouTube as before.
    telethon_api_id: int = 0
    telethon_api_hash: str = ""
    telethon_session: str = ""  # StringSession from scripts/telethon_login.py
    storage_channel_id: str = ""  # e.g. "-1001234567890"
    source_channels: str = ""  # comma-separated @usernames or -100… ids

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def admin_id_list(self) -> list[int]:
        """Parse ADMIN_IDS ('1,2,3') into a list of ints."""
        return [int(x) for x in self.admin_ids.replace(" ", "").split(",") if x]

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_id_list

    @property
    def source_channel_list(self) -> list[str]:
        """Parse SOURCE_CHANNELS ('@a,@b,-100…') into a list of channel refs."""
        return [c.strip() for c in self.source_channels.split(",") if c.strip()]

    @property
    def telethon_enabled(self) -> bool:
        """True only when the Telethon fetcher is fully configured (api creds +
        a logged-in session + a storage channel to forward into)."""
        return bool(
            self.telethon_api_id
            and self.telethon_api_hash
            and self.telethon_session
            and self.storage_channel_id
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance (loaded on first use)."""
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
