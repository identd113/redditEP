"""Reader stage: fetch a configured feed and yield raw, uncleaned entries.

Deliberately dumb — no filtering, no dedup, no HTML cleaning. Those are the
feed_parsers stage's job. This module only knows how to talk to feedparser.
"""

import feedparser
from bs4 import BeautifulSoup

from edenprairie_news.models import FeedSource, RawEntry


def fetch_feed(source: FeedSource) -> list[RawEntry]:
    parsed = feedparser.parse(source.url)
    entries = []
    for entry in parsed.entries:
        entries.append(
            RawEntry(
                url=entry.get("link", ""),
                source=source.name,
                title=entry.get("title", ""),
                summary_html=entry.get("summary", ""),
                published_at=_extract_published(entry),
                author=entry.get("author", ""),
                image_url=_extract_image(entry) or "",
            )
        )
    return entries


def _extract_published(entry) -> str | None:
    if "published" in entry:
        return entry.published
    if "updated" in entry:
        return entry.updated
    return None


def _extract_image(entry) -> str | None:
    for thumb in entry.get("media_thumbnail", []):
        if thumb.get("url"):
            return thumb["url"]

    for media in entry.get("media_content", []):
        if media.get("url") and media.get("medium", "image") == "image":
            return media["url"]

    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and link.get("type", "").startswith("image"):
            return link.get("href")

    img_tag = BeautifulSoup(entry.get("summary", ""), "html.parser").find("img")
    if img_tag and img_tag.get("src"):
        return img_tag["src"]

    return None
