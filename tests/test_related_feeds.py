import pytest

from edenprairie_news import pipeline, storage
from edenprairie_news.models import FeedSource, RawEntry
from edenprairie_news.web import app as web


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "FEEDS_PATH", tmp_path / "none.yaml")
    path = tmp_path / "t.db"
    storage.init_db(path)
    return path


def entry(url, title):
    return RawEntry(url=url, source="KSTP", title=title, summary_html="<p>text</p>", published_at="2026-11-18T10:00:00+00:00")


def test_a_related_feed_marks_its_articles_as_nearby_and_a_normal_feed_does_not(monkeypatch, db_path):
    seen = []
    monkeypatch.setattr(pipeline, "insert_new_articles", lambda articles, *a, **k: seen.extend(articles) or articles)
    pipeline._process_source(FeedSource("KSTP: Chaska", "u1", ["related"]), [entry("https://x/1", "Chaska news")])
    pipeline._process_source(FeedSource("KSTP: Eden Prairie", "u2", []), [entry("https://x/2", "EP news")])
    assert {a.title: a.scope for a in seen} == {"Chaska news": "related", "EP news": "local"}


def test_scope_is_stored_and_old_databases_get_the_column(db_path):
    from edenprairie_news.models import Article

    storage.insert_new_articles([Article(url="https://x/1", source="S", title="T", summary="", published_at=None, scope="related")], db_path)
    storage.insert_new_articles([Article(url="https://x/2", source="S", title="U", summary="", published_at=None)], db_path)
    with storage.get_conn(db_path) as conn:
        conn.execute("UPDATE articles SET status = 'drafted'")
    assert {a.url: a.scope for a in storage.get_by_status("drafted", db_path)} == {"https://x/1": "related", "https://x/2": "local"}
    assert "scope" in storage.ARTICLES_MIGRATIONS


def test_related_articles_are_not_mined_for_events(monkeypatch):
    from edenprairie_news.models import Article

    calls = []
    monkeypatch.setattr(pipeline, "_suggest_events", lambda article, venues=None: calls.append(article.url))
    monkeypatch.setattr(pipeline, "list_feeds", lambda: [FeedSource("K", "u", ["related"])])
    monkeypatch.setattr(pipeline, "fetch_feed", lambda s: [entry("https://x/1", "Chaska fair Nov. 28 at 10 a.m.")])
    monkeypatch.setattr(pipeline, "insert_new_articles", lambda articles, *a, **k: articles)
    monkeypatch.setattr(pipeline, "_draft_by_url", lambda *a: None)
    monkeypatch.setattr(pipeline, "notify_new_drafts", lambda *a: None)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    pipeline.run_pipeline()
    assert calls == []


def test_index_lists_nearby_drafts_in_their_own_section(monkeypatch):
    from edenprairie_news.models import Article

    local = Article(id=1, url="https://x/1", source="S", title="Eden Prairie story", summary="", published_at=None, status="drafted")
    near = Article(id=2, url="https://x/2", source="KSTP", title="Chaska story", summary="", published_at=None, status="drafted", scope="related")
    by = {"drafted": [local, near], "sent": [], "posted": [], "rejected": []}
    monkeypatch.setattr(storage, "get_by_status", lambda s, *a, **k: by.get(s, []))
    monkeypatch.setattr(storage, "get_subreddit_posts", lambda **k: [])
    web.app.config["TESTING"] = True
    html = web.app.test_client().get("/").get_data(as_text=True)
    assert "Drafts (2)" in html and "Nearby cities (1)" in html
    assert html.index("Eden Prairie story") < html.index("Nearby cities") < html.index("Chaska story")
