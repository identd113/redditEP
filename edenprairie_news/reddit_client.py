"""Thin wrapper around PRAW for posting drafts and (optionally) mod queue actions.

Two ways to authenticate, both against a PRAW "script" app (see
.env.example): the password grant using the configured account's raw
username/password, or a refresh token obtained via the web UI's "Connect
via Reddit login" button (get_oauth_authorize_url()/exchange_oauth_code()
below implement that flow) -- preferred, since the account's password never
touches this app. get_reddit() picks whichever is configured, preferring
the refresh token. Either way the resulting token is scoped to everything
the account can already do on the subreddit -- no separate mod scope list
to request. Revoke/rotate by changing the account password, revoking the
app's access from the account's reddit.com/prefs/apps authorized-apps list,
or resetting the app's client secret.

The account does NOT need to be a subreddit moderator just to post drafts
(submit() only needs the account to not be blocked from posting) -- a
dedicated non-mod bot account is the intended setup, so it isn't tied to a
human mod's personal account. get_mod_queue()/approve()/remove() below do
require real moderator permissions, since those wrap PRAW's mod.* API; the
web UI only calls them when config.mod_queue_enabled() is on (off by
default) -- see the "Reddit API policy" section of CLAUDE.md for why.

Dedup strategy borrows from Epicfisher/reddit-rss-bot: don't only trust the
local DB, also ask Reddit directly whether a URL has already been submitted.
That catches posts made by other mods/bots outside this tool.
"""

import praw

from edenprairie_news.config import get_reddit_config


def get_reddit() -> praw.Reddit:
    reddit_config = get_reddit_config()
    if not reddit_config.is_configured:
        raise RuntimeError(
            "Reddit credentials are not set. Set them from the web UI's Config page, "
            "or copy .env.example to .env and fill it in."
        )
    if reddit_config.refresh_token:
        return praw.Reddit(
            client_id=reddit_config.client_id,
            client_secret=reddit_config.client_secret,
            refresh_token=reddit_config.refresh_token,
            user_agent=reddit_config.user_agent,
        )
    return praw.Reddit(
        client_id=reddit_config.client_id,
        client_secret=reddit_config.client_secret,
        username=reddit_config.username,
        password=reddit_config.password,
        user_agent=reddit_config.user_agent,
    )


def get_reddit_readonly() -> praw.Reddit:
    """For reading only (score, comments). With just the script app's client id and secret PRAW uses the
    app's own read-only access: no account logs in, so nothing here can post, vote or moderate. When a
    full account is configured that is used instead (it sees the same public data)."""
    reddit_config = get_reddit_config()
    if reddit_config.is_configured:
        return get_reddit()
    if not reddit_config.can_read:
        raise RuntimeError(
            "Reddit client id and secret are not set. Register a script app at reddit.com/prefs/apps and "
            "enter them on the Config page (or in .env)."
        )
    reddit = praw.Reddit(
        client_id=reddit_config.client_id,
        client_secret=reddit_config.client_secret,
        user_agent=reddit_config.user_agent,
    )
    reddit.read_only = True
    return reddit


def update_wiki(reddit: praw.Reddit, page: str, content: str, reason: str = "Update events") -> None:
    """Replace a wiki page of the subreddit. Needs the account to be allowed to edit the wiki (a moderator,
    or an approved wiki editor) and the wikiedit scope."""
    reddit.subreddit(get_reddit_config().subreddit).wiki[page].edit(content=content, reason=reason)


def fetch_post_stats(reddit: praw.Reddit, post_ids: list[str]) -> list[dict]:
    """[{post_id, score, upvote_ratio, num_comments, created_utc, removed}] for posts by id (no t3_ prefix). One request
    per 100 posts."""
    out = []
    for start in range(0, len(post_ids), 100):
        fullnames = [f"t3_{p}" for p in post_ids[start:start + 100]]
        for item in reddit.info(fullnames=fullnames):
            out.append({
                "post_id": item.id,
                "score": item.score,
                "upvote_ratio": getattr(item, "upvote_ratio", None),
                "num_comments": item.num_comments,
                "created_utc": item.created_utc,
                "removed": bool(getattr(item, "removed_by_category", None)),
            })
    return out


def fetch_comments(reddit: praw.Reddit, post_id: str, limit: int = 50) -> list[dict]:
    """Up to `limit` comments on a post, flattened; collapsed "load more" stubs are skipped (one request)."""
    submission = reddit.submission(id=post_id)
    submission.comments.replace_more(limit=0)
    out = []
    for comment in submission.comments.list()[:limit]:
        out.append({
            "comment_id": comment.id,
            "author": str(comment.author) if comment.author else "[deleted]",
            "body": comment.body,
            "score": comment.score,
            "created_utc": comment.created_utc,
            "parent_id": comment.parent_id,
        })
    return out


# Scopes cover everything this module actually calls: read (search/info/new),
# submit (submit_post), modposts (mod.modqueue/reports/unmoderated/approve/remove).
# identity is requested too but currently unused -- nothing surfaces the
# connected account's name back in the UI yet.
OAUTH_SCOPES = ["identity", "read", "submit", "modposts", "wikiedit", "wikiread"]


def get_oauth_authorize_url(redirect_uri: str, state: str) -> str:
    """Step 1 of the web-login flow: the reddit.com URL to send the user's
    browser to so they can grant this app access by logging in themselves,
    rather than this app ever holding the account's raw password."""
    reddit_config = get_reddit_config()
    reddit = praw.Reddit(
        client_id=reddit_config.client_id,
        client_secret=reddit_config.client_secret,
        redirect_uri=redirect_uri,
        user_agent=reddit_config.user_agent,
    )
    return reddit.auth.url(scopes=OAUTH_SCOPES, state=state, duration="permanent")


def exchange_oauth_code(redirect_uri: str, code: str) -> str:
    """Step 2: trade the one-time code Reddit's callback redirect included
    for a long-lived refresh token, which get_reddit() then uses instead of
    a stored username/password."""
    reddit_config = get_reddit_config()
    reddit = praw.Reddit(
        client_id=reddit_config.client_id,
        client_secret=reddit_config.client_secret,
        redirect_uri=redirect_uri,
        user_agent=reddit_config.user_agent,
    )
    refresh_token = reddit.auth.authorize(code)
    if not refresh_token:
        raise RuntimeError("Reddit didn't return a refresh token for this authorization.")
    return refresh_token


def already_posted_on_reddit(reddit: praw.Reddit, url: str) -> bool:
    subreddit = reddit.subreddit(get_reddit_config().subreddit)
    results = subreddit.search(f'url:"{url}"', sort="new", limit=1)
    return next(results, None) is not None


def submit_post(reddit: praw.Reddit, title: str, body: str) -> str:
    """Submits a self (text) post so the formatted summary + source link are visible
    inline, rather than a bare link post. Returns the new post's id."""
    subreddit = reddit.subreddit(get_reddit_config().subreddit)
    submission = subreddit.submit(title=title, selftext=body)
    return submission.id


def get_mod_queue(reddit: praw.Reddit, limit: int = 25) -> list[dict]:
    subreddit = reddit.subreddit(get_reddit_config().subreddit)
    return [_summarize(item) for item in subreddit.mod.modqueue(limit=limit)]


def get_reports(reddit: praw.Reddit, limit: int = 25) -> list[dict]:
    subreddit = reddit.subreddit(get_reddit_config().subreddit)
    return [_summarize(item) for item in subreddit.mod.reports(limit=limit)]


def get_unmoderated(reddit: praw.Reddit, limit: int = 25) -> list[dict]:
    subreddit = reddit.subreddit(get_reddit_config().subreddit)
    return [_summarize(item) for item in subreddit.mod.unmoderated(limit=limit)]


def get_recent_submissions(reddit: praw.Reddit, limit: int = 25) -> list[dict]:
    """Recent posts already live in the subreddit -- feeds the web UI's
    "current subreddit stories" view (as opposed to modqueue/reports, which
    are specifically flagged-for-mod-attention items)."""
    subreddit = reddit.subreddit(get_reddit_config().subreddit)
    return [_summarize_submission(item) for item in subreddit.new(limit=limit)]


def approve(reddit: praw.Reddit, fullname: str) -> None:
    """fullname is a Reddit "thing" id like t3_xxxxx (post) or t1_xxxxx (comment),
    as returned in _summarize()'s "fullname" field."""
    item = next(reddit.info([fullname]))
    item.mod.approve()


def remove(reddit: praw.Reddit, fullname: str, spam: bool = False) -> None:
    item = next(reddit.info([fullname]))
    item.mod.remove(spam=spam)


def _summarize_submission(item) -> dict:
    return {
        "fullname": item.fullname,
        "title": item.title,
        "author": str(item.author) if item.author else "[deleted]",
        "permalink": f"https://reddit.com{item.permalink}",
        "url": item.url,
        "created_utc": item.created_utc,
        "num_comments": item.num_comments,
        "score": item.score,
        "flair": item.link_flair_text,
        "num_reports": getattr(item, "num_reports", 0) or 0,
    }


def _summarize(item) -> dict:
    return {
        "id": item.id,
        "fullname": item.fullname,
        "kind": "comment" if item.fullname.startswith("t1_") else "submission",
        "title": getattr(item, "title", None),
        "body": getattr(item, "body", None),
        "author": str(item.author) if item.author else "[deleted]",
        "permalink": f"https://reddit.com{item.permalink}",
        "num_reports": getattr(item, "num_reports", 0),
        "created_utc": item.created_utc,
    }
