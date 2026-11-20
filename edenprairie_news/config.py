"""Env vars (.env) plus DB-backed settings/feeds overrides (storage.py).

Reddit/Discord config and the feed list are editable at runtime from the
web UI's Config page, persisted in the settings/feeds tables in storage.py.
get_reddit_config()/get_discord_config() below resolve fresh on every call
(DB value if set, else the matching .env var) so a saved change takes
effect on the very next pipeline run or web request -- no process restart.

FEEDS_PATH/config/feeds.yaml is only read once, as a first-run seed for the
feeds table (see storage._seed_feeds_if_empty) -- after that the DB is
authoritative and this file isn't read again. storage.list_feeds() is the
runtime feed source, not this module.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
FEEDS_PATH = REPO_ROOT / "config" / "feeds.yaml"
DB_PATH = REPO_ROOT / "data" / "articles.db"

load_dotenv(REPO_ROOT / ".env")


def _resolved(setting_key: str, env_var: str, default: str | None = None) -> str | None:
    from edenprairie_news import storage  # local import: storage.py imports this module

    db_value = storage.get_setting(setting_key)
    if db_value:
        return db_value
    return os.environ.get(env_var, default)


class WebConfig:
    """Bind address/port only -- env-only, not DB-editable. Changing where
    the server listens needs a process restart regardless of where the
    value lives, so there's no benefit to routing it through the DB."""

    host = os.environ.get("WEB_HOST", "0.0.0.0")
    port = os.environ.get("WEB_PORT", "1981")

    @classmethod
    def base_url(cls) -> str:
        """The address to put in links sent to other devices (Discord). WEB_BASE_URL wins if set (use it for a
        name such as http://newsbox.local:1981). Otherwise, when listening on every address, this machine's
        LAN address, so a phone on the same network can open it; 127.0.0.1 only as a last resort."""
        override = os.environ.get("WEB_BASE_URL", "").strip().rstrip("/")
        if override:
            return override
        if cls.host == "0.0.0.0":
            return f"http://{_lan_address()}:{cls.port}"
        return f"http://{cls.host}:{cls.port}"


def _lan_address() -> str:
    """This machine's address on the local network (the one it would use to reach the outside), without
    sending anything: a UDP socket "connected" to a public address only picks the route."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # documentation address: nothing is sent
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


@dataclass
class RedditSettings:
    client_id: str | None
    client_secret: str | None
    username: str | None
    password: str | None
    refresh_token: str | None
    user_agent: str
    subreddit: str
    sync_limit: int
    wiki_page: str = "events"

    @property
    def is_configured(self) -> bool:
        """Either auth path works: a refresh token from the web-login OAuth
        flow, or the account's raw username/password."""
        has_credentials = bool(self.client_id and self.client_secret)
        has_auth = bool(self.refresh_token) or bool(self.username and self.password)
        return has_credentials and has_auth

    @property
    def can_read(self) -> bool:
        """Enough to *read* Reddit (score, comments) as the app itself, with no account login: just the
        script app's client id and secret. Statistics only need this."""
        return bool(self.client_id and self.client_secret)


@dataclass
class DiscordSettings:
    webhook_url: str | None


def get_reddit_config() -> RedditSettings:
    return RedditSettings(
        client_id=_resolved("reddit_client_id", "REDDIT_CLIENT_ID"),
        client_secret=_resolved("reddit_client_secret", "REDDIT_CLIENT_SECRET"),
        username=_resolved("reddit_username", "REDDIT_USERNAME"),
        password=_resolved("reddit_password", "REDDIT_PASSWORD"),
        refresh_token=_resolved("reddit_refresh_token", "REDDIT_REFRESH_TOKEN"),
        user_agent=_resolved(
            "reddit_user_agent", "REDDIT_USER_AGENT", "edenprairie-news-bot/0.1 by u/unknown"
        ),
        subreddit=_resolved("reddit_subreddit", "REDDIT_SUBREDDIT", "edenprairie"),
        sync_limit=int(_resolved("reddit_sync_limit", "REDDIT_SYNC_LIMIT", "50")),
        wiki_page=_resolved("reddit_wiki_page", "REDDIT_WIKI_PAGE", "events"),
    )


def get_discord_config() -> DiscordSettings:
    return DiscordSettings(webhook_url=_resolved("discord_webhook_url", "DISCORD_WEBHOOK_URL"))


DEFAULT_MAX_AGE_DAYS = 30


def max_article_age_days() -> int:
    """Articles published longer ago than this are not drafted. 0 turns the limit off. Set on the Config page
    (or MAX_ARTICLE_AGE_DAYS); a missing or unreadable value means the default, 30."""
    raw = _resolved("max_article_age_days", "MAX_ARTICLE_AGE_DAYS", str(DEFAULT_MAX_AGE_DAYS))
    try:
        return max(0, int(str(raw).strip()))
    except ValueError:
        return DEFAULT_MAX_AGE_DAYS


def mod_queue_enabled() -> bool:
    """Off by default: the mod queue routes (view/approve/remove) call PRAW's
    mod.* methods, which need the configured Reddit account to actually be a
    subreddit moderator. A dedicated posting-only bot account isn't, so this
    stays off unless explicitly turned on from the Config page."""
    return _resolved("mod_queue_enabled", "ENABLE_MOD_QUEUE", "false") == "true"
