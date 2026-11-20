import pytest

from edenprairie_news import storage
from edenprairie_news.models import Article
from edenprairie_news.web import app as web


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "FEEDS_PATH", tmp_path / "none.yaml")
    path = tmp_path / "t.db"
    storage.init_db(path)
    return path


def art(url, title="T"):
    return Article(url=url, source="S", title=title, summary="", published_at=None)


def add_drafted(db_path, url):
    storage.insert_new_articles([art(url)], db_path)
    with storage.get_conn(db_path) as conn:
        conn.execute("UPDATE articles SET status = 'drafted' WHERE url = ?", (url,))
        return conn.execute("SELECT id FROM articles WHERE url = ?", (url,)).fetchone()["id"]


def test_a_removed_link_is_never_added_again_even_when_the_feed_spells_it_differently(db_path):
    article_id = add_drafted(db_path, "https://example.com/news/story?id=7")
    storage.mark_removed(article_id, db_path)
    again = [
        art("https://example.com/news/story?id=7"),                              # exactly the same
        art("https://www.example.com/news/story/?id=7&utm_source=newsletter"),   # tracking tag, www, trailing slash
        art("http://EXAMPLE.com/news/story?id=7#comments"),                      # scheme, case, fragment
    ]
    assert storage.insert_new_articles(again, db_path) == []
    assert storage.get_by_status("removed", db_path)[0].id == article_id and len(storage.get_by_status("new", db_path)) == 0
    assert storage.insert_new_articles([art("https://example.com/news/story?id=8")], db_path)  # a different story still comes in


def test_rejected_and_posted_links_stay_blocked_too(db_path):
    a = add_drafted(db_path, "https://example.com/a")
    storage.mark_rejected(a, db_path)
    assert storage.insert_new_articles([art("https://example.com/a?utm_medium=x")], db_path) == []


def test_removed_articles_leave_every_list_and_restore_goes_back_where_it_belongs(db_path):
    plain = add_drafted(db_path, "https://example.com/plain")
    posted = add_drafted(db_path, "https://example.com/posted")
    storage.link_posted(posted, "https://www.reddit.com/r/edenprairie/comments/1abc/t/", db_path)
    storage.mark_removed(plain, db_path)
    storage.mark_removed(posted, db_path)
    assert storage.get_by_status("drafted", db_path) == [] and storage.get_by_status("posted", db_path) == []
    storage.restore_removed(plain, db_path)
    storage.restore_removed(posted, db_path)
    assert [a.id for a in storage.get_by_status("drafted", db_path)] == [plain]
    assert [a.id for a in storage.get_by_status("posted", db_path)] == [posted]
    storage.restore_removed(plain, db_path)  # restoring something that is not removed does nothing
    assert len(storage.get_by_status("drafted", db_path)) == 1


def test_old_databases_get_their_link_keys_filled_once(db_path):
    with storage.get_conn(db_path) as conn:
        conn.execute("INSERT INTO articles (url, source, title, fetched_at, status, updated_at) VALUES "
                     "('https://www.Example.com/a/?utm_source=x', 'S', 't', '2026-11-19T00:00:00+00:00', 'drafted', 'x')")
    storage.init_db(db_path)
    storage.init_db(db_path)
    with storage.get_conn(db_path) as conn:
        key = conn.execute("SELECT url_key FROM articles").fetchone()["url_key"]
    assert key == "https://example.com/a"
    assert storage.insert_new_articles([art("https://example.com/a")], db_path) == []  # an article stored before the change is matched too


@pytest.fixture
def client(monkeypatch):
    calls = []
    monkeypatch.setattr(storage, "mark_removed", lambda i, *a, **k: calls.append(("remove", i)))
    monkeypatch.setattr(storage, "restore_removed", lambda i, *a, **k: calls.append(("restore", i)))
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    c.calls = calls
    return c


def test_remove_and_restore_routes(client):
    r = client.post("/articles/4/remove", headers={"Referer": "http://localhost/?obits=1"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/?obits=1") and client.calls == [("remove", 4)]  # back to where you were
    assert client.post("/articles/4/restore").status_code == 302 and client.calls[-1] == ("restore", 4)


def test_every_article_tile_has_a_remove_button_and_removed_ones_can_be_restored(monkeypatch):
    def a(i, status, **kw):
        return Article(id=i, url=f"https://x/{i}", source="S", title=f"Story {i}", summary="", published_at=None, status=status, **kw)

    by = {"drafted": [a(1, "drafted")], "sent": [a(3, "sent")], "posted": [a(4, "posted", reddit_post_id="1abc")],
          "removed": [a(6, "removed")]}
    by["drafted"].append(a(2, "drafted", scope="related"))
    monkeypatch.setattr(storage, "get_by_status", lambda s, *k, **kw: by[s])
    monkeypatch.setattr(storage, "get_subreddit_posts", lambda **k: [])
    monkeypatch.setattr(storage, "get_stats_history", lambda *a, **k: [])
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    drafts, sent, posted_tab, removed = (c.get(f"/?tab={t}").get_data(as_text=True) for t in ("drafts", "sent", "posted", "removed"))
    for i, page in ((1, drafts), (2, drafts), (3, sent), (4, posted_tab)):
        assert f'action="/articles/{i}/remove"' in page, i
    for page in (drafts, sent, posted_tab, removed):
        assert "Reject" not in page and "/reject" not in page and "Rejected" not in page  # one button, one list
    assert 'action="/articles/6/restore"' in removed and "Removed (1)" in removed and "will not be added again" in removed
    html = posted_tab
    posted_form = html[html.index('action="/articles/4/remove"') - 60:html.index('action="/articles/4/remove"') + 160]
    assert "confirm(" in posted_form  # a posted tile asks first: the Reddit post itself is not touched


def test_remove_is_a_strong_red_button_not_the_pale_grey_one(client):
    css = open("edenprairie_news/web/static/style.css").read()
    block = css[css.index("button.danger {"):css.index("}", css.index("button.danger {"))]
    assert "#c62828" in block and "color: #fff" in block
    web.app.config["TESTING"] = True


def test_the_remove_buttons_on_the_page_use_the_red_style(monkeypatch):
    a = Article(id=1, url="https://x/1", source="S", title="Story", summary="", published_at=None, status="drafted")
    by = {"drafted": [a]}
    monkeypatch.setattr(storage, "get_by_status", lambda s, *k, **kw: by.get(s, []))
    monkeypatch.setattr(storage, "get_subreddit_posts", lambda **k: [])
    html = web.app.test_client().get("/").get_data(as_text=True)
    assert 'class="danger" title="Take this off the list for good' in html
    edit_page_button = open("edenprairie_news/web/templates/article.html").read()
    assert "article_remove" in edit_page_button and 'class="danger"' in edit_page_button and "Reject" not in edit_page_button


def test_anything_already_rejected_moves_to_removed_once_and_stays_blocked(db_path):
    with storage.get_conn(db_path) as conn:
        conn.execute("INSERT INTO articles (url, source, title, fetched_at, status, updated_at, url_key) VALUES "
                     "('https://x/r', 'S', 't', '2026-11-19T00:00:00+00:00', 'rejected', 'x', 'https://x/r')")
    storage.init_db(db_path)
    assert storage.get_by_status("rejected", db_path) == []
    removed = storage.get_by_status("removed", db_path)
    assert [a.url for a in removed] == ["https://x/r"]
    storage.restore_removed(removed[0].id, db_path)  # and the old rejects can now be brought back
    assert [a.url for a in storage.get_by_status("drafted", db_path)] == ["https://x/r"]
    storage.mark_removed(removed[0].id, db_path)
    assert storage.insert_new_articles([art("https://x/r?utm_source=z")], db_path) == []
