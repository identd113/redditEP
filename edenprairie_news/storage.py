"""SQLite persistence: the article pipeline, the subreddit moderation view,
and DB-backed runtime config.

Independent tables, all in the same DB file (post_stats and post_comments hold the history of how our
posted articles are doing on Reddit -- see stats.py):
- articles: status-driven, new -> drafted -> sent -> posted | removed
  (sent = opened in Reddit for the user to post, waiting for the post's link).
  Our own news drafts.
- subreddit_posts: a synced snapshot of live r/edenprairie submissions, with
  mod-applied tags and auto-computed action_flags (see flag_rules.py). The
  reserved tag "hidden" is what the web UI uses to drop a post out of the
  default view -- see get_subreddit_posts().
- settings: key/value overrides for Reddit/Discord config, editable from the
  web UI's Config page. config.get_reddit_config()/get_discord_config() read
  these with a fallback to the matching .env var -- see config.py.
- feeds: the RSS feed list, editable from the Config page. Seeded once from
  config/feeds.yaml the first time init_db() runs against an empty feeds
  table; after that the DB is authoritative and feeds.yaml is no longer read.

No ORM — the schema is small enough that raw SQL stays readable.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from edenprairie_news.config import DB_PATH, FEEDS_PATH
from edenprairie_news.dates import normalize_published
from edenprairie_news.reddit_link import normalize_url
from edenprairie_news.models import Article, FeedSource

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    post_title TEXT DEFAULT '',
    post_body TEXT DEFAULT '',
    reddit_post_id TEXT,
    updated_at TEXT NOT NULL,
    author TEXT DEFAULT '',
    image_url TEXT DEFAULT '',
    reddit_url TEXT DEFAULT '',
    sent_at TEXT,
    scope TEXT NOT NULL DEFAULT 'local',
    url_key TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS subreddit_posts (
    fullname TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT,
    permalink TEXT NOT NULL,
    url TEXT,
    created_utc REAL,
    num_comments INTEGER DEFAULT 0,
    score INTEGER DEFAULT 0,
    flair TEXT,
    num_reports INTEGER DEFAULT 0,
    tags TEXT NOT NULL DEFAULT '[]',
    action_flags TEXT NOT NULL DEFAULT '[]',
    first_seen_at TEXT NOT NULL,
    last_synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS post_stats (
    post_id TEXT NOT NULL,
    taken_at TEXT NOT NULL,
    score INTEGER NOT NULL,
    upvote_ratio REAL,
    num_comments INTEGER NOT NULL,
    PRIMARY KEY (post_id, taken_at)
);

CREATE TABLE IF NOT EXISTS post_comments (
    comment_id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    author TEXT,
    body TEXT,
    score INTEGER DEFAULT 0,
    created_utc REAL,
    parent_id TEXT,
    first_seen_at TEXT NOT NULL,
    last_synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER,
    title TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT DEFAULT '',
    start_time TEXT DEFAULT '',
    end_time TEXT DEFAULT '',
    location TEXT DEFAULT '',
    location_source TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    snippet TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'suggested',
    created_at TEXT NOT NULL,
    UNIQUE (source_url, start_date, start_time, location)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    parser TEXT NOT NULL DEFAULT 'default'
);
"""

# Columns added to `articles` after its initial release. CREATE TABLE IF NOT
# EXISTS won't add columns to a table that already exists, so init_db()
# patches older DB files with these. Extend this list (don't rewrite SCHEMA
# retroactively) whenever a future change adds an articles column.
ARTICLES_MIGRATIONS = {
    "author": "ALTER TABLE articles ADD COLUMN author TEXT DEFAULT ''",
    "image_url": "ALTER TABLE articles ADD COLUMN image_url TEXT DEFAULT ''",
    "reddit_url": "ALTER TABLE articles ADD COLUMN reddit_url TEXT DEFAULT ''",
    "sent_at": "ALTER TABLE articles ADD COLUMN sent_at TEXT",
    "scope": "ALTER TABLE articles ADD COLUMN scope TEXT NOT NULL DEFAULT 'local'",
    "url_key": "ALTER TABLE articles ADD COLUMN url_key TEXT DEFAULT ''",
}


@contextmanager
def get_conn(db_path: Path = DB_PATH):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)
        _migrate_articles_columns(conn)
        _normalize_published_dates(conn)
        conn.execute("UPDATE articles SET status = 'removed' WHERE status = 'rejected'")  # one list now: Removed, restorable
        _fill_url_keys(conn)
        _seed_feeds_if_empty(conn)


def _migrate_articles_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
    for column, ddl in ARTICLES_MIGRATIONS.items():
        if column not in existing:
            conn.execute(ddl)


def _normalize_published_dates(conn: sqlite3.Connection) -> None:
    """Older rows hold the feed's raw date text ("Thu, 19 Nov 2026 03:23:29 GMT"), which cannot be sorted. Rewrite
    them once as UTC ISO text; text that is not a date is cleared (the page then says "date unknown")."""
    rows = conn.execute(
        "SELECT id, published_at FROM articles WHERE published_at IS NOT NULL AND published_at != '' "
        "AND published_at NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00'"
    ).fetchall()
    for row in rows:
        conn.execute("UPDATE articles SET published_at = ? WHERE id = ?", (normalize_published(row["published_at"]), row["id"]))


def _fill_url_keys(conn: sqlite3.Connection) -> None:
    """url_key is the link with tracking parameters, www., case and a trailing slash removed, so the same story is
    recognised however a feed spells its address. Filled once for rows stored before it existed."""
    for row in conn.execute("SELECT id, url FROM articles WHERE url_key IS NULL OR url_key = ''").fetchall():
        conn.execute("UPDATE articles SET url_key = ? WHERE id = ?", (normalize_url(row["url"]), row["id"]))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_url_key ON articles (url_key)")


def _seed_feeds_if_empty(conn: sqlite3.Connection) -> None:
    (count,) = conn.execute("SELECT COUNT(*) FROM feeds").fetchone()
    if count > 0 or not FEEDS_PATH.exists():
        return
    with open(FEEDS_PATH) as f:
        raw = yaml.safe_load(f) or {}
    for entry in raw.get("feeds", []):
        conn.execute(
            "INSERT OR IGNORE INTO feeds (name, url, tags, parser) VALUES (?, ?, ?, ?)",
            (
                entry["name"],
                entry["url"],
                json.dumps(entry.get("tags", [])),
                entry.get("parser", "default"),
            ),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_article(row: sqlite3.Row) -> Article:
    return Article(
        id=row["id"],
        url=row["url"],
        source=row["source"],
        title=row["title"],
        summary=row["summary"] or "",
        published_at=row["published_at"],
        author=row["author"] or "",
        image_url=row["image_url"] or "",
        status=row["status"],
        post_title=row["post_title"] or "",
        post_body=row["post_body"] or "",
        reddit_post_id=row["reddit_post_id"],
        reddit_url=row["reddit_url"] or "",
        sent_at=row["sent_at"],
        scope=row["scope"] or "local",
    )


def insert_new_articles(articles: list[Article], db_path: Path = DB_PATH) -> list[Article]:
    """Insert articles not already known by URL. Returns the ones actually inserted."""
    inserted = []
    with get_conn(db_path) as conn:
        for article in articles:
            key = normalize_url(article.url)
            existing = conn.execute(
                "SELECT 1 FROM articles WHERE url = ? OR url_key = ?", (article.url, key)
            ).fetchone()  # any status counts, "removed" included: a link we have dropped is never added again
            if existing:
                continue
            conn.execute(
                """INSERT INTO articles
                   (url, source, title, summary, published_at, fetched_at, status, updated_at,
                    author, image_url, scope, url_key)
                   VALUES (?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?)""",
                (
                    article.url,
                    article.source,
                    article.title,
                    article.summary,
                    normalize_published(article.published_at),
                    _now(),
                    _now(),
                    article.author,
                    article.image_url,
                    article.scope,
                    key,
                ),
            )
            inserted.append(article)
    return inserted


def get_by_status(status: str, db_path: Path = DB_PATH) -> list[Article]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            # newest first by the date the article was posted; when a feed gave none, by when we first saw it
            "SELECT * FROM articles WHERE status = ? ORDER BY COALESCE(published_at, fetched_at) DESC, id DESC",
            (status,),
        ).fetchall()
    return [_row_to_article(r) for r in rows]


def get_by_id(article_id: int, db_path: Path = DB_PATH) -> Article | None:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    return _row_to_article(row) if row else None


def save_draft(article_id: int, post_title: str, post_body: str, db_path: Path = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            """UPDATE articles SET status = 'drafted', post_title = ?, post_body = ?,
               updated_at = ? WHERE id = ?""",
            (post_title, post_body, _now(), article_id),
        )


def update_draft_text(article_id: int, post_title: str, post_body: str, db_path: Path = DB_PATH) -> None:
    """Edit a draft's text in place without changing its status."""
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE articles SET post_title = ?, post_body = ?, updated_at = ? WHERE id = ?",
            (post_title, post_body, _now(), article_id),
        )


def mark_rejected(article_id: int, db_path: Path = DB_PATH) -> None:
    """Old name, kept for existing callers: there is no separate "rejected" any more, only removed (with Restore)."""
    mark_removed(article_id, db_path)


def mark_sent(article_id: int, db_path: Path = DB_PATH) -> None:
    """The user opened Reddit's pre-filled submit page for this draft. It leaves the drafts so it
    cannot be sent twice, and waits to be matched to the post (link_posted)."""
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE articles SET status = 'sent', sent_at = ?, updated_at = ? WHERE id = ? AND status = 'drafted'",
            (_now(), _now(), article_id),
        )


def reopen_draft(article_id: int, db_path: Path = DB_PATH) -> None:
    """Sent by mistake or never posted: put it back among the drafts."""
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE articles SET status = 'drafted', sent_at = NULL, updated_at = ? WHERE id = ? AND status = 'sent'",
            (_now(), article_id),
        )


def link_posted(article_id: int, reddit_url: str, db_path: Path = DB_PATH) -> None:
    """Record the Reddit post made from this article (found automatically or pasted by hand)."""
    from edenprairie_news.reddit_link import post_id_from_url

    with get_conn(db_path) as conn:
        conn.execute(
            """UPDATE articles SET status = 'posted', reddit_url = ?, reddit_post_id = ?, updated_at = ?
               WHERE id = ?""",
            (reddit_url, post_id_from_url(reddit_url), _now(), article_id),
        )


def mark_removed(article_id: int, db_path: Path = DB_PATH) -> None:
    """Take an article off every list for good. The row stays (with its link) so the pipeline never adds that
    link again; restore_removed() undoes it."""
    with get_conn(db_path) as conn:
        conn.execute("UPDATE articles SET status = 'removed', updated_at = ? WHERE id = ?", (_now(), article_id))


def restore_removed(article_id: int, db_path: Path = DB_PATH) -> None:
    """Bring a removed article back: to Posted if it had been posted to Reddit, otherwise to the drafts."""
    with get_conn(db_path) as conn:
        conn.execute(
            """UPDATE articles SET status = CASE WHEN reddit_post_id IS NOT NULL AND reddit_post_id != ''
               THEN 'posted' ELSE 'drafted' END, updated_at = ? WHERE id = ? AND status = 'removed'""",
            (_now(), article_id),
        )


def remove_drafts_older_than(days: int, db_path: Path = DB_PATH) -> int:
    """Remove (so Restore still works, and the links stay blocked) drafts published more than `days` ago.
    Posted and sent articles are left alone. Returns how many were removed. days <= 0 does nothing."""
    if days <= 0:
        return 0
    cutoff = (datetime.now(UTC) - timedelta(days=days)).replace(microsecond=0).isoformat()
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "UPDATE articles SET status = 'removed', updated_at = ? WHERE status = 'drafted' "
            "AND published_at IS NOT NULL AND published_at < ?",
            (_now(), cutoff),
        )
    return cur.rowcount


def count_drafts_older_than(days: int, db_path: Path = DB_PATH) -> int:
    if days <= 0:
        return 0
    cutoff = (datetime.now(UTC) - timedelta(days=days)).replace(microsecond=0).isoformat()
    with get_conn(db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM articles WHERE status = 'drafted' AND published_at IS NOT NULL AND published_at < ?", (cutoff,)
        ).fetchone()[0]


def mark_posted(article_id: int, reddit_post_id: str, db_path: Path = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            """UPDATE articles SET status = 'posted', reddit_post_id = ?, updated_at = ?
               WHERE id = ?""",
            (reddit_post_id, _now(), article_id),
        )


# A new snapshot is stored when the numbers moved, or when the last one is older than this, so the
# history shows a steady trend without writing a row on every refresh.
STATS_MIN_GAP = timedelta(hours=1)


def record_stats(post_id: str, score: int, upvote_ratio: float | None, num_comments: int,
                 db_path: Path = DB_PATH) -> bool:
    """Store one snapshot of a Reddit post's numbers. Returns False when nothing was worth storing
    (same numbers as the last snapshot, taken less than STATS_MIN_GAP ago)."""
    with get_conn(db_path) as conn:
        last = conn.execute(
            "SELECT * FROM post_stats WHERE post_id = ? ORDER BY taken_at DESC LIMIT 1", (post_id,)
        ).fetchone()
        if last:
            same = (last["score"], last["num_comments"], last["upvote_ratio"]) == (score, num_comments, upvote_ratio)
            age = datetime.now(UTC) - datetime.fromisoformat(last["taken_at"])
            if same and age < STATS_MIN_GAP:
                return False
        conn.execute(
            "INSERT OR REPLACE INTO post_stats (post_id, taken_at, score, upvote_ratio, num_comments) VALUES (?, ?, ?, ?, ?)",
            (post_id, _now(), score, upvote_ratio, num_comments),
        )
    return True


def get_stats_history(post_id: str, db_path: Path = DB_PATH) -> list[dict]:
    """Oldest first."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT taken_at, score, upvote_ratio, num_comments FROM post_stats WHERE post_id = ? ORDER BY taken_at",
            (post_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def summarize_stats(history: list[dict], now: datetime | None = None) -> dict | None:
    """Latest numbers plus the change over the last 24 hours (against the oldest snapshot inside that
    window, or the first one ever when the post is younger). None when nothing was recorded yet."""
    if not history:
        return None
    now = now or datetime.now(UTC)
    latest = history[-1]
    window = [h for h in history if now - datetime.fromisoformat(h["taken_at"]) <= timedelta(hours=24)]
    base = window[0] if window else latest
    return {
        "score": latest["score"], "upvote_ratio": latest["upvote_ratio"], "num_comments": latest["num_comments"],
        "taken_at": latest["taken_at"],
        "score_change_24h": latest["score"] - base["score"], "comments_change_24h": latest["num_comments"] - base["num_comments"],
    }


def upsert_comments(post_id: str, comments: list[dict], db_path: Path = DB_PATH) -> int:
    """comments: {comment_id, author, body, score, created_utc, parent_id}. Returns how many were new."""
    new = 0
    with get_conn(db_path) as conn:
        for c in comments:
            exists = conn.execute("SELECT 1 FROM post_comments WHERE comment_id = ?", (c["comment_id"],)).fetchone()
            if exists:
                conn.execute(
                    "UPDATE post_comments SET author = ?, body = ?, score = ?, last_synced_at = ? WHERE comment_id = ?",
                    (c["author"], c["body"], c["score"], _now(), c["comment_id"]),
                )
            else:
                new += 1
                conn.execute(
                    """INSERT INTO post_comments (comment_id, post_id, author, body, score, created_utc, parent_id,
                       first_seen_at, last_synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (c["comment_id"], post_id, c["author"], c["body"], c["score"], c["created_utc"],
                     c["parent_id"], _now(), _now()),
                )
    return new


def get_comments(post_id: str, db_path: Path = DB_PATH) -> list[dict]:
    """Newest first."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM post_comments WHERE post_id = ? ORDER BY created_utc DESC", (post_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def insert_events(article_id: int, source_url: str, candidates: list, db_path: Path = DB_PATH) -> int:
    """Store extracted candidates (events.EventCandidate) as `suggested`. A repeat of the same event from the
    same article is ignored. Returns how many were new."""
    new = 0
    with get_conn(db_path) as conn:
        for c in candidates:
            cur = conn.execute(
                """INSERT OR IGNORE INTO events (article_id, title, start_date, end_date, start_time, end_time, location,
                   location_source, source_url, snippet, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'suggested', ?)""",
                (article_id, c.title, c.start_date.isoformat(), c.end_date.isoformat() if c.end_date else "",
                 c.start_time, c.end_time, c.location, c.location_source, source_url, c.snippet, _now()),
            )
            new += cur.rowcount
    return new


def add_event(title: str, start_date: str, start_time: str = "", end_time: str = "", location: str = "",
              source_url: str = "", db_path: Path = DB_PATH) -> None:
    """An event typed in by hand: approved straight away."""
    with get_conn(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO events (article_id, title, start_date, start_time, end_time, location,
               location_source, source_url, status, created_at) VALUES (NULL, ?, ?, ?, ?, ?, 'manual', ?, 'approved', ?)""",
            (title, start_date, start_time, end_time, location, source_url, _now()),
        )


def get_events(status: str, db_path: Path = DB_PATH) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE status = ? ORDER BY start_date, start_time", (status,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_events_for_article(article_id: int, db_path: Path = DB_PATH) -> list[dict]:
    """Events found in one article that are still waiting for a decision or already on the calendar."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE article_id = ? AND status IN ('suggested', 'approved') ORDER BY start_date, start_time",
            (article_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def event_already_known(source_url: str, today_iso: str, db_path: Path = DB_PATH) -> bool:
    """Should an events-feed item for this event be skipped? Yes when it is already stored with a start that has not
    passed yet (any status), or when it was ever dismissed ("Not an event"); either way it is not suggested again."""
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM events WHERE source_url = ? AND (status = 'rejected' OR start_date >= ?) LIMIT 1",
            (source_url, today_iso),
        ).fetchone()
    return row is not None


def get_event(event_id: int, db_path: Path = DB_PATH) -> dict | None:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return dict(row) if row else None


def set_event_status(event_id: int, status: str, db_path: Path = DB_PATH) -> None:
    if status not in ("suggested", "approved", "rejected"):
        raise ValueError(status)
    with get_conn(db_path) as conn:
        conn.execute("UPDATE events SET status = ? WHERE id = ?", (status, event_id))


def update_event(event_id: int, fields: dict, db_path: Path = DB_PATH) -> None:
    """Edit title, dates, times or location (a person correcting the guess)."""
    allowed = ("title", "start_date", "end_date", "start_time", "end_time", "location", "source_url")
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    sets = ", ".join(f"{k} = ?" for k in updates)
    with get_conn(db_path) as conn:
        conn.execute(f"UPDATE events SET {sets} WHERE id = ?", (*updates.values(), event_id))


def _row_to_post(row: sqlite3.Row) -> dict:
    return {
        "fullname": row["fullname"],
        "title": row["title"],
        "author": row["author"],
        "permalink": row["permalink"],
        "url": row["url"],
        "created_utc": row["created_utc"],
        "num_comments": row["num_comments"],
        "score": row["score"],
        "flair": row["flair"],
        "num_reports": row["num_reports"],
        "tags": json.loads(row["tags"] or "[]"),
        "action_flags": json.loads(row["action_flags"] or "[]"),
        "first_seen_at": row["first_seen_at"],
        "last_synced_at": row["last_synced_at"],
    }


def upsert_subreddit_post(post: dict, db_path: Path = DB_PATH) -> None:
    """Insert a newly-seen post as-is, or refresh an existing one -- except
    its tags, which are mod-applied and must survive re-syncing."""
    action_flags_json = json.dumps(post.get("action_flags", []))
    with get_conn(db_path) as conn:
        existing = conn.execute(
            "SELECT 1 FROM subreddit_posts WHERE fullname = ?", (post["fullname"],)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE subreddit_posts SET title = ?, author = ?, permalink = ?, url = ?,
                   created_utc = ?, num_comments = ?, score = ?, flair = ?, num_reports = ?,
                   action_flags = ?, last_synced_at = ? WHERE fullname = ?""",
                (
                    post["title"],
                    post["author"],
                    post["permalink"],
                    post["url"],
                    post["created_utc"],
                    post["num_comments"],
                    post["score"],
                    post["flair"],
                    post["num_reports"],
                    action_flags_json,
                    _now(),
                    post["fullname"],
                ),
            )
        else:
            conn.execute(
                """INSERT INTO subreddit_posts
                   (fullname, title, author, permalink, url, created_utc, num_comments, score,
                    flair, num_reports, tags, action_flags, first_seen_at, last_synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)""",
                (
                    post["fullname"],
                    post["title"],
                    post["author"],
                    post["permalink"],
                    post["url"],
                    post["created_utc"],
                    post["num_comments"],
                    post["score"],
                    post["flair"],
                    post["num_reports"],
                    action_flags_json,
                    _now(),
                    _now(),
                ),
            )


def get_subreddit_posts(include_hidden: bool = False, db_path: Path = DB_PATH) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM subreddit_posts ORDER BY created_utc DESC"
        ).fetchall()
    posts = [_row_to_post(r) for r in rows]
    if not include_hidden:
        posts = [p for p in posts if "hidden" not in p["tags"]]
    return posts


def add_post_tag(fullname: str, tag: str, db_path: Path = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT tags FROM subreddit_posts WHERE fullname = ?", (fullname,)
        ).fetchone()
        if not row:
            return
        tags = json.loads(row["tags"] or "[]")
        if tag not in tags:
            tags.append(tag)
        conn.execute(
            "UPDATE subreddit_posts SET tags = ? WHERE fullname = ?",
            (json.dumps(tags), fullname),
        )


def remove_post_tag(fullname: str, tag: str, db_path: Path = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT tags FROM subreddit_posts WHERE fullname = ?", (fullname,)
        ).fetchone()
        if not row:
            return
        tags = [t for t in json.loads(row["tags"] or "[]") if t != tag]
        conn.execute(
            "UPDATE subreddit_posts SET tags = ? WHERE fullname = ?",
            (json.dumps(tags), fullname),
        )


def get_setting(key: str, default: str | None = None, db_path: Path = DB_PATH) -> str | None:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str, db_path: Path = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def _row_to_feed(row: sqlite3.Row) -> FeedSource:
    return FeedSource(
        id=row["id"],
        name=row["name"],
        url=row["url"],
        tags=json.loads(row["tags"] or "[]"),
        parser=row["parser"],
    )


def list_feeds(db_path: Path = DB_PATH) -> list[FeedSource]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM feeds ORDER BY id").fetchall()
    return [_row_to_feed(r) for r in rows]


def add_feed(
    name: str, url: str, tags: list[str], parser: str = "default", db_path: Path = DB_PATH
) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO feeds (name, url, tags, parser) VALUES (?, ?, ?, ?)",
            (name, url, json.dumps(tags), parser),
        )


def delete_feed(feed_id: int, db_path: Path = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
