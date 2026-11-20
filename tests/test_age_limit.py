from datetime import UTC, datetime, timedelta

import pytest

from edenprairie_news import config, parser, pipeline, storage
from edenprairie_news.models import Article, FeedSource, RawEntry
from edenprairie_news.web import app as web

NOW = datetime(2026, 11, 19, 18, 0, tzinfo=UTC)


def art(url, published):
    return Article(url=url, source="S", title=url, summary="", published_at=published)


def ago(days):
    return (NOW - timedelta(days=days)).isoformat()


def test_filter_recent_keeps_the_new_the_undated_and_the_unreadable_and_drops_the_old():
    items = [art("fresh", ago(2)), art("edge", ago(29)), art("old", ago(31)), art("ancient", "Mon, 12 Jul 2010 07:00:00 GMT"),
             art("undated", None), art("garbage", "sometime"), art("future", ago(-1))]
    kept = [a.url for a in parser.filter_recent(items, 30, NOW)]
    assert kept == ["fresh", "edge", "undated", "garbage", "future"]
    assert parser.filter_recent(items, 0, NOW) == items  # 0 turns the limit off


def test_the_limit_defaults_to_30_and_is_settable_and_survives_nonsense(monkeypatch):
    values = {}
    monkeypatch.setattr(storage, "get_setting", lambda k, *a, **kw: values.get(k))
    monkeypatch.delenv("MAX_ARTICLE_AGE_DAYS", raising=False)
    assert config.max_article_age_days() == 30
    values["max_article_age_days"] = "14"
    assert config.max_article_age_days() == 14
    values["max_article_age_days"] = "0"
    monkeypatch.setattr(storage, "get_setting", lambda k, *a, **kw: values.get(k) or None)  # "0" is stored text, so it is truthy here
    values["max_article_age_days"] = "-5"
    assert config.max_article_age_days() == 0  # negative means off, never an error
    values["max_article_age_days"] = "lots"
    assert config.max_article_age_days() == 30


def test_ingestion_skips_old_articles_using_the_configured_limit(monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "insert_new_articles", lambda articles, *a, **k: seen.extend(articles) or articles)
    monkeypatch.setattr(pipeline, "max_article_age_days", lambda: 30)
    recent = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    old = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    entries = [RawEntry(url="https://x/new", source="S", title="new", summary_html="", published_at=recent),
               RawEntry(url="https://x/old", source="S", title="old", summary_html="", published_at=old)]
    pipeline._process_source(FeedSource("F", "u", []), entries)
    assert [a.title for a in seen] == ["new"]
    seen.clear()
    monkeypatch.setattr(pipeline, "max_article_age_days", lambda: 0)
    pipeline._process_source(FeedSource("F", "u", []), entries)
    assert [a.title for a in seen] == ["new", "old"]


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "FEEDS_PATH", tmp_path / "none.yaml")
    path = tmp_path / "t.db"
    storage.init_db(path)
    return path


def test_cleanup_removes_only_old_drafts_and_they_can_be_restored(db_path):
    storage.insert_new_articles([art("https://x/old", ago(60)), art("https://x/new", ago(2)), art("https://x/undated", None),
                                 art("https://x/oldposted", ago(60)), art("https://x/oldrejected", ago(60))], db_path)
    with storage.get_conn(db_path) as conn:
        conn.execute("UPDATE articles SET status = 'drafted'")
        conn.execute("UPDATE articles SET status = 'posted' WHERE url = 'https://x/oldposted'")
        conn.execute("UPDATE articles SET status = 'rejected' WHERE url = 'https://x/oldrejected'")
    assert storage.count_drafts_older_than(30, db_path) == 1
    assert storage.remove_drafts_older_than(30, db_path) == 1
    assert {a.url for a in storage.get_by_status("drafted", db_path)} == {"https://x/new", "https://x/undated"}
    assert [a.url for a in storage.get_by_status("posted", db_path)] == ["https://x/oldposted"]
    removed = storage.get_by_status("removed", db_path)
    assert [a.url for a in removed] == ["https://x/old"]
    storage.restore_removed(removed[0].id, db_path)
    assert "https://x/old" in {a.url for a in storage.get_by_status("drafted", db_path)}
    assert storage.remove_drafts_older_than(0, db_path) == 0 and storage.count_drafts_older_than(0, db_path) == 0


def test_config_page_saves_the_limit_and_the_cleanup_button_reports(monkeypatch):
    saved = {}
    monkeypatch.setattr(storage, "set_setting", lambda k, v, *a, **kw: saved.__setitem__(k, v))
    monkeypatch.setattr(storage, "remove_drafts_older_than", lambda d, *a, **kw: 133)
    monkeypatch.setattr(web, "max_article_age_days", lambda: 30)
    monkeypatch.setattr(storage, "count_drafts_older_than", lambda d, *a, **kw: 133)
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    c.post("/config/age", data={"max_age_days": "14"})
    assert saved == {"max_article_age_days": "14"}
    c.post("/config/age", data={"max_age_days": "soon"})
    assert saved == {"max_article_age_days": "14"}  # not a number: ignored
    assert c.post("/config/age/cleanup").headers["Location"].endswith("cleaned=133")
    html = c.get("/config?cleaned=133").get_data(as_text=True)
    assert "Removed 133 old draft(s)" in html and 'value="30"' in html and "Remove the 133 stored drafts older than 30 days now" in html
