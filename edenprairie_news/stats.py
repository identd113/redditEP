"""How our posted articles are doing on Reddit: score, upvote ratio, comment count and the comments
themselves, kept as a history so the trend is visible.

Read-only. Needs only the script app's client id and secret (reddit_client.get_reddit_readonly): no account
logs in, and nothing here can post, vote or moderate. Like the rest of the tool it runs on demand (the
"Refresh stats" button, or `python -m edenprairie_news.stats`), not on a schedule.
"""

from datetime import UTC, datetime, timedelta

from edenprairie_news import reddit_client, storage

COMMENT_WINDOW = timedelta(days=14)  # comments are only fetched for posts this young; older ones just get numbers


def tracked_post_ids(db_path=storage.DB_PATH) -> list[str]:
    return [a.reddit_post_id for a in storage.get_by_status("posted", db_path) if a.reddit_post_id]


def refresh_stats(fetch_stats=None, fetch_comments=None, post_ids: list[str] | None = None,
                  now: datetime | None = None, db_path=storage.DB_PATH) -> dict:
    """Snapshot the numbers for every posted article and pull new comments for the recent ones.
    fetch_stats / fetch_comments default to the real Reddit calls and exist so tests can pass fakes."""
    ids = post_ids if post_ids is not None else tracked_post_ids(db_path)
    if not ids:
        return {"tracked": 0, "snapshots": 0, "new_comments": 0, "removed": []}
    if fetch_stats is None or fetch_comments is None:
        reddit = reddit_client.get_reddit_readonly()
        fetch_stats = fetch_stats or (lambda pids: reddit_client.fetch_post_stats(reddit, pids))
        fetch_comments = fetch_comments or (lambda pid: reddit_client.fetch_comments(reddit, pid))
    now = now or datetime.now(UTC)
    snapshots = new_comments = 0
    removed = []
    for stat in fetch_stats(ids):
        if storage.record_stats(stat["post_id"], stat["score"], stat["upvote_ratio"], stat["num_comments"], db_path):
            snapshots += 1
        if stat.get("removed"):
            removed.append(stat["post_id"])
        recent = now - datetime.fromtimestamp(stat["created_utc"], UTC) <= COMMENT_WINDOW
        if stat["num_comments"] and recent:
            new_comments += storage.upsert_comments(stat["post_id"], fetch_comments(stat["post_id"]), db_path)
    return {"tracked": len(ids), "snapshots": snapshots, "new_comments": new_comments, "removed": removed}


def main() -> None:
    summary = refresh_stats()
    print(f"Tracked {summary['tracked']} posts: {summary['snapshots']} new snapshots, {summary['new_comments']} new comments.")
    if summary["removed"]:
        print("Removed by Reddit or a moderator: " + ", ".join(summary["removed"]))


if __name__ == "__main__":
    main()
