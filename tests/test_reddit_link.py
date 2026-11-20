from urllib.parse import parse_qs, urlsplit

from edenprairie_news import reddit_link


def test_submit_url_prefills_a_text_post_for_the_subreddit():
    url = reddit_link.submit_url("edenprairie", "Council votes (Sun Sailor)", "Line one\n\nSource: [Sun Sailor](https://example.com/a?x=1&y=2)")
    parts = urlsplit(url)
    assert parts.netloc == "www.reddit.com" and parts.path == "/r/edenprairie/submit"
    q = parse_qs(parts.query)
    assert q["title"] == ["Council votes (Sun Sailor)"]
    assert q["text"] == ["Line one\n\nSource: [Sun Sailor](https://example.com/a?x=1&y=2)"]  # survives encoding intact
    assert q["type"] == ["TEXT"] and q["selftext"] == ["true"]


def test_post_id_from_the_links_people_paste():
    assert reddit_link.post_id_from_url("https://www.reddit.com/r/edenprairie/comments/1AbC2d/some_title/") == "1abc2d"
    assert reddit_link.post_id_from_url("https://old.reddit.com/r/edenprairie/comments/1abc2d/") == "1abc2d"
    assert reddit_link.post_id_from_url("https://redd.it/1abc2d") == "1abc2d"
    assert reddit_link.post_id_from_url("https://example.com/not-reddit") is None
    assert reddit_link.post_id_from_url("") is None


def test_normalize_makes_the_same_story_match_however_the_link_was_written():
    a = reddit_link.normalize_url("http://WWW.Example.com/news/story/?utm_source=fb&id=7#top")
    b = reddit_link.normalize_url("https://example.com/news/story?id=7")
    assert a == b
    assert reddit_link.normalize_url("https://example.com/a?id=7") != reddit_link.normalize_url("https://example.com/a?id=8")
