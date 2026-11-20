"""Orchestrates reddit_client -> flag_rules -> storage for the subreddit
moderation view. Mirrors how pipeline.py orchestrates the news-drafting
stages: this is the only module that calls both reddit_client and storage
together for the "current subreddit stories" domain.
"""

from edenprairie_news.config import get_reddit_config
from edenprairie_news.flag_rules import compute_flags
from edenprairie_news.reddit_client import get_recent_submissions, get_reddit
from edenprairie_news.storage import init_db, record_stats, upsert_subreddit_post


def sync_subreddit_posts() -> dict:
    init_db()
    reddit = get_reddit()
    posts = get_recent_submissions(reddit, limit=get_reddit_config().sync_limit)
    for post in posts:
        post["action_flags"] = compute_flags(post)
        upsert_subreddit_post(post)
        record_stats(post["fullname"].removeprefix("t3_"), post["score"], None, post["num_comments"])
    return {"synced": len(posts)}
