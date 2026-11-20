import pytest
import requests

from edenprairie_news import reddit_public

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <author><name>/u/someone</name></author>
    <id>t3_1abc2d</id>
    <link href="https://www.reddit.com/r/edenprairie/comments/1abc2d/council_votes/"/>
    <title>Council votes (Sun Sailor)</title>
    <content type="html">&lt;div class="md"&gt;&lt;p&gt;Source: &lt;a href="https://example.com/news/story?a=1&amp;amp;b=2"&gt;Sun Sailor&lt;/a&gt;&lt;/p&gt;&lt;/div&gt; &lt;a href="https://www.reddit.com/r/edenprairie/comments/1abc2d/council_votes/"&gt;[comments]&lt;/a&gt;</content>
  </entry>
</feed>"""


def test_parse_feed_extracts_the_post_and_the_links_inside_it():
    (post,) = reddit_public.parse_feed(ATOM)
    assert post["fullname"] == "t3_1abc2d" and post["author"] == "someone"
    assert post["permalink"].endswith("/comments/1abc2d/council_votes/")
    assert post["urls"] == ["https://example.com/news/story?a=1&b=2"]  # the Reddit comments link is left out


class Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


@pytest.mark.parametrize("status,words", [(429, "rate limiting"), (403, "HTTP 403")])
def test_reddit_refusals_become_a_plain_reason(monkeypatch, status, words):
    monkeypatch.setattr(reddit_public.requests, "get", lambda *a, **k: Resp(status))
    with pytest.raises(reddit_public.RedditUnavailable, match=words):
        reddit_public.fetch_recent_posts("edenprairie", "agent")


def test_network_failure_is_reported_not_raised_raw(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(reddit_public.requests, "get", boom)
    with pytest.raises(reddit_public.RedditUnavailable, match="could not reach"):
        reddit_public.fetch_recent_posts("edenprairie", "agent")


def test_fetch_returns_parsed_posts_and_sends_our_user_agent(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen.update(url=url, headers=headers)
        return Resp(200, ATOM)

    monkeypatch.setattr(reddit_public.requests, "get", fake_get)
    posts = reddit_public.fetch_recent_posts("edenprairie", "my-agent/1.0")
    assert len(posts) == 1 and seen["headers"] == {"User-Agent": "my-agent/1.0"} and "/r/edenprairie/" in seen["url"]


def test_the_feed_address_is_the_standard_new_dot_rss_form(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        return Resp(200, ATOM)

    monkeypatch.setattr(reddit_public.requests, "get", fake_get)
    reddit_public.fetch_recent_posts("edenprairie", "ua", limit=25)
    assert seen["url"] == "https://www.reddit.com/r/edenprairie/new.rss?limit=25"
