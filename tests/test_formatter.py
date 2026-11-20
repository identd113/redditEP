from edenprairie_news.formatter import MAX_TITLE_LEN, format_body, format_post, format_title
from edenprairie_news.models import Article


def make_article(**overrides) -> Article:
    defaults = dict(
        url="https://example.com/story",
        source="Example News",
        title="City council approves new trail",
        summary="A short summary of the story.",
        published_at="2026-08-01",
    )
    defaults.update(overrides)
    return Article(**defaults)


def test_format_title_includes_source_and_truncates():
    long_title = "x" * (MAX_TITLE_LEN + 50)
    title = format_title(make_article(title=long_title))
    assert len(title) == MAX_TITLE_LEN


def test_format_body_includes_summary_and_source_link():
    body = format_body(make_article())
    assert "A short summary of the story." in body
    assert "[Example News](https://example.com/story)" in body
    assert "2026-08-01" in body


def test_format_post_returns_title_and_body_tuple():
    title, body = format_post(make_article())
    assert "City council approves new trail" in title
    assert "Example News" in body


def test_format_body_includes_byline_when_author_present():
    body = format_body(make_article(author="Jane Reporter"))
    assert "By Jane Reporter" in body


def test_format_body_omits_byline_when_no_author():
    body = format_body(make_article(author=""))
    assert "By " not in body
