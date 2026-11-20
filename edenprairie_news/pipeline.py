"""Orchestrates reader -> feed_parsers -> storage -> formatter for one on-demand run.

This is intentionally the only module that calls multiple stages together.
Each stage stays independently testable; this file just wires them up.

Feeds are processed one source at a time (not flattened together) so each
source's own parser strategy and relevance-filter tag apply only to its own
entries -- see edenprairie_news/feed_parsers/. The feed list itself comes
from storage.list_feeds() (DB-backed, editable from the web UI's Config
page), not config/feeds.yaml -- that file is only a first-run seed.
"""

from datetime import date

from edenprairie_news.config import WebConfig, max_article_age_days
from edenprairie_news import event_feeds
from edenprairie_news.events import extract_events
from edenprairie_news.feed_parsers import get_parser
from edenprairie_news.formatter import format_post
from edenprairie_news.models import FeedSource
from edenprairie_news.notifier import notify_new_drafts
from edenprairie_news.parser import filter_recent, filter_relevant
from edenprairie_news.reader import fetch_feed
from edenprairie_news.storage import init_db, insert_new_articles, list_feeds, save_draft


def run_pipeline() -> dict:
    """Fetches all configured feeds, stores any new articles, and drafts
    Reddit posts for each. Returns a summary dict for logging/display."""
    init_db()
    fetched = 0
    new_articles = []

    events_imported = 0
    for source in list_feeds():
        if source.parser == "events":  # a calendar feed: each item is an event, not an article
            events_imported += _import_event_feed(source)
            continue
        raw_entries = fetch_feed(source)
        fetched += len(raw_entries)
        new_articles.extend(_process_source(source, raw_entries))

    venues = None
    for article in new_articles:
        title, body = format_post(article)
        if article.scope == "local":
            _suggest_events(article, venues)
        # insert_new_articles doesn't return DB ids, so re-fetch is unnecessary here:
        # we draft by url lookup instead to keep this loop simple.
        _draft_by_url(article.url, title, body)

    notify_new_drafts(len(new_articles), WebConfig.base_url())

    return {"fetched": fetched, "new": len(new_articles), "events": events_imported}


def _import_event_feed(source: FeedSource) -> int:
    """New event suggestions from one events feed. A failing feed is logged and skipped, never stopping the run."""
    import logging

    try:
        counts = event_feeds.import_from_url(source.url)
    except Exception:
        logging.getLogger(__name__).exception("event feed %s failed", source.url)
        return 0
    logging.getLogger(__name__).info("event feed %s: %s", source.name, counts)
    return counts["new"]


def _process_source(source: FeedSource, raw_entries: list) -> list:
    parse_entry = get_parser(source.parser)
    articles = filter_recent([parse_entry(e) for e in raw_entries if e.url and e.title], max_article_age_days())
    scope = "related" if "related" in source.tags else "local"
    for a in articles:
        a.scope = scope  # news about a neighbouring city: kept apart from Eden Prairie's and never mined for events
    if "needs-filter" in source.tags:
        articles = filter_relevant(articles)
    return insert_new_articles(articles)


def reference_date(published_at: str | None) -> date:
    """The article's publish date from whatever format the feed used (ISO, or RFC 822 like
    "Mon, 12 Jul 2026 14:03:00 GMT"); today when it is missing or unreadable."""
    from edenprairie_news.dates import parse_published

    parsed = parse_published(published_at)
    return parsed.date() if parsed else date.today()


def backfill_events() -> dict:
    """Run event extraction over articles already stored (for example after fixing the extractor). Safe to
    repeat: an event already stored is ignored."""
    from edenprairie_news.models import Article
    from edenprairie_news.storage import get_conn, init_db

    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT url, source, title, summary, published_at FROM articles").fetchall()
    before = _count_events()
    for r in rows:
        _suggest_events(Article(url=r["url"], source=r["source"], title=r["title"], summary=r["summary"] or "", published_at=r["published_at"]))
    return {"articles": len(rows), "new_events": _count_events() - before}


def _count_events() -> int:
    from edenprairie_news.storage import get_conn

    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def _suggest_events(article, venues=None) -> None:
    """Look for events (dates, times, places) in the article's title and summary and store them as
    suggestions for the Events page. A failure here must never stop drafting, so it is only logged."""
    import logging

    from edenprairie_news.storage import get_conn, insert_events

    try:
        reference = reference_date(article.published_at)
        candidates = extract_events(article.title, f"{article.title}. {article.summary}", reference, venues)
        if candidates:
            with get_conn() as conn:
                row = conn.execute("SELECT id FROM articles WHERE url = ?", (article.url,)).fetchone()
            if row:
                insert_events(row["id"], article.url, candidates)
    except Exception:
        logging.getLogger(__name__).exception("event extraction failed for %s", article.url)


def _draft_by_url(url: str, title: str, body: str) -> None:
    from edenprairie_news.storage import get_conn

    with get_conn() as conn:
        row = conn.execute("SELECT id FROM articles WHERE url = ?", (url,)).fetchone()
    if row:
        save_draft(row["id"], title, body)


def main() -> None:
    summary = run_pipeline()
    print(f"Fetched {summary['fetched']} entries, {summary['new']} new articles drafted.")


if __name__ == "__main__":
    main()
