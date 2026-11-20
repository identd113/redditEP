from datetime import UTC, datetime, timedelta

import pytest

from edenprairie_news import stats, storage
from edenprairie_news.models import Article

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "FEEDS_PATH", tmp_path / "none.yaml")
    path = tmp_path / "t.db"
    storage.init_db(path)
    return path


def posted_article(db_path, url, post_id):
    storage.insert_new_articles([Article(url=url, source="S", title="T", summary="", published_at=None)], db_path)
    with storage.get_conn(db_path) as conn:
        article_id = conn.execute("SELECT id FROM articles WHERE url = ?", (url,)).fetchone()["id"]
    storage.link_posted(article_id, f"https://www.reddit.com/r/edenprairie/comments/{post_id}/t/", db_path)
    return article_id


def stat(post_id, score, comments, age_days=1, ratio=0.9, removed=False):
    return {"post_id": post_id, "score": score, "upvote_ratio": ratio, "num_comments": comments,
            "created_utc": (NOW - timedelta(days=age_days)).timestamp(), "removed": removed}


def comment(cid, body="nice"):
    return {"comment_id": cid, "author": "neighbor", "body": body, "score": 2, "created_utc": 1.0, "parent_id": "t3_x"}


def test_refresh_takes_a_snapshot_per_posted_article_and_keeps_the_comments(db_path):
    posted_article(db_path, "https://example.com/a", "aaa")
    out = stats.refresh_stats(lambda ids: [stat("aaa", 12, 2)], lambda pid: [comment("c1"), comment("c2")], now=NOW, db_path=db_path)
    assert out == {"tracked": 1, "snapshots": 1, "new_comments": 2, "removed": []}
    assert storage.get_stats_history("aaa", db_path)[0]["score"] == 12
    assert {c["comment_id"] for c in storage.get_comments("aaa", db_path)} == {"c1", "c2"}


def test_a_second_refresh_with_the_same_numbers_adds_neither_snapshots_nor_duplicate_comments(db_path):
    posted_article(db_path, "https://example.com/a", "aaa")
    args = dict(fetch_stats=lambda ids: [stat("aaa", 12, 2)], fetch_comments=lambda pid: [comment("c1"), comment("c2")], now=NOW, db_path=db_path)
    stats.refresh_stats(**args)
    out = stats.refresh_stats(**args)
    assert out["snapshots"] == 0 and out["new_comments"] == 0
    assert len(storage.get_comments("aaa", db_path)) == 2


def test_changed_numbers_make_a_new_snapshot_and_a_changed_comment_updates_in_place(db_path):
    posted_article(db_path, "https://example.com/a", "aaa")
    stats.refresh_stats(lambda ids: [stat("aaa", 12, 1)], lambda pid: [comment("c1", "first")], now=NOW, db_path=db_path)
    out = stats.refresh_stats(lambda ids: [stat("aaa", 30, 2)], lambda pid: [comment("c1", "edited"), comment("c2")], now=NOW, db_path=db_path)
    assert out["snapshots"] == 1 and out["new_comments"] == 1
    assert [h["score"] for h in storage.get_stats_history("aaa", db_path)] == [12, 30]
    assert {c["comment_id"]: c["body"] for c in storage.get_comments("aaa", db_path)}["c1"] == "edited"


def test_old_posts_get_numbers_but_no_comment_fetch_and_removed_posts_are_reported(db_path):
    posted_article(db_path, "https://example.com/old", "old")
    posted_article(db_path, "https://example.com/gone", "gone")
    asked = []
    out = stats.refresh_stats(lambda ids: [stat("old", 5, 9, age_days=30), stat("gone", 0, 0, removed=True)],
                              lambda pid: asked.append(pid) or [], now=NOW, db_path=db_path)
    assert out["snapshots"] == 2 and asked == [] and out["removed"] == ["gone"]


def test_nothing_posted_means_nothing_is_asked_of_reddit(db_path):
    def boom(*a):
        raise AssertionError("Reddit must not be called")

    assert stats.refresh_stats(boom, boom, now=NOW, db_path=db_path)["tracked"] == 0


def test_summary_shows_latest_numbers_and_the_change_over_24_hours():
    h = lambda hours_ago, score, comments: {"taken_at": (NOW - timedelta(hours=hours_ago)).isoformat(), "score": score,
                                           "upvote_ratio": 0.9, "num_comments": comments}
    history = [h(50, 3, 0), h(20, 10, 1), h(2, 25, 4)]
    s = storage.summarize_stats(history, now=NOW)
    assert (s["score"], s["num_comments"]) == (25, 4)
    assert (s["score_change_24h"], s["comments_change_24h"]) == (15, 3)  # against the oldest snapshot inside 24 h
    assert storage.summarize_stats([], now=NOW) is None


def test_readonly_client_needs_only_client_id_and_secret(monkeypatch):
    from edenprairie_news import reddit_client
    from edenprairie_news.config import RedditSettings

    cfg = RedditSettings(client_id="id", client_secret="sec", username=None, password=None, refresh_token=None,
                         user_agent="ua", subreddit="edenprairie", sync_limit=50)
    assert cfg.can_read and not cfg.is_configured
    monkeypatch.setattr(reddit_client, "get_reddit_config", lambda: cfg)
    reddit = reddit_client.get_reddit_readonly()  # PRAW builds the client without any network call
    assert reddit.read_only is True
    monkeypatch.setattr(reddit_client, "get_reddit_config", lambda: RedditSettings(None, None, None, None, None, "ua", "edenprairie", 50))
    with pytest.raises(RuntimeError, match="client id and secret"):
        reddit_client.get_reddit_readonly()
