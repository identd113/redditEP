from datetime import date

import pytest

from edenprairie_news import storage
from edenprairie_news.web import app as web


def ev(i, status, **kw):
    base = {"id": i, "title": f"Event {i}", "start_date": "2099-12-05", "end_date": "", "start_time": "18:00", "end_time": "20:00",
            "location": "Staring Lake", "location_source": "feed", "source_url": f"https://x/events/{i}/", "snippet": "s", "status": status}
    base.update(kw)
    return base


@pytest.fixture
def client(monkeypatch):
    calls = []
    store = {"suggested": [ev(1, "suggested")], "approved": [ev(2, "approved"), ev(3, "approved", start_date="2020-01-02", title="Old one")],
             "rejected": [ev(4, "rejected", title="Gone event")]}
    monkeypatch.setattr(storage, "get_events", lambda status, *a, **k: store.get(status, []))
    monkeypatch.setattr(storage, "set_event_status", lambda i, s, *a, **k: calls.append(("status", i, s)))
    monkeypatch.setattr(storage, "update_event", lambda i, f, *a, **k: calls.append(("update", i, f)))
    monkeypatch.setattr(storage, "add_event", lambda *a, **k: calls.append(("add", a)))
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    c.calls = calls
    return c


def test_every_event_has_a_remove_button_and_removed_ones_can_be_restored(client):
    html = client.get("/events").get_data(as_text=True)
    for i in (1, 2, 3):
        assert f'action="/events/{i}/remove"' in html, i
    assert 'action="/events/4/restore"' in html and "Removed events (1)" in html and "will not be suggested again" in html
    assert "Not an event" not in html and "Not events" not in html
    assert html.count('class="danger" data-help-key="Remove event"') == 3


def test_remove_and_restore_change_the_status_that_blocks_a_comeback(client):
    client.post("/events/2/remove")
    client.post("/events/4/restore")
    client.post("/events/2/reject")  # the old names still work
    client.post("/events/2/reopen")
    assert client.calls == [("status", 2, "rejected"), ("status", 4, "suggested"), ("status", 2, "rejected"), ("status", 2, "suggested")]


def test_events_already_on_the_calendar_can_be_edited_and_show_their_wiki_line(client):
    html = client.get("/events").get_data(as_text=True)
    assert html.count("Edit this event") == 2  # both approved events
    assert 'action="/events/2/edit"' in html and 'action="/events/3/edit"' in html
    weekday = date(2099, 12, 5).strftime("%a")
    assert f"**{weekday}, Dec 5 · 6 to 8 pm** · Event 2 · Staring Lake · [source](https://x/events/2/)" in html
    assert html.count("past</span>") == 1  # the old one is marked, not hidden


def test_saving_an_edit_keeps_the_website_and_reports_saved(client):
    r = client.post("/events/2/edit", data={"title": " Rotary ", "start_date": "2026-12-05", "end_date": "2026-12-07", "start_time": "17:30",
                                            "end_time": "19:00", "location": "City Center", "source_url": "https://example.com/r"})
    assert "saved=2" in r.headers["Location"]
    update = client.calls[0]
    assert update[:2] == ("update", 2) and update[2] == {"title": "Rotary", "start_date": "2026-12-05", "end_date": "2026-12-07", "start_time": "17:30",
                                                          "end_time": "19:00", "location": "City Center", "source_url": "https://example.com/r"}


@pytest.mark.parametrize("bad,words", [
    ({"start_date": "tomorrow"}, "date is not valid"),
    ({"end_date": "2026-12-01"}, "before the first day"),
    ({"end_date": "soon"}, "last day is not valid"),
    ({"start_time": "6pm"}, "start time must look like 18:30"),
    ({"end_time": "25:00"}, "end time must look like 18:30"),
    ({"title": "  "}, "needs a name"),
])
def test_a_bad_edit_is_refused_with_the_reason_and_changes_nothing(client, bad, words):
    data = {"title": "T", "start_date": "2026-12-05", "end_date": "", "start_time": "18:00", "end_time": "", "location": "", "source_url": ""}
    data.update(bad)
    r = client.post("/events/2/edit", data=data)
    assert "event_error=2" in r.headers["Location"] and client.calls == []
    page = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "Not saved:" in page and words in page


def test_adding_by_hand_uses_the_same_checks(client):
    bad = client.post("/events/add", data={"title": "Fair", "start_date": "2026-12-05", "start_time": "7pm"})
    assert "event_error=new" in bad.headers["Location"] and client.calls == []
    client.post("/events/add", data={"title": "Fair", "start_date": "2026-12-05", "start_time": "19:00", "location": "Park"})
    assert client.calls == [("add", ("Fair", "2026-12-05", "19:00", "", "Park", ""))]
