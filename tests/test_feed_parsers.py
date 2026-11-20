from edenprairie_news.feed_parsers import get_parser
from edenprairie_news.feed_parsers.default import parse_entry
from edenprairie_news.models import RawEntry


def test_get_parser_returns_default_for_known_name():
    assert get_parser("default") is parse_entry


def test_get_parser_falls_back_to_default_for_unknown_name():
    assert get_parser("does-not-exist") is parse_entry


def test_default_parse_entry_cleans_html_and_preserves_fields():
    entry = RawEntry(
        url="https://example.com/a",
        source="Example",
        title="  A Title  ",
        summary_html="<p>Body <b>text</b></p>",
        published_at="2026-08-01",
        author="Jane Reporter",
        image_url="https://example.com/a.jpg",
    )
    article = parse_entry(entry)
    assert article.url == "https://example.com/a"
    assert article.title == "A Title"
    assert article.summary == "Body text"
    assert article.published_at == "2026-08-01"
    assert article.author == "Jane Reporter"
    assert article.image_url == "https://example.com/a.jpg"
