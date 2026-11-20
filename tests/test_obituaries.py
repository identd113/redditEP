import pytest

from edenprairie_news import obituaries, storage
from edenprairie_news.models import Article
from edenprairie_news.web import app as web


@pytest.mark.parametrize("title", [
    "Dianne Camille Anderson - Legacy | Obituary",
    "Leslie Ann Cavins Obituary (2026) - Eden Prairie, MN - Washburn-McReavy",
    "Drew Von Fisher - View Obituary & Service Information - washburn-mcreavy.com",
    "Vernette Inola Fox (Nordstrom) Obituary | Huber Funeral Homes & Cremation",
])
def test_the_real_obituary_headlines_are_caught(title):
    assert obituaries.is_obituary(title)


@pytest.mark.parametrize("title", [
    "City Council OKs Dave's Hot Chicken, Wings Credit Union",
    "Planning Commission backs new neighborhood at C.H. Robinson site",
    "Meet the six Eden Prairie School Board candidates",
    "EPHS girls hockey opens season with 7-3 win",
])
def test_ordinary_news_is_not(title):
    assert not obituaries.is_obituary(title)


def test_summary_and_source_count_too():
    assert obituaries.is_obituary("Mary Smith", summary="Mary passed away peacefully on Nov. 3")
    assert obituaries.is_obituary("Mary Smith", source="legacy.com")


@pytest.fixture
def client(monkeypatch):
    news = Article(id=1, url="https://x/1", source="S", title="Council votes", summary="", published_at=None, status="drafted")
    obit = Article(id=2, url="https://x/2", source="S", title="Jane Doe Obituary | Huber Funeral Homes", summary="", published_at=None, status="drafted")
    near_obit = Article(id=3, url="https://x/3", source="K", title="Chaska man Obituary", summary="", published_at=None, status="drafted", scope="related")
    by = {"drafted": [news, obit, near_obit], "sent": [], "posted": [], "rejected": []}
    monkeypatch.setattr(storage, "get_by_status", lambda s, *a, **k: by.get(s, []))
    monkeypatch.setattr(storage, "get_subreddit_posts", lambda **k: [])
    web.app.config["TESTING"] = True
    return web.app.test_client()


def test_obituaries_are_hidden_by_default_with_a_count_and_a_link_to_show_them(client):
    html = client.get("/").get_data(as_text=True)
    assert "Council votes" in html and "Jane Doe Obituary" not in html and "Chaska man" not in html
    assert "2 obituaries hidden" in html and "obits=1" in html and "Drafts (1)" in html and "Nearby cities" not in html


def test_the_toggle_shows_them_with_a_badge_and_a_link_back(client):
    html = client.get("/?tab=drafts&obits=1").get_data(as_text=True)
    assert "Jane Doe Obituary" in html and "Chaska man Obituary" in html and "Drafts (3)" in html
    assert html.count('badge flag">obituary') == 2 or html.count("obituary</span>") >= 1
    assert "Showing obituaries (2)" in html and "Hide obituaries" in html
