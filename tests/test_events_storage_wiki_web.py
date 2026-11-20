from datetime import date

import pytest

from edenprairie_news import events, storage, wiki_page
from edenprairie_news.web import app as web


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "FEEDS_PATH", tmp_path / "none.yaml")
    path = tmp_path / "t.db"
    storage.init_db(path)
    return path


def candidate(**kw):
    base = dict(title="Open house", start_date=date(2026, 11, 21), start_time="18:00", end_time="20:00",
                location="Staring Lake Outdoor Center", location_source="venue", snippet="s")
    base.update(kw)
    return events.EventCandidate(**base)


def test_candidates_are_stored_as_suggestions_once_and_can_be_approved_edited_and_rejected(db_path):
    assert storage.insert_events(1, "https://example.com/a", [candidate(), candidate(start_time="19:00")], db_path) == 2
    assert storage.insert_events(1, "https://example.com/a", [candidate()], db_path) == 0  # same event again: ignored
    first, second = storage.get_events("suggested", db_path)
    storage.update_event(first["id"], {"location": "City Center", "start_time": "17:30", "bogus": "x"}, db_path)
    storage.set_event_status(first["id"], "approved", db_path)
    storage.set_event_status(second["id"], "rejected", db_path)
    approved = storage.get_events("approved", db_path)
    assert [(e["location"], e["start_time"]) for e in approved] == [("City Center", "17:30")]
    assert len(storage.get_events("rejected", db_path)) == 1 and storage.get_events("suggested", db_path) == []
    with pytest.raises(ValueError):
        storage.set_event_status(first["id"], "maybe", db_path)


def test_a_hand_added_event_is_approved_at_once(db_path):
    storage.add_event("Tree lighting", "2026-12-05", "17:00", "", "Staring Lake", "https://example.com/t", db_path)
    (e,) = storage.get_events("approved", db_path)
    assert e["title"] == "Tree lighting" and e["location_source"] == "manual"


def test_wiki_text_lists_only_upcoming_events_grouped_by_month_with_source_links():
    evs = [
        {"start_date": "2026-12-05", "end_date": "", "start_time": "17:00", "end_time": "", "title": "Tree lighting", "location": "Staring Lake", "source_url": "https://example.com/t"},
        {"start_date": "2026-11-21", "end_date": "", "start_time": "18:00", "end_time": "20:00", "title": "Open house", "location": "", "source_url": ""},
        {"start_date": "2026-11-01", "end_date": "", "start_time": "", "end_time": "", "title": "Already over", "location": "", "source_url": ""},
        {"start_date": "2026-11-20", "end_date": "2026-11-22", "start_time": "", "end_time": "", "title": "Still running", "location": "", "source_url": ""},
    ]
    text = wiki_page.render(evs, date(2026, 11, 19))
    assert "Already over" not in text and "Still running" in text
    assert text.index("## November 2026") < text.index("## December 2026")
    assert text.index("Still running") < text.index("Open house") < text.index("Tree lighting")
    assert "- **Sat, Nov 21 · 6 to 8 pm** · Open house" in text
    assert "- **Sat, Dec 5 · 5 pm** · Tree lighting · Staring Lake · [source](https://example.com/t)" in text
    assert "- **Fri, Nov 20-22** · Still running" in text
    assert "No upcoming events" in wiki_page.render([], date(2026, 11, 19))


@pytest.fixture
def client(monkeypatch):
    calls = []
    monkeypatch.setattr(storage, "set_event_status", lambda i, s, *a, **k: calls.append(("status", i, s)))
    monkeypatch.setattr(storage, "update_event", lambda i, f, *a, **k: calls.append(("edit", i, f)))
    monkeypatch.setattr(storage, "add_event", lambda *a, **k: calls.append(("add", a)))
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    c.calls = calls
    return c


def test_event_buttons_change_status_and_bad_dates_are_refused(client):
    client.post("/events/3/approve")
    client.post("/events/3/reject")
    client.post("/events/3/reopen")
    client.post("/events/3/explode")
    assert client.calls == [("status", 3, "approved"), ("status", 3, "rejected"), ("status", 3, "suggested")]
    client.calls.clear()
    assert "event_error=3" in client.post("/events/3/edit", data={"title": "x", "start_date": "tomorrow"}).headers["Location"]
    client.post("/events/3/edit", data={"title": "T", "start_date": "2026-12-01", "location": " Park "})
    assert client.calls[0][2]["location"] == "Park" and client.calls[0][2]["start_date"] == "2026-12-01"
    assert "event_error=new" in client.post("/events/add", data={"title": "x", "start_date": "nope"}).headers["Location"]
    client.post("/events/add", data={"title": "Fair", "start_date": "2026-12-02"})
    assert client.calls[-1][0] == "add"


def test_events_page_shows_review_items_the_wiki_text_and_the_no_account_message(client, monkeypatch):
    sug = {"id": 7, "title": "Open house", "start_date": "2026-11-21", "end_date": "", "start_time": "18:00", "end_time": "20:00",
           "location": "", "location_source": "", "source_url": "https://example.com/a", "snippet": "The open house is Nov. 21", "status": "suggested"}
    monkeypatch.setattr(storage, "get_events", lambda status, *a, **k: [sug] if status == "suggested" else [])
    html = client.get("/events").get_data(as_text=True)
    assert 'action="/events/7/approve"' in html and "no place found" in html and "No upcoming events" in html
    assert "/wiki/edit/events" in html
    from edenprairie_news.config import RedditSettings
    monkeypatch.setattr(web, "get_reddit_config", lambda: RedditSettings(None, None, None, None, None, "ua", "edenprairie", 50))
    loc = client.post("/events/wiki").headers["Location"]
    assert "wiki_error=No+Reddit+account" in loc
