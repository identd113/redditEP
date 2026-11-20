"""Registry of per-feed parsing strategies.

`config/feeds.yaml` entries name a strategy via `parser: <name>`. Add a new
strategy by writing a `parse_entry(entry: RawEntry) -> Article` function in
a sibling module and registering it below -- no changes needed anywhere
else in the pipeline.
"""

import logging
from collections.abc import Callable

from edenprairie_news.feed_parsers import default
from edenprairie_news.models import Article, RawEntry

logger = logging.getLogger(__name__)

PARSERS: dict[str, Callable[[RawEntry], Article]] = {
    "default": default.parse_entry,
    # "events": a feed of events (a calendar as RSS). The pipeline sends it to the Events page through
    # event_feeds.py instead of drafting articles; the entry here only makes the name selectable on the Config page.
    "events": default.parse_entry,
}


def get_parser(name: str) -> Callable[[RawEntry], Article]:
    parser = PARSERS.get(name)
    if parser is None:
        logger.warning("Unknown feed parser %r, falling back to 'default'", name)
        return PARSERS["default"]
    return parser
