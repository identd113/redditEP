import re

import pytest

from edenprairie_news import storage
from edenprairie_news.models import Article
from edenprairie_news.web import app as web


def art(i, source, status="drafted", scope="local", title=None):
    return Article(id=i, url=f"https://x/{i}", source=source, title=title or f"Story {i} from {source}", summary="s",
                   published_at="2026-11-18T10:00:00+00:00", status=status, scope=scope)


@pytest.fixture
def client(monkeypatch):
    by = {
        "drafted": [art(1, "Eden Prairie Local News"), art(2, "Eden Prairie Local News"), art(3, "KSTP: Eden Prairie"),
                    art(4, "KSTP nearby: Chaska", scope="related"), art(5, "KSTP nearby: Chaska", scope="related"),
                    art(6, "KSTP nearby: Edina", scope="related"), art(7, "Google News: Eden Prairie, MN")],
        "sent": [art(8, "Eden Prairie Local News", "sent")],
        "posted": [art(9, "KSTP: Eden Prairie", "posted")],
        "removed": [art(10, "Google News: Eden Prairie, MN", "removed"), art(11, "Google News: Eden Prairie, MN", "removed")],
    }
    monkeypatch.setattr(storage, "get_by_status", lambda s, *a, **k: by.get(s, []))
    monkeypatch.setattr(storage, "get_subreddit_posts", lambda **k: [{"fullname": "t3_a", "title": "A live post", "author": "u", "permalink": "https://r/a",
                                                                       "num_comments": 1, "score": 2, "flair": None, "action_flags": [], "tags": []}])
    monkeypatch.setattr(storage, "get_stats_history", lambda *a, **k: [])
    web.app.config["TESTING"] = True
    return web.app.test_client()


def tab_links(html):
    start = html.index('<nav class="side"')
    nav = html[start:html.index("</nav>", start)]
    return re.findall(r'<a href="([^"]+)" class="(active)?"[^>]*>([^<]*)<span class="count">(\d+)</span>', nav)


def test_the_left_tabs_show_each_section_with_its_count_and_mark_the_current_one(client):
    links = tab_links(client.get("/").get_data(as_text=True))
    assert [(label.strip(), count) for _, _, label, count in links] == [
        ("Drafts", "7"), ("Sent to Reddit", "1"), ("Posted", "1"), ("r/edenprairie", "1"), ("Removed", "2")]
    assert [a for _, a, _, _ in links] == ["active", "", "", "", ""]  # Drafts is the page you land on
    assert tab_links(client.get("/?tab=removed").get_data(as_text=True))[4][1] == "active"
    assert "Drafts (7)" in client.get("/?tab=bogus").get_data(as_text=True)  # an unknown tab falls back to Drafts


def test_each_tab_shows_only_its_own_content_and_its_own_buttons(client):
    drafts, sent, posted, sub, removed = (client.get(f"/?tab={t}").get_data(as_text=True) for t in ("drafts", "sent", "posted", "subreddit", "removed"))
    button = lambda label: f">{label}</button>"  # the page's help data also contains every label, so look for the button itself
    assert button("Run pipeline now") in drafts and "Story 1 from" in drafts and "Story 8" not in drafts and "A live post" not in drafts
    assert button("Check Reddit for my posts") in sent and "Story 8 from" in sent and button("Run pipeline now") not in sent
    assert button("Refresh stats") in posted and "Story 9 from" in posted and button("Check Reddit for my posts") not in posted
    assert button("Sync subreddit posts") in sub and "A live post" in sub and "r/edenprairie (1)" in sub
    assert button("Restore") in removed
    assert "Restore" in removed and "Story 10 from" in removed and "Story 1 from" not in removed


def test_drafts_can_be_filtered_by_source_with_eden_prairie_sources_before_nearby_ones(client):
    html = client.get("/").get_data(as_text=True)
    chips = re.findall(r'<a class="chip ([^"]*)" href="([^"]+)">([^<]*)<span class="count">(\d+)</span>', html)
    names = [(c[2].strip(), c[3]) for c in chips]
    assert names == [("All", "7"), ("Eden Prairie Local News", "2"), ("Google News: Eden Prairie, MN", "1"), ("KSTP: Eden Prairie", "1"),
                     ("KSTP nearby: Chaska", "2"), ("KSTP nearby: Edina", "1")]
    assert "nearby" in chips[4][0] and "nearby" not in chips[1][0]  # nearby feeds are marked (dashed outline)
    only = client.get("/?tab=drafts&source=KSTP+nearby%3A+Chaska").get_data(as_text=True)
    assert "Story 4 from" in only and "Story 5 from" in only and "Story 6 from" not in only and "Story 1 from" not in only
    assert "Drafts (2)" in only and re.search(r'chip [^"]*active[^"]*"[^>]*>KSTP nearby: Chaska', only)
    assert "Drafts (7)" in client.get("/?source=No+such+feed").get_data(as_text=True)  # an unknown source shows everything


def test_eden_prairie_drafts_come_before_nearby_ones_and_a_filter_keeps_that_order(client):
    html = client.get("/").get_data(as_text=True)
    assert html.index("Story 7 from") < html.index("Nearby cities (3)") < html.index("Story 4 from")


def test_actions_land_back_on_the_tab_they_belong_to(client, monkeypatch):
    from edenprairie_news import matching, stats as stats_module
    monkeypatch.setattr(web, "run_pipeline", lambda: {"fetched": 5, "new": 2, "events": 1})
    assert "tab=drafts" in client.post("/pipeline/run").headers["Location"]
    monkeypatch.setattr(web, "sync_subreddit_posts", lambda: {"synced": 3})
    assert "tab=subreddit" in client.post("/subreddit/sync").headers["Location"]
    monkeypatch.setattr(stats_module, "refresh_stats", lambda: {"tracked": 0, "snapshots": 0, "new_comments": 0, "removed": []})
    assert "tab=posted" in client.post("/stats/refresh").headers["Location"]
    monkeypatch.setattr(web.reddit_public, "fetch_recent_posts", lambda *a, **k: [])
    monkeypatch.setattr(matching, "match_posts", lambda posts: [])
    assert "tab=sent" in client.post("/reddit/match").headers["Location"]
    monkeypatch.setattr(storage, "link_posted", lambda *a, **k: None)
    assert "tab=posted" in client.post("/articles/8/link", data={"reddit_url": "https://www.reddit.com/r/edenprairie/comments/1abc/t/"}).headers["Location"]
    assert "tab=sent" in client.post("/articles/8/link", data={"reddit_url": "nope"}).headers["Location"]
    monkeypatch.setattr(storage, "reopen_draft", lambda *a, **k: None)
    assert "tab=drafts" in client.post("/articles/8/reopen").headers["Location"]


def test_the_phone_layout_turns_the_tabs_into_a_strip():
    css = open("edenprairie_news/web/static/style.css").read()
    assert "nav.side" in css and "flex-direction: row" in css and "overflow-x: auto" in css
