from datetime import date

import pytest

from edenprairie_news import event_feeds, pipeline, storage
from edenprairie_news.models import FeedSource

TODAY = date(2026, 11, 19)


def item(title, link, pub, desc="Join us."):
    return f"<item><title>{title}</title><link>{link}</link><pubDate>{pub}</pubDate><description><![CDATA[<p>{desc}</p>]]></description></item>"


def feed(*items):
    return '<?xml version="1.0"?><rss version="2.0"><channel><title>Events</title>' + "".join(items) + "</channel></rss>"


PAGE = """<html><script type="application/ld+json">{"@context":"https://schema.org","@type":"Event","name":"Story Time",
"startDate":"2026-11-19T10:30:00-06:00","endDate":"2026-11-19T11:00:00-06:00",
"location":{"@type":"Place","name":"University of MN Landscape Arboretum","address":"3675 Arboretum Dr"}}</script></html>"""


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "FEEDS_PATH", tmp_path / "none.yaml")
    path = tmp_path / "t.db"
    storage.init_db(path)
    return path


def run(xml, db_path, fetch=lambda url: {}, today=TODAY):
    return event_feeds.import_events(xml, today=today, fetch_page=fetch, pause=0, db_path=db_path)


def test_the_feed_start_time_is_read_in_local_time_whatever_zone_it_is_written_in():
    (a,) = event_feeds.parse_items(feed(item("A", "https://x/events/a/?occurrence=2026-11-19", "Thu, 19 Nov 2026 09:30:00 -0600")))
    (b,) = event_feeds.parse_items(feed(item("B", "https://x/events/b/", "Thu, 19 Nov 2026 15:30:00 +0000")))
    assert (a.start.strftime("%Y-%m-%d %H:%M"), b.start.strftime("%Y-%m-%d %H:%M")) == ("2026-11-19 09:30", "2026-11-19 09:30")
    assert a.base_url == "https://x/events/a/"  # the occurrence is dropped: the event is one thing


def test_event_page_schema_data_gives_the_end_time_and_the_place():
    d = event_feeds.parse_event_page(PAGE)
    assert d["end"].strftime("%H:%M") == "11:00" and d["place"] == "University of MN Landscape Arboretum" and d["address"] == "3675 Arboretum Dr"
    assert event_feeds.parse_event_page("<html>nothing</html>") == {}


def test_a_new_event_becomes_a_suggestion_with_time_end_and_place(db_path):
    xml = feed(item("Story Time at the Arb", "https://x/events/story/?occurrence=2026-11-19", "Thu, 19 Nov 2026 10:30:00 -0600"))
    out = run(xml, db_path, fetch=lambda url: event_feeds.parse_event_page(PAGE))
    assert out["new"] == 1
    (e,) = storage.get_events("suggested", db_path)
    assert (e["start_date"], e["start_time"], e["end_time"]) == ("2026-11-19", "10:30", "11:00")
    assert e["location"] == "University of MN Landscape Arboretum, 3675 Arboretum Dr" and e["source_url"] == "https://x/events/story/"
    assert e["article_id"] is None and e["status"] == "suggested"


def test_a_recurring_event_is_one_suggestion_for_its_next_occurrence_and_returns_after_it_passes(db_path):
    link = "https://x/events/santa/"
    xml = feed(item("Santa", link + "?occurrence=2026-11-20", "Fri, 20 Nov 2026 12:00:00 -0600"),
               item("Santa", link + "?occurrence=2026-11-19", "Thu, 19 Nov 2026 12:00:00 -0600"),
               item("Santa", link + "?occurrence=2026-11-21", "Sat, 21 Nov 2026 12:00:00 -0600"))
    assert run(xml, db_path)["new"] == 1
    assert [e["start_date"] for e in storage.get_events("suggested", db_path)] == ["2026-11-19"]  # the next one
    again = run(xml, db_path)
    assert again["new"] == 0 and again["skipped_known"] >= 1  # nothing doubled on a second run
    later = feed(item("Santa", link + "?occurrence=2026-11-26", "Thu, 26 Nov 2026 12:00:00 -0600"))
    assert run(later, db_path, today=date(2026, 11, 22))["new"] == 1  # the earlier one has passed: the next is suggested


def test_a_dismissed_event_is_never_suggested_again(db_path):
    xml = feed(item("Rotary", "https://x/events/rotary/?occurrence=2026-11-19", "Thu, 19 Nov 2026 12:00:00 -0600"))
    run(xml, db_path)
    (e,) = storage.get_events("suggested", db_path)
    storage.set_event_status(e["id"], "rejected", db_path)
    later = feed(item("Rotary", "https://x/events/rotary/?occurrence=2026-12-03", "Thu, 03 Dec 2026 12:00:00 -0600"))
    assert run(later, db_path, today=date(2026, 12, 1))["new"] == 0


def test_past_events_and_events_in_other_towns_are_skipped_and_counted(db_path):
    xml = feed(item("Yesterday", "https://x/events/old/", "Wed, 18 Nov 2026 12:00:00 -0600"),
               item("Gold Buying Event", "https://x/events/gold/", "Thu, 19 Nov 2026 10:00:00 -0600",
                    "Sell your gold in Park Rapids, MN - two days only"),
               item("Library storytime in Eden Prairie, MN", "https://x/events/lib/", "Thu, 19 Nov 2026 11:00:00 -0600"),
               item("Open house", "https://x/events/open/", "Thu, 19 Nov 2026 11:00:00 -0600", "Tour the building at 8080 Mitchell Rd."))
    out = run(xml, db_path)
    assert (out["skipped_past"], out["skipped_elsewhere"], out["new"]) == (1, 1, 2)
    assert {e["title"] for e in storage.get_events("suggested", db_path)} == {"Library storytime in Eden Prairie, MN", "Open house"}


def test_an_unreadable_event_page_does_not_lose_the_event(db_path):
    def broken(url):
        raise OSError("site down")

    xml = feed(item("Rotary", "https://x/events/rotary/", "Thu, 19 Nov 2026 12:00:00 -0600"))
    assert run(xml, db_path, fetch=broken)["new"] == 1
    (e,) = storage.get_events("suggested", db_path)
    assert e["start_time"] == "12:00" and e["location"] == ""


def test_at_most_a_set_number_of_event_pages_are_fetched_per_run(db_path, monkeypatch):
    monkeypatch.setattr(event_feeds, "MAX_PAGE_LOOKUPS", 3)
    xml = feed(*[item(f"E{i}", f"https://x/events/e{i}/", "Thu, 19 Nov 2026 12:00:00 -0600") for i in range(6)])
    fetched = []
    out = run(xml, db_path, fetch=lambda url: fetched.append(url) or {})
    assert out["new"] == 6 and len(fetched) == 3  # all stored, only three pages read


def test_the_pipeline_sends_an_events_feed_to_the_importer_and_drafts_no_articles(monkeypatch):
    called = []
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(pipeline, "list_feeds", lambda: [FeedSource("Events", "https://x/events/feed/", [], "events")])
    monkeypatch.setattr(pipeline, "fetch_feed", lambda s: called.append("article reader used") or [])
    monkeypatch.setattr(event_feeds, "import_from_url", lambda url: called.append(url) or {"new": 4})
    monkeypatch.setattr(pipeline, "notify_new_drafts", lambda *a: None)
    out = pipeline.run_pipeline()
    assert called == ["https://x/events/feed/"] and out == {"fetched": 0, "new": 0, "events": 4}


def test_a_failing_events_feed_never_stops_the_run(monkeypatch):
    def boom(url):
        raise OSError("down")

    monkeypatch.setattr(event_feeds, "import_from_url", boom)
    assert pipeline._import_event_feed(FeedSource("Events", "https://x/events/feed/", [], "events")) == 0


def test_an_end_time_that_is_not_after_the_start_is_dropped_and_a_glued_address_is_separated(db_path):
    page = ('<script type="application/ld+json">{"@type":"Event","startDate":"2026-11-19T09:30:00-06:00",'
            '"endDate":"2026-11-19T00:00:00-06:00","location":{"name":"Helping Paws","address":"6569 City W PkwyEden Prairie"}}</script>')
    xml = feed(item("Photos", "https://x/events/photos/", "Thu, 19 Nov 2026 09:30:00 -0600"))
    run(xml, db_path, fetch=lambda url: event_feeds.parse_event_page(page))
    (e,) = storage.get_events("suggested", db_path)
    assert e["end_time"] == "" and e["location"] == "Helping Paws, 6569 City W Pkwy, Eden Prairie"
