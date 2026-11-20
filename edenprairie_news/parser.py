"""Shared parsing utilities used by strategies in feed_parsers/.

Does not touch storage — deduping against already-seen URLs happens in
storage.insert_new_articles.
"""

from datetime import UTC, datetime, timedelta

from bs4 import BeautifulSoup

from edenprairie_news.dates import parse_published
from edenprairie_news.models import Article

DEFAULT_KEYWORDS = ["eden prairie"]


def clean_html(raw_html: str) -> str:
    return BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)


def filter_recent(articles: list[Article], max_age_days: int, now: datetime | None = None) -> list[Article]:
    """Drop articles published more than max_age_days ago (0 = keep everything). An article with no readable date
    is kept: better a story of unknown age than a missed one."""
    if max_age_days <= 0:
        return articles
    cutoff = (now or datetime.now(UTC)) - timedelta(days=max_age_days)
    kept = []
    for a in articles:
        published = parse_published(a.published_at)
        if published is None or published >= cutoff:
            kept.append(a)
    return kept


def filter_relevant(articles: list[Article], keywords: list[str] = DEFAULT_KEYWORDS) -> list[Article]:
    """Keep only articles whose title or summary mentions one of the keywords.

    Useful for broad metro-area feeds; feeds that are already Eden Prairie-specific
    (e.g. a scoped Google News search) don't need this applied.
    """
    lowered_keywords = [k.lower() for k in keywords]
    return [
        a
        for a in articles
        if any(k in a.title.lower() or k in a.summary.lower() for k in lowered_keywords)
    ]
