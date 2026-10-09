"""Find structured event data on ordinary web pages."""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from dateutil import parser as dtparser

from ..models import Event, SourceConfig

EVENT_TYPES = {
    "Event", "MusicEvent", "TheaterEvent", "ExhibitionEvent", "Festival", "SocialEvent",
    "ScreeningEvent", "DanceEvent", "LiteraryEvent", "ComedyEvent", "EducationEvent",
    "VisualArtsEvent", "ChildrensEvent", "BusinessEvent",
}
PROGRAM_WORDS = re.compile(r"\b(programm|program|events?|veranstaltungen|kalender|termine|spielplan|konzerte|concerts?|calendar)\b", re.I)


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def find_ics_links(soup: BeautifulSoup, base: str) -> list[str]:
    out = []
    for a in soup.select("a[href], link[href]"):
        href = a["href"].strip()
        low = href.lower()
        if low.startswith("webcal:") or low.endswith(".ics") or "ical=1" in low or "/ical" in low or "format=ical" in low:
            out.append(urljoin(base, href))
    return list(dict.fromkeys(out))


def find_program_link(soup: BeautifulSoup, base: str) -> str | None:
    host = re.sub(r"^https?://(www\.)?", "", base).split("/")[0]
    for a in soup.select("nav a[href], header a[href], a[href]"):
        label = " ".join(a.get_text(" ", strip=True).split())[:40]
        href = urljoin(base, a["href"])
        if host not in href or href.rstrip("/") == base.rstrip("/"):
            continue
        last_segment = href.rstrip("/").rsplit("/", 1)[-1]
        if PROGRAM_WORDS.search(label) or PROGRAM_WORDS.search(last_segment):
            return href
    return None


def _walk(node):
    if isinstance(node, list):
        for n in node:
            yield from _walk(n)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "itemListElement", "item", "subEvent", "event", "events"):
            if key in node:
                yield from _walk(node[key])


def _is_event(node: dict) -> bool:
    t = node.get("@type")
    types = t if isinstance(t, list) else [t]
    return any(x in EVENT_TYPES for x in types if isinstance(x, str))


def _parse_dt(value: str, tz: ZoneInfo, local_times: bool = False) -> tuple[datetime, bool]:
    dt = dtparser.isoparse(value)
    all_day = len(value.strip()) <= 10
    if dt.tzinfo is None or local_times:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.astimezone(tz)
    return dt, all_day


def _text(v) -> str:
    if isinstance(v, list):
        v = v[0] if v else ""
    if isinstance(v, dict):
        v = v.get("url") or v.get("name") or v.get("@id") or ""
    return str(v or "").strip()


def parse_jsonld(soup: BeautifulSoup, src: SourceConfig, base: str, tz: ZoneInfo) -> list[Event]:
    events: list[Event] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk(data):
            if not _is_event(node) or not node.get("startDate") or not node.get("name"):
                continue
            try:
                start, all_day = _parse_dt(str(node["startDate"]), tz, src.local_times)
                end = _parse_dt(str(node["endDate"]), tz, src.local_times)[0] if node.get("endDate") else None
            except (ValueError, OverflowError):
                continue
            loc = node.get("location")
            venue = _text(loc.get("name")) if isinstance(loc, dict) else ""
            desc = BeautifulSoup(_text(node.get("description")), "lxml").get_text(" ", strip=True)
            events.append(
                Event(
                    title=BeautifulSoup(_text(node["name"]), "lxml").get_text(" ", strip=True),
                    start=start,
                    end=end,
                    all_day=all_day,
                    venue=venue if venue and len(venue) < 60 and len(venue.split()) <= 4 else src.name,
                    city=src.city,
                    url=urljoin(base, _text(node.get("url"))) if node.get("url") else base,
                    source=src.name,
                    description=desc[:600],
                    image=urljoin(base, _text(node.get("image"))) if node.get("image") else None,
                )
            )
    return events


def page_text(soup: BeautifulSoup, base: str, limit: int = 40_000) -> str:
    """Readable page text with link targets kept inline, for the LLM extractor."""
    soup = BeautifulSoup(str(soup), "lxml")  # work on a copy
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    for tag in soup.select("footer, [class*=cookie], [id*=cookie]"):
        tag.decompose()
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True)
        if label:
            a.replace_with(f"{label} <{urljoin(base, a['href'])}>")
    for img in soup.find_all("img", src=True):
        img.replace_with(f" [img {urljoin(base, img['src'])}] ")
    text = soup.get_text("\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:limit]
