"""Shared data types passed between pipeline stages."""

from dataclasses import dataclass, field


@dataclass
class RawEntry:
    """A single feed entry as returned by the reader stage, before cleaning."""

    url: str
    source: str
    title: str
    summary_html: str
    published_at: str | None  # ISO 8601 string, or None if the feed didn't provide one
    author: str = ""
    image_url: str = ""  # empty if the feed entry didn't include one


@dataclass
class Article:
    """A cleaned, deduped article ready for formatting/storage."""

    url: str
    source: str
    title: str
    summary: str
    published_at: str | None
    author: str = ""
    image_url: str = ""
    scope: str = "local"  # "local" (about Eden Prairie) or "related" (a neighbouring city's news)
    id: int | None = None
    status: str = "new"  # new -> drafted -> sent -> posted | rejected (sent: handed to Reddit, awaiting its link); removed = taken off the lists, link remembered
    post_title: str = ""
    post_body: str = ""
    reddit_post_id: str | None = None
    reddit_url: str = ""  # permalink of the Reddit post made from this article, once known
    sent_at: str | None = None


@dataclass
class FeedSource:
    name: str
    url: str
    tags: list[str] = field(default_factory=list)
    parser: str = "default"  # key into feed_parsers.PARSERS
    id: int | None = None  # set when loaded from storage.list_feeds(), for delete-by-id
