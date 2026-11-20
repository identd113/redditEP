"""Publish dates: feeds write them in different formats (ISO 8601, or RFC 822 like "Thu, 19 Nov 2026 03:23:29 GMT"),
so they are normalised to UTC ISO text when stored. That makes sorting newest-first correct and gives one place that
turns a date into the "Thu Nov 19, 9:23 pm · 2 hours ago" shown on the pages. Standard library only.
"""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Chicago")


def parse_published(raw: str | None) -> datetime | None:
    """A timezone-aware UTC datetime, or None when the text is empty or not a date we understand."""
    if not raw or not str(raw).strip():
        return None
    raw = str(raw).strip()
    dt = None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)  # feeds that give no zone are treated as UTC, the usual convention
    return dt.astimezone(UTC)


def normalize_published(raw: str | None) -> str | None:
    """Stored form: '2026-11-19T03:23:29+00:00' (no fraction), or None."""
    dt = parse_published(raw)
    return dt.replace(microsecond=0).isoformat() if dt else None


def time_ago(then: datetime, now: datetime | None = None) -> str:
    seconds = int(((now or datetime.now(UTC)) - then).total_seconds())
    if seconds < 0:
        return "upcoming"
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        n = seconds // 60
        return f"{n} minute{'s' if n != 1 else ''} ago"
    if seconds < 86400:
        n = seconds // 3600
        return f"{n} hour{'s' if n != 1 else ''} ago"
    if seconds < 14 * 86400:
        n = seconds // 86400
        return f"{n} day{'s' if n != 1 else ''} ago"
    if seconds < 60 * 86400:
        return f"{seconds // (7 * 86400)} weeks ago"
    if seconds < 700 * 86400:
        return f"{seconds // (30 * 86400)} months ago"
    n = seconds // (365 * 86400)
    return f"{n} year{'s' if n != 1 else ''} ago"


def posted_label(raw: str | None, now: datetime | None = None) -> str:
    """'Thu, Nov 19, 9:23 pm · 2 hours ago' in Eden Prairie time, 'Nov 12, 2010 · 16 years ago' for older ones, or
    'date unknown'."""
    dt = parse_published(raw)
    if dt is None:
        return "date unknown"
    now = now or datetime.now(UTC)
    local = dt.astimezone(LOCAL_TZ)
    if (now - dt).days >= 300 or dt.year != now.astimezone(LOCAL_TZ).year:
        when = f"{local:%b} {local.day}, {local.year}"
    else:
        hour = local.strftime("%I:%M %p").lstrip("0").replace(":00", "").lower()
        when = f"{local:%a, %b} {local.day}, {hour}"
    return f"{when} · {time_ago(dt, now)}"
