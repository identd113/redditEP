import pytest

from edenprairie_news import storage


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    storage.init_db(path)
    return path


def make_post(**overrides) -> dict:
    defaults = dict(
        fullname="t3_abc123",
        title="City council meeting recap",
        author="someuser",
        permalink="https://reddit.com/r/edenprairie/comments/abc123",
        url="https://reddit.com/r/edenprairie/comments/abc123",
        created_utc=1754000000.0,
        num_comments=3,
        score=10,
        flair="Announcement",
        num_reports=0,
        action_flags=[],
    )
    defaults.update(overrides)
    return defaults


def test_upsert_then_get_roundtrips(db_path):
    storage.upsert_subreddit_post(make_post(), db_path)
    posts = storage.get_subreddit_posts(db_path=db_path)
    assert len(posts) == 1
    assert posts[0]["fullname"] == "t3_abc123"
    assert posts[0]["tags"] == []


def test_resync_preserves_manually_applied_tags(db_path):
    storage.upsert_subreddit_post(make_post(), db_path)
    storage.add_post_tag("t3_abc123", "needs-followup", db_path)

    # Re-sync with fresh data (e.g. updated score) - tags must survive.
    storage.upsert_subreddit_post(make_post(score=25), db_path)

    posts = storage.get_subreddit_posts(db_path=db_path)
    assert posts[0]["score"] == 25
    assert posts[0]["tags"] == ["needs-followup"]


def test_hidden_tag_excludes_from_default_view(db_path):
    storage.upsert_subreddit_post(make_post(), db_path)
    storage.add_post_tag("t3_abc123", "hidden", db_path)

    assert storage.get_subreddit_posts(db_path=db_path) == []
    visible_with_hidden = storage.get_subreddit_posts(include_hidden=True, db_path=db_path)
    assert len(visible_with_hidden) == 1

    storage.remove_post_tag("t3_abc123", "hidden", db_path)
    assert len(storage.get_subreddit_posts(db_path=db_path)) == 1
