"""The text of the subreddit's events wiki page, built from approved events. Pure string work, no I/O."""

from datetime import date, datetime

INTRO = "*Updated {updated}. Gathered from local news and checked by the moderators; please confirm details with the linked source before you go.*"


def _when(event: dict) -> str:
    start = date.fromisoformat(event["start_date"])
    text = start.strftime("%a, %b ") + str(start.day)
    if event.get("end_date"):
        end = date.fromisoformat(event["end_date"])
        text += f"-{end.day}" if end.month == start.month else end.strftime(" - %b ") + str(end.day)
    if event.get("start_time"):
        start, end = _clock(event["start_time"]), _clock(event["end_time"]) if event.get("end_time") else ""
        if end and start[-2:] == end[-2:]:
            start = start[:-3]  # "6 to 8 pm", not "6 pm to 8 pm"
        text += " · " + start + (f" to {end}" if end else "")
    return text


def _clock(hhmm: str) -> str:
    t = datetime.strptime(hhmm, "%H:%M")
    return t.strftime("%-I:%M %p").replace(":00", "").lower()


def when_text(event: dict) -> str:
    """'Sat, Nov 21 · 6 to 8 pm' -- the same wording the wiki page uses."""
    return _when(event)


def line(event: dict) -> str:
    """One event as the wiki page will show it (without the leading dash)."""
    parts = [f"**{_when(event)}**", event["title"]]
    if event.get("location"):
        parts.append(event["location"])
    if event.get("source_url"):
        parts.append(f"[source]({event['source_url']})")
    return " · ".join(parts)


def render(events: list[dict], today: date) -> str:
    """Markdown for the wiki page: approved events that have not ended, grouped by month, soonest first."""
    upcoming = [e for e in events if date.fromisoformat(e.get("end_date") or e["start_date"]) >= today]
    upcoming.sort(key=lambda e: (e["start_date"], e.get("start_time") or ""))
    lines = ["# Eden Prairie events", "", INTRO.format(updated=today.strftime("%B %-d, %Y")), ""]
    if not upcoming:
        return "\n".join(lines + ["No upcoming events are listed right now."]) + "\n"
    month = None
    for e in upcoming:
        key = e["start_date"][:7]
        if key != month:
            month = key
            lines += ["", f"## {date.fromisoformat(e['start_date']).strftime('%B %Y')}", ""]
        lines.append("- " + line(e))
    return "\n".join(lines) + "\n"
