"""Google Calendar links and iCalendar files."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from icalendar import Calendar
from icalendar import Event as VEvent

from .models import Event

DEFAULT_LENGTH = timedelta(hours=3)


def _end(e: Event) -> datetime:
    if e.end and e.end > e.start:
        return e.end
    return e.start + (timedelta(days=1) if e.all_day else DEFAULT_LENGTH)


def _all_day_end(e: Event):
    """Exclusive end date for all-day events."""
    if e.end and e.end.date() >= e.start.date():
        return e.end.date() + timedelta(days=1)
    return e.start.date() + timedelta(days=1)


def google_url(e: Event) -> str:
    if e.all_day:
        dates = f"{e.start:%Y%m%d}/{_all_day_end(e):%Y%m%d}"
    else:
        fmt = "%Y%m%dT%H%M%SZ"
        dates = f"{e.start.astimezone(timezone.utc):{fmt}}/{_end(e).astimezone(timezone.utc):{fmt}}"
    details = "\n\n".join(x for x in (e.why, e.description[:400], e.url) if x)
    q = {"action": "TEMPLATE", "text": e.title, "dates": dates, "location": f"{e.venue}, {e.city}", "details": details}
    return "https://calendar.google.com/calendar/render?" + urlencode(q)


def _vevent(e: Event, stamp: datetime) -> VEvent:
    v = VEvent()
    v.add("uid", f"{e.id}@subradar")
    v.add("dtstamp", stamp)
    v.add("summary", e.title)
    if e.all_day:
        v.add("dtstart", e.start.date())
        v.add("dtend", _all_day_end(e))
    else:
        v.add("dtstart", e.start)
        v.add("dtend", _end(e))
    v.add("location", f"{e.venue}, {e.city}")
    v.add("url", e.url)
    v.add("description", "\n\n".join(x for x in (e.why, e.description, e.url) if x))
    return v


def ics_bytes(events: list[Event], name: str = "SubRadar") -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//SubRadar//bernhardhack//")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", name)
    cal.add("x-wr-timezone", "Europe/Vienna")
    cal.add("refresh-interval", timedelta(hours=12))
    stamp = datetime.now(timezone.utc)
    for e in events:
        cal.add_component(_vevent(e, stamp))
    return cal.to_ical()
