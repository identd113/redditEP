from urllib.parse import parse_qs, urlsplit

import pytest

from edenprairie_news import storage
from edenprairie_news.models import Article
from edenprairie_news.web import app as web

EVENT = {"id": 11, "article_id": 5, "title": "Open house", "start_date": "2026-11-21", "end_date": "", "start_time": "18:00",
         "end_time": "20:00", "location": "Staring Lake Outdoor Center", "location_source": "venue",
         "source_url": "https://example.com/a", "snippet": "The open house is Saturday, Nov. 21", "status": "suggested"}
NO_PLACE = dict(EVENT, id=12, title="Other thing", start_time="", end_time="", location="", location_source="", source_url="")
APPROVED = dict(EVENT, id=13, title="Already there", status="approved")


@pytest.fixture
def client(monkeypatch):
    calls = []
    state = {"events": [dict(EVENT), dict(NO_PLACE), dict(APPROVED)]}
    article = Article(id=5, url="https://example.com/a", source="Sun Sailor", title="T", summary="", published_at="2026-11-18T10:00:00+00:00",
                      status="drafted", post_title="Council votes", post_body="Body text", scope="local")
    monkeypatch.setattr(storage, "get_by_id", lambda i, *a, **k: article if i == 5 else None)
    monkeypatch.setattr(storage, "get_events_for_article", lambda i, *a, **k: state["events"])
    monkeypatch.setattr(storage, "update_event", lambda i, f, *a, **k: calls.append(("update", i, f)))
    monkeypatch.setattr(storage, "set_event_status", lambda i, s, *a, **k: calls.append(("status", i, s)))
    monkeypatch.setattr(storage, "add_event", lambda *a, **k: calls.append(("add", a)))
    monkeypatch.setattr(storage, "mark_sent", lambda i, *a, **k: calls.append(("sent", i)))
    import edenprairie_news.pipeline as pipeline
    monkeypatch.setattr(pipeline, "_suggest_events", lambda a, v=None: calls.append(("rescan", a.id)))
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    c.calls, c.state, c.article = calls, state, article
    return c


def test_the_preview_shows_what_when_where_website_and_the_wiki_line(client):
    html = client.get("/articles/5/post").get_data(as_text=True)
    assert ("rescan", 5) in client.calls  # looks at the article again first
    assert "Council votes" in html and "Body text" in html  # the Reddit post itself
    assert 'value="Open house"' in html and 'value="2026-11-21"' in html and 'value="Staring Lake Outdoor Center"' in html
    assert 'value="https://example.com/a"' in html
    assert "**Sat, Nov 21 · 6 to 8 pm** · Open house · Staring Lake Outdoor Center · [source](https://example.com/a)" in html
    assert "no place found" in html and "Already on the calendar" in html and "Add an event by hand" in html


def test_a_nearby_article_is_not_rescanned_for_events(client):
    client.article.scope = "related"
    client.get("/articles/5/post")
    assert ("rescan", 5) not in client.calls


def test_with_no_events_found_the_page_says_so_and_still_lets_the_person_post(client):
    client.state["events"] = []
    html = client.get("/articles/5/post").get_data(as_text=True)
    assert "No dates or places were found" in html and "Post to Reddit" in html
    assert client.get("/articles/99/post").status_code == 302 and client.get("/articles/99/post").headers["Location"].endswith("/")


def test_ticked_events_are_saved_with_edits_approved_and_then_reddit_opens(client):
    r = client.post("/articles/5/send", data={
        "from_preview": "1", "event_id": ["11", "12"],
        "add_11": "on", "title_11": "Open house (free)", "start_date_11": "2026-11-21", "end_date_11": "", "start_time_11": "18:00",
        "end_time_11": "20:00", "location_11": "City Center", "source_url_11": "https://example.com/a",
        # event 12 left unticked
        "title_12": "Other thing", "start_date_12": "2026-11-22",
    })
    assert r.status_code == 303 and urlsplit(r.headers["Location"]).netloc == "www.reddit.com"
    assert ("status", 11, "approved") in client.calls and ("sent", 5) in client.calls
    assert not any(c[0] in ("status", "update") and c[1] == 12 for c in client.calls)  # unticked: left for later
    update = next(c for c in client.calls if c[0] == "update" and c[1] == 11)
    assert update[2]["location"] == "City Center" and update[2]["title"] == "Open house (free)"
    assert client.calls.index(("status", 11, "approved")) < client.calls.index(("sent", 5))  # calendar first, then sent
    assert parse_qs(urlsplit(r.headers["Location"]).query)["title"] == ["Council votes"]


def test_an_invalid_date_sends_the_person_back_and_changes_nothing(client):
    r = client.post("/articles/5/send", data={"from_preview": "1", "event_id": "11", "add_11": "on", "title_11": "Open house",
                                              "start_date_11": "next saturday"})
    assert r.status_code == 302 and "/articles/5/post" in r.headers["Location"] and "error=" in r.headers["Location"]
    assert client.calls == []  # not even marked sent
    r2 = client.post("/articles/5/send", data={"from_preview": "1", "new_title": "My event", "new_start_date": "soon"})
    assert "/articles/5/post" in r2.headers["Location"] and client.calls == []


def test_an_event_typed_by_hand_is_added_and_unknown_ids_are_ignored(client):
    r = client.post("/articles/5/send", data={"from_preview": "1", "event_id": ["999"], "add_999": "on", "start_date_999": "2026-11-21",
                                              "new_title": "Cookie swap", "new_start_date": "2026-12-12", "new_location": "Library"})
    assert r.status_code == 303
    assert client.calls[0] == ("add", ("Cookie swap", "2026-12-12", "", "", "Library", ""))
    assert not any(c[0] in ("update", "status") for c in client.calls)  # 999 is not an event of this article


def test_sending_without_the_preview_changes_no_calendar_entries(client):
    assert client.post("/articles/5/send").status_code == 303
    assert client.calls == [("sent", 5)]
