"""Find dates, times and places for events in an article's text, with plain rules (standard library only).

Deliberately modest: it proposes *candidates* and a person approves each one on the Events page before it
reaches the calendar, so a missed or wrong guess costs a click, not a wrong public post. When the place or the
time cannot be told, the field is left empty rather than guessed.

Only the article's title and feed summary are read (that is all the tool stores), so an event described only in
the full article body will not be seen.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

VENUES_PATH = Path(__file__).resolve().parent.parent / "config" / "venues.yaml"

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_WEEKDAY = r"(?:Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun)(?:day|sday|nesday|rsday|urday)?"
_DATE = re.compile(
    rf"(?:\b{_WEEKDAY}\.?,?\s+)?\b(?P<mon>{_MONTH})\.?\s+(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?\b"
    rf"(?:\s*(?:-|–|—|to|through)\s*(?:{_MONTH}\.?\s+)?(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?\b)?"
    r"(?:,?\s+(?P<year>20\d\d)\b)?"
)
_TIME = re.compile(r"\b(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>[ap])\.?m\.?(?=\W|$)", re.I)
_TIME_RANGE = re.compile(
    r"\b(?P<h1>\d{1,2})(?::(?P<m1>\d{2}))?\s*(?P<ap1>[ap]\.?m\.?)?\s*(?:-|–|—|to|until)\s*"
    r"(?P<h2>\d{1,2})(?::(?P<m2>\d{2}))?\s*(?P<ap2>[ap])\.?m\.?(?=\W|$)", re.I
)
_ADDRESS = re.compile(
    r"\b\d{3,5}\s+(?:[NSEW]\.?\s+)?[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?\s+"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Pkwy|Parkway|Way|Ln|Lane|Ct|Court|Cir|Circle|Pl|Place|Trl|Trail)\b\.?"
)
_AT_PLACE = re.compile(
    r"\bat\s+(?:the\s+)?(?P<place>[A-Z][\w'’&-]*(?:\s+(?:of|and|&|the|de|at)?\s*[A-Z][\w'’&-]*){0,5})(?!\w)"
)
_CUES = re.compile(
    r"\b(meeting|open house|festival|hearing|concert|market|fair|sale|registration|workshop|class|game|tournament|"
    r"performance|show|parade|run|walk|event|ceremony|forum|session|clinic|tour|celebration|fundraiser|drive|"
    r"will be held|will host|hosts?|begins?|opens?|doors|tickets|rsvp|free|join|come|ribbon|dedication|"
    r"town hall|council|commission|board|story ?time|fireworks|market|picnic|trick|santa|tree lighting)\b", re.I
)
_NOT_PLACES = {"The", "A", "An", "This", "That", "It", "He", "She", "They", "We", "Our", "Their"}
_ABBREV = re.compile(r"\b(a\.m|p\.m|Mr|Mrs|Ms|Dr|St|Ave|Rd|Blvd|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|No|vs)\.", re.I)


@dataclass
class EventCandidate:
    title: str
    start_date: date
    start_time: str = ""  # "HH:MM" 24 h, or ""
    end_time: str = ""
    end_date: date | None = None  # for "Nov. 21-23"
    location: str = ""
    location_source: str = ""  # "venue" | "address" | "phrase" | ""
    snippet: str = ""

    @property
    def key(self) -> tuple:
        return (self.start_date.isoformat(), self.start_time, self.location.lower())


def load_venues(path: Path = VENUES_PATH) -> list[str]:
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except OSError:
        return []
    return sorted((str(v) for v in raw.get("venues", [])), key=len, reverse=True)  # longest first: "Staring Lake Outdoor Center" before "Staring Lake"


def _sentences(text: str) -> list[str]:
    protected = _ABBREV.sub(lambda m: m.group(0)[:-1] + "\x00", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[\"“(]?[A-Z0-9])", protected)
    return [p.replace("\x00", ".").strip() for p in parts if p.strip()]


def _resolve_date(mon: str, day: int, year: str | None, ref: date) -> date | None:
    month = _MONTHS[mon[:3].lower()]
    try:
        if year:
            return date(int(year), month, day)
        candidate = date(ref.year, month, day)
        if candidate < ref - timedelta(days=30):  # "Jan. 5" read in December means next January
            candidate = date(ref.year + 1, month, day)
        return candidate
    except ValueError:
        return None


def _to_24h(hour: int, minute: str | None, ap: str) -> str | None:
    if not 1 <= hour <= 12:
        return None
    hour = hour % 12 + (12 if ap.lower().startswith("p") else 0)
    return f"{hour:02d}:{int(minute or 0):02d}"


def _times(text: str) -> tuple[str, str]:
    """(start, end) as HH:MM; end is '' when there is no range."""
    m = _TIME_RANGE.search(text)
    if m:
        ap2 = m.group("ap2")
        ap1 = (m.group("ap1") or ap2)[0]
        start, end = _to_24h(int(m.group("h1")), m.group("m1"), ap1), _to_24h(int(m.group("h2")), m.group("m2"), ap2)
        if start and end:
            return start, end
    m = _TIME.search(text)
    if m:
        t = _to_24h(int(m.group("h")), m.group("m"), m.group("ap"))
        if t:
            return t, ""
    if re.search(r"\bnoon\b", text, re.I):
        return "12:00", ""
    return "", ""


def _location(context: str, venues: list[str]) -> tuple[str, str]:
    low = context.lower()
    for venue in venues:
        if venue.lower() in low:
            return venue, "venue"
    m = _ADDRESS.search(context)
    if m:
        return m.group(0).strip(" ."), "address"
    for m in _AT_PLACE.finditer(context):
        place = m.group("place").strip(" .,")
        first = place.split()[0]
        if first in _NOT_PLACES or re.fullmatch(_MONTH, first.rstrip(".")) or _TIME.match(place) or first.isdigit():
            continue
        return place, "phrase"
    return "", ""


def extract_events(title: str, text: str, reference: date, venues: list[str] | None = None) -> list[EventCandidate]:
    """Candidates found in `text` (title + summary). `reference` is the article's publish date: dates before it
    are treated as things that already happened and skipped, and a missing year is inferred from it."""
    venues = load_venues() if venues is None else venues
    sentences = _sentences(text)
    found: dict[tuple, EventCandidate] = {}
    for i, sentence in enumerate(sentences):
        for m in _DATE.finditer(sentence):
            start = _resolve_date(m.group("mon"), int(m.group("d1")), m.group("year"), reference)
            if start is None or start < reference - timedelta(days=1):
                continue
            end = None
            if m.group("d2"):
                end = _resolve_date(m.group("mon"), int(m.group("d2")), m.group("year"), reference)
                end = end if end and end > start else None
            context = " ".join(sentences[i:i + 2])  # this sentence and the next: time and place often follow the date
            start_time, end_time = _times(sentence) if _times(sentence)[0] else _times(sentences[i + 1] if i + 1 < len(sentences) else "")
            if not (_CUES.search(context) or start_time):  # event wording, or a clock time next to the date
                continue
            location, source = _location(sentence, venues)  # this sentence first, then the next one
            if not location and i + 1 < len(sentences):
                location, source = _location(sentences[i + 1], venues)
            candidate = EventCandidate(title=title.strip(), start_date=start, end_date=end, start_time=start_time,
                                       end_time=end_time, location=location, location_source=source, snippet=sentence[:300])
            found.setdefault(candidate.key, candidate)
    return sorted(found.values(), key=lambda e: (e.start_date, e.start_time))
