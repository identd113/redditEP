import pytest

from edenprairie_news import matching, storage
from edenprairie_news.models import Article


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "FEEDS_PATH", tmp_path / "none.yaml")
    path = tmp_path / "t.db"
    storage.init_db(path)
    return path


def add(db_path, url, status="drafted"):
    storage.insert_new_articles([Article(url=url, source="Sun Sailor", title="T " + url, summary="", published_at=None)], db_path)
    with storage.get_conn(db_path) as conn:
        article_id = conn.execute("SELECT id FROM articles WHERE url = ?", (url,)).fetchone()["id"]
    storage.save_draft(article_id, "title", "body", db_path)
    if status == "sent":
        storage.mark_sent(article_id, db_path)
    return article_id


def test_sending_takes_a_draft_out_of_the_drafts_and_reopening_puts_it_back(db_path):
    article_id = add(db_path, "https://example.com/a")
    storage.mark_sent(article_id, db_path)
    assert [a.id for a in storage.get_by_status("sent", db_path)] == [article_id]
    assert storage.get_by_status("drafted", db_path) == []
    assert storage.get_by_status("sent", db_path)[0].sent_at
    storage.reopen_draft(article_id, db_path)
    assert [a.id for a in storage.get_by_status("drafted", db_path)] == [article_id]


def test_a_post_that_contains_the_article_link_is_matched_and_stays_visible(db_path):
    article_id = add(db_path, "https://example.com/news/story", status="sent")
    post = {"permalink": "https://www.reddit.com/r/edenprairie/comments/1abc2d/title/",
            "urls": ["https://example.com/news/story/?utm_source=x"]}
    assert matching.match_posts([post], db_path) == [(article_id, post["permalink"])]
    posted = storage.get_by_status("posted", db_path)
    assert posted[0].reddit_url == post["permalink"] and posted[0].reddit_post_id == "1abc2d"
    assert matching.match_posts([post], db_path) == []  # a second pass finds nothing left to match


def test_a_link_post_to_the_article_matches_too(db_path):
    article_id = add(db_path, "https://example.com/x")
    post = {"permalink": "https://www.reddit.com/r/edenprairie/comments/9zz/x/", "url": "https://example.com/x"}
    assert [m[0] for m in matching.match_posts([post], db_path)] == [article_id]


def test_unrelated_posts_and_rejected_articles_are_not_touched(db_path):
    article_id = add(db_path, "https://example.com/a", status="sent")
    other = add(db_path, "https://example.com/b")
    storage.mark_rejected(other, db_path)
    posts = [
        {"permalink": "https://www.reddit.com/r/edenprairie/comments/1/", "urls": ["https://example.com/other"]},
        {"permalink": "https://www.reddit.com/r/edenprairie/comments/2/", "urls": ["https://example.com/b"]},
    ]
    assert matching.match_posts(posts, db_path) == []
    assert [a.id for a in storage.get_by_status("sent", db_path)] == [article_id]


def test_pasting_a_link_by_hand_marks_it_posted(db_path):
    article_id = add(db_path, "https://example.com/a", status="sent")
    storage.link_posted(article_id, "https://www.reddit.com/r/edenprairie/comments/Q1W2/hi/", db_path)
    a = storage.get_by_id(article_id, db_path)
    assert a.status == "posted" and a.reddit_post_id == "q1w2"
