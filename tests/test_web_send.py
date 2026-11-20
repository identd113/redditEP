from urllib.parse import parse_qs, urlsplit

import pytest

from edenprairie_news import storage
from edenprairie_news.models import Article
from edenprairie_news.web import app as web


@pytest.fixture
def client(monkeypatch):
    calls = []
    article = Article(id=5, url="https://example.com/a", source="Sun Sailor", title="T", summary="", published_at=None,
                      status="drafted", post_title="Council votes (Sun Sailor)", post_body="Body\n\nSource: [x](https://example.com/a)")
    monkeypatch.setattr(storage, "get_by_id", lambda i, *a, **k: article if i == 5 else None)
    monkeypatch.setattr(storage, "mark_sent", lambda i, *a, **k: calls.append(("sent", i)))
    monkeypatch.setattr(storage, "reopen_draft", lambda i, *a, **k: calls.append(("reopen", i)))
    monkeypatch.setattr(storage, "link_posted", lambda i, u, *a, **k: calls.append(("link", i, u)))
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    c.calls, c.article = calls, article
    return c


def test_send_marks_the_draft_sent_and_opens_the_prefilled_reddit_page(client):
    r = client.post("/articles/5/send")
    assert r.status_code == 303 and client.calls == [("sent", 5)]
    loc = urlsplit(r.headers["Location"])
    assert loc.netloc == "www.reddit.com" and loc.path.endswith("/submit")
    assert parse_qs(loc.query)["title"] == ["Council votes (Sun Sailor)"]


def test_send_ignores_articles_that_are_already_posted_or_unknown(client):
    client.article.status = "posted"
    assert client.post("/articles/5/send").headers["Location"].endswith("/")
    assert client.post("/articles/99/send").headers["Location"].endswith("/")
    assert client.calls == []


def test_paste_a_reddit_link_links_the_article_and_rejects_other_text(client):
    client.post("/articles/5/link", data={"reddit_url": "https://www.reddit.com/r/edenprairie/comments/1abc/t/"})
    assert client.calls == [("link", 5, "https://www.reddit.com/r/edenprairie/comments/1abc/t/")]
    r = client.post("/articles/5/link", data={"reddit_url": "https://example.com/nope"})
    assert "link_error=5" in r.headers["Location"] and len(client.calls) == 1


def test_reopen_puts_a_sent_draft_back(client):
    client.post("/articles/5/reopen")
    assert client.calls == [("reopen", 5)]


def test_index_shows_post_button_on_drafts_and_a_link_form_on_sent_ones(client, monkeypatch):
    drafted = Article(id=1, url="https://example.com/d", source="Sun Sailor", title="A draft", summary="s", published_at=None, status="drafted")
    sent = Article(id=2, url="https://example.com/s", source="Sun Sailor", title="Waiting one", summary="s", published_at=None,
                   status="sent", sent_at="2026-11-19T05:10:00+00:00")
    posted = Article(id=3, url="https://example.com/p", source="Sun Sailor", title="Matched one", summary="s", published_at=None,
                     status="posted", reddit_url="https://www.reddit.com/r/edenprairie/comments/1abc/t/", reddit_post_id="1abc")
    by_status = {"drafted": [drafted], "sent": [sent], "posted": [posted], "rejected": []}
    monkeypatch.setattr(storage, "get_by_status", lambda s, *a, **k: by_status.get(s, []))
    monkeypatch.setattr(storage, "get_subreddit_posts", lambda **k: [])
    monkeypatch.setattr(storage, "get_stats_history", lambda pid, *a, **k: [
        {"taken_at": "2026-11-20T08:00:00+00:00", "score": 10, "upvote_ratio": 0.9, "num_comments": 1},
        {"taken_at": "2026-11-20T10:00:00+00:00", "score": 25, "upvote_ratio": 0.93, "num_comments": 4}])
    drafts = client.get("/").get_data(as_text=True)
    assert 'action="/articles/1/post"' in drafts and ">Post to Reddit</button>" in drafts and ">Run pipeline now</button>" in drafts
    sent_tab = client.get("/?tab=sent").get_data(as_text=True)
    assert "Sent to Reddit (1)" in sent_tab and 'action="/articles/2/link"' in sent_tab and "Not posted, back to drafts" in sent_tab
    assert ">Check Reddit for my posts</button>" in sent_tab
    posted_tab = client.get("/?tab=posted").get_data(as_text=True)
    assert 'href="https://www.reddit.com/r/edenprairie/comments/1abc/t/"' in posted_tab  # matched ones keep their Reddit link
    assert "&#9650; 25" in posted_tab and "(+15 today)" in posted_tab and "93% upvoted" in posted_tab
    assert "4 comments" in posted_tab and "(+3 today)" in posted_tab and ">Refresh stats</button>" in posted_tab


def test_refresh_stats_route_reports_numbers_or_the_reason_it_failed(client, monkeypatch):
    from edenprairie_news import stats as stats_module

    monkeypatch.setattr(stats_module, "refresh_stats", lambda: {"tracked": 3, "snapshots": 2, "new_comments": 5, "removed": ["x1"]})
    loc = client.post("/stats/refresh").headers["Location"]
    assert "stats_tracked=3" in loc and "stats_comments=5" in loc and "stats_removed=x1" in loc

    def no_credentials():
        raise RuntimeError("Reddit client id and secret are not set.")

    monkeypatch.setattr(stats_module, "refresh_stats", no_credentials)
    assert "stats_error=RuntimeError" in client.post("/stats/refresh").headers["Location"]


def test_stats_page_lists_history_and_comments(client, monkeypatch):
    client.article.status, client.article.reddit_post_id = "posted", "1abc"
    monkeypatch.setattr(storage, "get_stats_history", lambda pid, *a, **k: [
        {"taken_at": "2026-11-20T08:00:00+00:00", "score": 5, "upvote_ratio": 0.9, "num_comments": 1},
        {"taken_at": "2026-11-20T10:00:00+00:00", "score": 25, "upvote_ratio": 0.93, "num_comments": 2}])
    monkeypatch.setattr(storage, "get_comments", lambda pid, *a, **k: [
        {"author": "neighbor", "score": 3, "body": "Thanks for posting this"}])
    html = client.get("/articles/5/stats").get_data(as_text=True)
    assert "<strong>25</strong>" in html and "93% upvoted" in html
    assert html.index("10:00") < html.index("08:00")  # newest snapshot first
    assert "u/neighbor" in html and "Thanks for posting this" in html
    client.article.reddit_post_id = None
    assert client.get("/articles/5/stats").status_code == 302  # nothing to show for an article not on Reddit


def test_sync_without_reddit_credentials_shows_a_message_not_a_server_error(client, monkeypatch):
    def not_configured():
        raise RuntimeError("Reddit credentials are not set.")

    monkeypatch.setattr(web, "sync_subreddit_posts", not_configured)
    r = client.post("/subreddit/sync")
    assert r.status_code == 302 and "sync_error=RuntimeError" in r.headers["Location"]
    monkeypatch.setattr(web, "sync_subreddit_posts", lambda: {"synced": 12})
    assert "synced=12" in client.post("/subreddit/sync").headers["Location"]
    monkeypatch.setattr(storage, "get_by_status", lambda s, *a, **k: [])
    monkeypatch.setattr(storage, "get_subreddit_posts", lambda **k: [])
    html = client.get("/?tab=subreddit&sync_error=RuntimeError%3A+Reddit+credentials+are+not+set.").get_data(as_text=True)
    assert "Could not read the subreddit" in html and "Client ID and Secret" in html
