"""Let Claude read a programme page and return events — with a guard against invented dates."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from ..ai import Claude
from ..models import Event, SourceConfig

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Act or event name as written on the page"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "start_time": {"type": "string", "description": "HH:MM, or empty if unknown"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD for multi-day events, else empty"},
                    "url": {"type": "string", "description": "Detail page link from the <...> markers, else empty"},
                    "image": {"type": "string", "description": "Image URL from [img ...] markers near the event, else empty"},
                    "description": {"type": "string", "description": "One or two sentences from the page, in its language"},
                    "evidence": {"type": "string", "description": "A short verbatim quote from the page that contains the date"},
                },
                "required": ["title", "date", "evidence"],
            },
        }
    },
    "required": ["events"],
}

SYSTEM = (
    "You extract event listings from the text of a venue's web page. Only list events that are "
    "explicitly on the page with a date. Never guess a date or year: if the page gives no year, use "
    "the next occurrence of that day and month after today. Skip opening hours, newsletters and past events."
)


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def evidence_ok(evidence: str, page: str, day: date) -> bool:
    """The quote must really be on the page and must mention the day of the month."""
    ev = _squash(evidence)
    if len(ev) < 4 or ev not in _squash(page):
        return False
    return re.search(rf"(?<!\d)0?{day.day}(?!\d)", ev) is not None


def extract_with_llm(text: str, src: SourceConfig, page_url: str, tz: ZoneInfo, ai: Claude, today: date,
                     stats: dict | None = None) -> list[Event]:
    prompt = (
        f"Today is {today.isoformat()} ({today.strftime('%A')}). Venue: {src.name}, {src.city}.\n"
        f"Page: {page_url}\n\n---\n{text}\n---\n\nList every upcoming event on this page."
    )
    result = ai.structured(system=SYSTEM, prompt=prompt, tool_name="events", schema=SCHEMA)
    events: list[Event] = []
    dropped = 0
    for item in result.get("events", []):
        try:
            d = date.fromisoformat(item["date"])
        except (KeyError, ValueError):
            dropped += 1
            continue
        if not evidence_ok(item.get("evidence", ""), text, d):
            dropped += 1
            continue
        all_day = True
        start = datetime.combine(d, time(0, 0), tzinfo=tz)
        if re.fullmatch(r"\d{1,2}:\d{2}", item.get("start_time") or ""):
            h, m = map(int, item["start_time"].split(":"))
            if h < 24 and m < 60:
                start, all_day = datetime.combine(d, time(h, m), tzinfo=tz), False
        end = None
        if item.get("end_date"):
            try:
                end = datetime.combine(date.fromisoformat(item["end_date"]), time(23, 59), tzinfo=tz)
            except ValueError:
                pass
        events.append(
            Event(
                title=item["title"].strip(),
                start=start,
                end=end,
                all_day=all_day,
                venue=src.name,
                city=src.city,
                url=(item.get("url") or "").strip() or page_url,
                source=src.name,
                description=(item.get("description") or "").strip()[:600],
                image=(item.get("image") or "").strip() or None,
            )
        )
    if dropped:
        log.info("%s: dropped %d events without verifiable date", src.name, dropped)
    if stats is not None:
        stats.update(found=len(result.get("events", [])), dropped=dropped, chars=len(text))
    return events
