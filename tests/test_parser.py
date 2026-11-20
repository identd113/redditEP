from edenprairie_news.models import Article
from edenprairie_news.parser import clean_html, filter_relevant


def test_clean_html_strips_tags():
    assert clean_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_filter_relevant_matches_title_or_summary_case_insensitively():
    articles = [
        Article(url="1", source="s", title="Eden Prairie opens new park", summary="", published_at=None),
        Article(url="2", source="s", title="Minneapolis news", summary="mentions eden prairie briefly", published_at=None),
        Article(url="3", source="s", title="Unrelated story", summary="nothing relevant", published_at=None),
    ]
    relevant = filter_relevant(articles)
    assert {a.url for a in relevant} == {"1", "2"}
