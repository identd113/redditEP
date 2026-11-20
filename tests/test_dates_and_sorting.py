from datetime import UTC, datetime, timedelta

import pytest

from edenprairie_news import dates, storage
from edenprairie_news.models import Article

NOW = datetime(2026, 11, 19, 18, 0, tzinfo=UTC)  # noon in Eden Prairie


def test_both_feed_date_formats_normalise_to_the_same_utc_text():
    assert dates.normalize_published("Thu, 19 Nov 2026 03:23:29 GMT") == "2026-11-19T03:23:29+00:00"
    assert dates.normalize_published("2026-11-19T03:23:29+00:00") == "2026-11-19T03:23:29+00:00"
    assert dates.normalize_published("2026-11-18T21:23:29-06:00") == "2026-11-19T03:23:29+00:00"  # other zones become UTC
    assert dates.normalize_published("2026-11-19T03:23:29Z") == "2026-11-19T03:23:29+00:00"
    assert dates.normalize_published("2026-11-19T03:23:29.987+00:00") == "2026-11-19T03:23:29+00:00"
    assert dates.normalize_published("last Tuesday") is None and dates.normalize_published("") is None and dates.normalize_published(None) is None


@pytest.mark.parametrize("delta,text", [
    (timedelta(seconds=30), "just now"), (timedelta(minutes=1, seconds=40), "1 minute ago"), (timedelta(minutes=45), "45 minutes ago"),
    (timedelta(hours=1, minutes=5), "1 hour ago"), (timedelta(hours=5), "5 hours ago"), (timedelta(days=1, hours=2), "1 day ago"),
    (timedelta(days=9), "9 days ago"), (timedelta(days=21), "3 weeks ago"), (timedelta(days=100), "3 months ago"),
    (timedelta(days=800), "2 years ago"), (timedelta(hours=-2), "upcoming"),
])
def test_time_ago_in_plain_words(delta, text):
    assert dates.time_ago(NOW - delta, NOW) == text


def test_label_shows_eden_prairie_time_and_the_year_only_when_it_matters():
    assert dates.posted_label("2026-11-19T15:23:00+00:00", NOW) == "Thu, Nov 19, 9:23 am · 2 hours ago"  # 15:23 UTC = 9:23 am CST
    assert dates.posted_label("2026-11-19T21:00:00+00:00", NOW) == "Thu, Nov 19, 3 pm · upcoming"
    assert dates.posted_label("Mon, 12 Jul 2010 07:00:00 GMT", NOW) == "Jul 12, 2010 · 16 years ago"
    assert dates.posted_label("2026-01-08T08:00:00+00:00", NOW) == "Jan 8, 2026 · 10 months ago"  # over ~300 days old: the date, not the time
    assert dates.posted_label("2026-09-01T08:00:00+00:00", NOW) == "Tue, Sep 1, 3 am · 2 months ago"
    assert dates.posted_label(None, NOW) == "date unknown" and dates.posted_label("garbage", NOW) == "date unknown"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "FEEDS_PATH", tmp_path / "none.yaml")
    path = tmp_path / "t.db"
    storage.init_db(path)
    return path


def make(url, published):
    return Article(url=url, source="S", title=url, summary="", published_at=published)


def test_lists_are_newest_posted_first_whatever_the_feed_date_format(db_path):
    storage.insert_new_articles([
        make("https://x/old", "Mon, 12 Jul 2010 07:00:00 GMT"),
        make("https://x/newest", "2026-11-19T03:23:29+00:00"),
        make("https://x/middle", "Wed, 11 Nov 2026 21:27:25 GMT"),
        make("https://x/undated", None),
    ], db_path)
    with storage.get_conn(db_path) as conn:
        conn.execute("UPDATE articles SET status = 'drafted'")
    order = [a.url.rsplit("/", 1)[1] for a in storage.get_by_status("drafted", db_path)]
    assert order.index("newest") < order.index("middle") < order.index("old")
    assert order.index("undated") < order.index("old")  # no date: ranked by when we first saw it, so it is recent


def test_old_databases_get_their_raw_dates_rewritten_once(db_path):
    with storage.get_conn(db_path) as conn:
        conn.execute("INSERT INTO articles (url, source, title, fetched_at, status, updated_at, published_at) VALUES "
                     "('u1','S','t','2026-11-19T00:00:00+00:00','drafted','x','Thu, 19 Nov 2026 03:23:29 GMT'), "
                     "('u2','S','t','2026-11-19T00:00:00+00:00','drafted','x','nonsense'), "
                     "('u3','S','t','2026-11-19T00:00:00+00:00','drafted','x','2026-11-18T10:00:00+00:00')")
    storage.init_db(db_path)
    storage.init_db(db_path)  # idempotent
    with storage.get_conn(db_path) as conn:
        got = {r["url"]: r["published_at"] for r in conn.execute("SELECT url, published_at FROM articles")}
    assert got == {"u1": "2026-11-19T03:23:29+00:00", "u2": None, "u3": "2026-11-18T10:00:00+00:00"}


def test_the_page_shows_the_posted_date_and_nearby_items_stay_below_eden_prairie(monkeypatch):
    from edenprairie_news.web import app as web

    fresh = (datetime.now(UTC) - timedelta(hours=3)).replace(microsecond=0).isoformat()
    local = Article(id=1, url="https://x/1", source="S", title="Eden Prairie story", summary="", published_at="2026-01-02T10:00:00+00:00", status="drafted")
    near = Article(id=2, url="https://x/2", source="KSTP", title="Chaska story", summary="", published_at=fresh, status="drafted", scope="related")
    by = {"drafted": [local, near], "sent": [], "posted": [], "rejected": []}
    monkeypatch.setattr(storage, "get_by_status", lambda s, *a, **k: by.get(s, []))
    monkeypatch.setattr(storage, "get_subreddit_posts", lambda **k: [])
    web.app.config["TESTING"] = True
    html = web.app.test_client().get("/").get_data(as_text=True)
    assert "3 hours ago" in html and "Jan 2, 2026" in html
    assert html.index("Eden Prairie story") < html.index("Chaska story")  # primary first even though the nearby one is newer
