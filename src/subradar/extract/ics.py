"""Parse iCalendar feeds into events."""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from icalendar import Calendar

from ..models import Event, SourceConfig


def _to_dt(value, tz: ZoneInfo) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        return (value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)), False
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0), tzinfo=tz), True
    raise ValueError(f"unsupported date value: {value!r}")


def parse_ics(text: str, src: SourceConfig, tz: ZoneInfo) -> list[Event]:
    cal = Calendar.from_ical(text)
    events: list[Event] = []
    for comp in cal.walk("VEVENT"):
        try:
            title = str(comp.get("SUMMARY", "")).strip()
            if not title or comp.get("DTSTART") is None:
                continue
            start, all_day = _to_dt(comp.decoded("DTSTART"), tz)
            end = _to_dt(comp.decoded("DTEND"), tz)[0] if comp.get("DTEND") is not None else None
            loc = str(comp.get("LOCATION", "")).strip()
            events.append(
                Event(
                    title=title,
                    start=start,
                    end=end,
                    all_day=all_day,
                    venue=src.name if not loc or len(loc) > 60 else loc,
                    city=src.city,
                    url=str(comp.get("URL", "")).strip() or src.url,
                    source=src.name,
                    description=str(comp.get("DESCRIPTION", "")).strip()[:600],
                )
            )
        except Exception:  # one broken VEVENT must not kill the feed
            continue
    return events
