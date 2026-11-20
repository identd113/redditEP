"""Fire-and-forget Discord webhook notifications.

Deliberately not a bot: no token, no persistent connection, just a POST to
a channel webhook URL. If DISCORD_WEBHOOK_URL isn't set this silently no-ops
so the rest of the pipeline works fine without Discord configured at all.

An interactive bot (slash commands, in-Discord Approve/Reject buttons) would
need a persistent discord.py process instead of this - see the "Planned"
note in CLAUDE.md before building that.
"""

import logging

import requests

from edenprairie_news.config import get_discord_config

logger = logging.getLogger(__name__)


def notify_new_drafts(count: int, web_url: str) -> None:
    if count <= 0:
        return
    webhook_url = get_discord_config().webhook_url
    if not webhook_url:
        logger.info("DISCORD_WEBHOOK_URL not set, skipping notification for %d draft(s)", count)
        return

    plural = "s" if count != 1 else ""
    content = f"{count} new draft{plural} ready for review → {web_url}"
    try:
        response = requests.post(webhook_url, json={"content": content}, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to send Discord notification")
