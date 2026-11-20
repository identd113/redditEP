"""Spot obituary and funeral-home listings, so the page can hide them behind a toggle.

The Google News feed returns many of these (legacy.com, funeral homes), and they are not stories for the subreddit.
They are detected from the title, summary and source name at display time (not stored), so improving the words
below takes effect immediately for everything already collected. A news story that merely mentions a funeral will
sometimes be caught too; that is why they are hidden behind a toggle and never deleted.
"""

import re

_OBIT = re.compile(
    r"obituar|funeral home|funeral homes|cremation|legacy\.com|celebration of life|in loving memory|"
    r"service information|visitation|memorial service|passed away|tribute archive|dignity memorial",
    re.I,
)


def is_obituary(title: str, summary: str = "", source: str = "") -> bool:
    return bool(_OBIT.search(f"{title} {summary} {source}"))
