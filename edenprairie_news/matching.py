"""Link our articles to the Reddit posts made from them, so a story is never
sent twice and the matched ones stay visible.

A post matches an article when the article's URL (normalised, see
reddit_link.normalize_url) is the post's link, or appears in its text. Only
articles that are `drafted` or `sent` are matched; anything already `posted`
or `rejected` is left alone.
"""

from edenprairie_news import reddit_link, storage


def match_posts(posts: list[dict], db_path=storage.DB_PATH) -> list[tuple[int, str]]:
    """posts: dicts with 'permalink' and 'urls' (links the post points at or contains; a link post's own
    'url' is accepted too). Marks matched articles posted. Returns [(article_id, permalink)]."""
    open_articles = storage.get_by_status("sent", db_path) + storage.get_by_status("drafted", db_path)
    by_url = {reddit_link.normalize_url(a.url): a for a in open_articles}
    matched = []
    for post in posts:
        post_id = reddit_link.post_id_from_url(post.get("permalink", ""))
        if not post_id:
            continue
        candidates = list(post.get("urls", [])) + ([post["url"]] if post.get("url") else [])
        for link in candidates:
            article = by_url.pop(reddit_link.normalize_url(link), None)
            if article:
                storage.link_posted(article.id, post["permalink"], db_path)
                matched.append((article.id, post["permalink"]))
                break
    return matched
