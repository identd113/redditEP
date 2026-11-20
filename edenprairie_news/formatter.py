"""Formatter stage: turn a clean Article into a Reddit post title + body.

Kept as pure string transforms with no I/O so formatting rules are trivial
to tweak and unit test.
"""

from edenprairie_news.models import Article

MAX_TITLE_LEN = 300  # Reddit's hard limit


def format_title(article: Article) -> str:
    title = f"{article.title} ({article.source})"
    return title[:MAX_TITLE_LEN]


def format_body(article: Article) -> str:
    lines = []
    if article.summary:
        lines.append(article.summary)
        lines.append("")
    lines.append(f"Source: [{article.source}]({article.url})")
    if article.author:
        lines.append(f"By {article.author}")
    if article.published_at:
        lines.append(f"Published: {article.published_at}")
    return "\n".join(lines)


def format_post(article: Article) -> tuple[str, str]:
    return format_title(article), format_body(article)
