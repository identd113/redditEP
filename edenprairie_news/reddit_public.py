"""Read-only look at what is already in the subreddit, with no API key.

Reddit serves a public Atom feed of a subreddit's newest posts. It is rate
limited and sometimes refuses automated requests, so this never retries and
never raises into the web UI: the caller gets the reason and the page says so.
The feed is only used to notice that an article we sent has since been posted
(see matching.py); pasting the post's link by hand always works instead.
"""

import html
import re

import feedparser
import requests

# The standard form is /new.rss. The first version used /new/.rss, which Reddit answered with 404 (checked
# 2026-11-19, before it started rate limiting this address with 429); /new.rss itself is not yet confirmed live.
FEED_URL = "https://www.reddit.com/r/{subreddit}/new.rss?limit={limit}"
_HREF = re.compile(r"""href=["']([^"']+)["']""", re.I)


class RedditUnavailable(Exception):
    """Reddit refused or could not be reached; str() says why, in plain words."""


def links_in(content_html: str) -> list[str]:
    return [html.unescape(u) for u in _HREF.findall(content_html or "")]


def parse_feed(text: str) -> list[dict]:
    """Atom text -> [{fullname, title, author, permalink, urls}] for each post."""
    feed = feedparser.parse(text)
    posts = []
    for entry in feed.entries:
        content = " ".join(c.get("value", "") for c in entry.get("content", [])) or entry.get("summary", "")
        permalink = entry.get("link", "")
        urls = [u for u in links_in(content) if "reddit.com" not in u or "/comments/" not in u]
        posts.append(
            {
                "fullname": entry.get("id", ""),
                "title": entry.get("title", ""),
                "author": (entry.get("author", "") or "").removeprefix("/u/"),
                "permalink": permalink,
                "urls": urls,
            }
        )
    return posts


def fetch_recent_posts(subreddit: str, user_agent: str, limit: int = 50) -> list[dict]:
    try:
        response = requests.get(
            FEED_URL.format(subreddit=subreddit, limit=limit),
            headers={"User-Agent": user_agent},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RedditUnavailable(f"could not reach Reddit ({type(exc).__name__})") from exc
    if response.status_code == 429:
        raise RedditUnavailable("Reddit is rate limiting this address (429); try again in a few minutes")
    if response.status_code != 200:
        raise RedditUnavailable(f"Reddit answered HTTP {response.status_code} for the subreddit feed")
    return parse_feed(response.text)
