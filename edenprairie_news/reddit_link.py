"""Pure helpers for the "post it yourself" flow: build the pre-filled Reddit
submit link, read a Reddit post id out of a pasted link, and normalise article
URLs so the same story matches however it was written. No I/O.
"""

import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

# Query parameters that only track where a click came from; they never change the page.
_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|ref|ref_src|cmpid)$", re.I)
_POST_ID = re.compile(r"/comments/([a-z0-9]+)", re.I)
_SHORT_ID = re.compile(r"^(?:https?://)?redd\.it/([a-z0-9]+)", re.I)


def submit_url(subreddit: str, title: str, body: str) -> str:
    """Reddit's own submit page for r/<subreddit>, pre-filled with a text post. The person
    checks it and presses Post, so the post is theirs and no API key is involved."""
    query = urlencode(
        {"type": "TEXT", "selftext": "true", "title": title, "text": body},
        quote_via=quote,
    )
    return f"https://www.reddit.com/r/{subreddit}/submit?{query}"


def post_id_from_url(url: str) -> str | None:
    """'https://www.reddit.com/r/edenprairie/comments/1abc2d/title/' -> '1abc2d'; also accepts redd.it links."""
    url = (url or "").strip()
    m = _POST_ID.search(url) or _SHORT_ID.match(url)
    return m.group(1).lower() if m else None


def permalink(subreddit: str, post_id: str) -> str:
    return f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/"


def normalize_url(url: str) -> str:
    """Lower-case host, https, no fragment, no tracking parameters, no trailing slash, sorted query."""
    parts = urlsplit((url or "").strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k))
    path = parts.path.rstrip("/") or ""
    return urlunsplit(("https", host, path, urlencode(query), ""))
