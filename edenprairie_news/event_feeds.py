"""Import events from an *events* feed (a calendar published as RSS) straight to the Events page.

Unlike an article feed, every item here already is an event, so nothing is guessed from wording and no Reddit
post is drafted. Built for Eden Prairie Local News (eplocalnews.org/events/feed/), where each item's publish date
is the occurrence's start, with a time zone (`Thu, 19 Nov 2026 09:30:00 -0600`), and each event page carries
schema.org data with the end time and the place. Everything lands as a *suggested* event for the person to approve.

Rules, so the calendar stays useful:
- Only upcoming occurrences. A recurring event (weekly story time, a Santa visit running for weeks) appears once,
  as its next occurrence, and again after that one has passed.
- An event the person dismissed ("Not an event") is never suggested again.
- Events whose text names another Minnesota town ("Park Rapids, MN") are skipped; the count is reported.
"""

import html
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

import feedparser
import requests

from edenprairie_news import storage
from edenprairie_news.dates import LOCAL_TZ
from edenprairie_news.events import EventCandidate

logger = logging.getLogger(__name__)

USER_AGENT = "edenprairie-news-bot/0.1 (r/edenprairie moderation helper; reads public event pages)"
MAX_PAGE_LOOKUPS = 15  # event pages fetched per run, one per second, so a feed never makes us hammer a site
_OTHER_TOWN = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+){0,2}),\s*(?:MN|Minnesota)\b")
_LD_JSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


@dataclass
class EventItem:
    title: str
    link: str  # as in the feed, including ?occurrence=
    base_url: str  # the event itself, without the occurrence
    start: datetime  # local time
    text: str


def _plain(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup or ""))).strip()


def _base(link: str) -> str:
    parts = urlsplit(link)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def parse_items(feed_text: str) -> list[EventItem]:
    items = []
    for e in feedparser.parse(feed_text).entries:
        try:
            start = parsedate_to_datetime(e.get("published", "")).astimezone(LOCAL_TZ)
        except (TypeError, ValueError):
            continue  # no usable start time: not an event we can place on a calendar
        link = e.get("link", "")
        if link and e.get("title"):
            items.append(EventItem(title=html.unescape(e["title"]).strip(), link=link, base_url=_base(link), start=start,
                                   text=_plain(e.get("summary", ""))))
    return items


def parse_event_page(page_html: str) -> dict:
    """{'end': datetime|None, 'place': str, 'address': str} from the page's schema.org Event data ({} if none)."""
    for m in _LD_JSON.finditer(page_html):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for node in (data if isinstance(data, list) else data.get("@graph", [data])):
            if isinstance(node, dict) and node.get("@type") == "Event":
                place = node.get("location") if isinstance(node.get("location"), dict) else {}
                address = place.get("address", "")
                if isinstance(address, dict):
                    address = ", ".join(str(address.get(k, "")) for k in ("streetAddress", "addressLocality") if address.get(k))
                end = None
                try:
                    end = datetime.fromisoformat(node["endDate"]).astimezone(LOCAL_TZ) if node.get("endDate") else None
                except ValueError:
                    pass
                return {"end": end, "place": html.unescape(str(place.get("name", ""))).strip(), "address": str(address).strip()}
    return {}


def fetch_event_page(url: str) -> dict:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    return parse_event_page(response.text)


def _elsewhere(text: str) -> bool:
    """True when the text puts the event in another Minnesota town and never mentions Eden Prairie."""
    if "eden prairie" in text.lower():
        return False
    return any(m.group(1) != "Eden Prairie" for m in _OTHER_TOWN.finditer(text))


def import_events(feed_text: str, today: date | None = None, fetch_page=fetch_event_page, pause: float = 1.0,
                  db_path=storage.DB_PATH) -> dict:
    """Parse the feed and store new events as suggestions. Returns counts: seen, new, skipped_elsewhere,
    skipped_known, skipped_past."""
    today = today or datetime.now(LOCAL_TZ).date()
    counts = {"seen": 0, "new": 0, "skipped_elsewhere": 0, "skipped_known": 0, "skipped_past": 0}
    taken: set[str] = set()
    lookups = 0
    for item in sorted(parse_items(feed_text), key=lambda i: i.start):
        counts["seen"] += 1
        if item.start.date() < today:
            counts["skipped_past"] += 1
            continue
        if item.base_url in taken or storage.event_already_known(item.base_url, today.isoformat(), db_path):
            counts["skipped_known"] += 1
            continue
        taken.add(item.base_url)
        details = {}
        if lookups < MAX_PAGE_LOOKUPS:
            lookups += 1
            try:
                details = fetch_page(item.link)
            except Exception as exc:  # the page is only a bonus; the feed already gave a date and a time
                logger.warning("event page %s unreadable: %s", item.link, exc)
            if lookups > 1 and pause:
                time.sleep(pause)
        place = ", ".join(p for p in (details.get("place"), details.get("address")) if p)
        place = re.sub(r"(?<=[a-z])(?=Eden Prairie)", ", ", place)  # the site sometimes joins "...Pkwy" and "Eden Prairie"
        if _elsewhere(f"{item.title} {item.text} {place}"):
            counts["skipped_elsewhere"] += 1
            continue
        end = details.get("end")
        if end and not (end.date() == item.start.date() and end > item.start):
            end = None  # an end that is not after the start (the site's "00:00") or on another day tells us nothing
        storage.insert_events(None, item.base_url, [EventCandidate(
            title=item.title, start_date=item.start.date(), start_time=item.start.strftime("%H:%M"),
            end_time=end.strftime("%H:%M") if end and end.date() == item.start.date() else "",
            location=place, location_source="feed" if place else "", snippet=item.text[:300])], db_path)
        counts["new"] += 1
    return counts


def import_from_url(url: str, **kwargs) -> dict:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return import_events(response.text, **kwargs)
