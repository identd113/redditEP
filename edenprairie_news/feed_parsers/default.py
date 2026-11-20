"""The fallback parser strategy: trust the feed's own summary, just strip HTML.

Most feeds need nothing fancier than this. Source-specific parsers (e.g. one
that fetches the full article page because a feed only gives a truncated
summary) should live alongside this file and follow the same signature.
"""

from edenprairie_news.models import Article, RawEntry
from edenprairie_news.parser import clean_html


def parse_entry(entry: RawEntry) -> Article:
    return Article(
        url=entry.url,
        source=entry.source,
        title=entry.title.strip(),
        summary=clean_html(entry.summary_html),
        published_at=entry.published_at,
        author=entry.author,
        image_url=entry.image_url,
    )
