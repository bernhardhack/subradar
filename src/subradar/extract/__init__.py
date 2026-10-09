"""Source extraction: calendar feeds first, page data second, Claude last."""
from __future__ import annotations

import logging
from datetime import date
from typing import Callable
from zoneinfo import ZoneInfo

from ..ai import Claude
from ..fetch import Fetcher
from ..models import Event, SourceConfig
from .html import find_ics_links, find_program_link, page_text, parse_jsonld, soup_of
from .ics import parse_ics
from .llm import extract_with_llm

log = logging.getLogger(__name__)


def _upcoming(events: list[Event], today: date) -> list[Event]:
    return [e for e in events if (e.end or e.start).date() >= today]


def extract_source(src: SourceConfig, fetcher: Fetcher, tz: ZoneInfo, ai: Claude | None, today: date,
                   renderer: Callable[[str], str] | None = None) -> tuple[list[Event], str]:
    """Return (events, method). Raises on hard failures so the caller can record them."""
    if src.ics:
        return parse_ics(fetcher.text(src.ics), src, tz), "ics"

    pages: list[tuple[str, str]] = []
    fetch_notes: list[str] = []
    home_html = fetcher.text(src.url)
    pages.append((src.url, home_html))
    program_url = src.program or find_program_link(soup_of(home_html), src.url)
    if program_url and program_url != src.url:
        try:
            pages.insert(0, (program_url, fetcher.text(program_url)))
        except Exception as e:  # programme page failing is not fatal
            log.warning("%s: programme page failed: %s", src.name, e)
            fetch_notes.append(f"programme page failed: {str(e)[:80]}")

    # 1. calendar feeds linked from the page
    for url, html in pages:
        for ics_url in find_ics_links(soup_of(html), url)[:2]:
            try:
                events = parse_ics(fetcher.text(ics_url), src, tz)
                if events:
                    return events, f"ics (found {ics_url})"
            except Exception as e:
                log.info("%s: linked calendar %s unusable: %s", src.name, ics_url, e)

    # 2. schema.org event data in the HTML
    for url, html in pages:
        events = parse_jsonld(soup_of(html), src, url, tz)
        if events:
            return events, "json-ld"

    # 3. Claude reads the page: programme page first, then the start page,
    #    then both again rendered in a browser (for sites that load their programme with JavaScript)
    if ai is None:
        return [], "none (no structured data; set ANTHROPIC_API_KEY to read the page)"
    notes: list[str] = list(fetch_notes)

    def read(url: str, html: str, label: str) -> list[Event]:
        stats: dict = {}
        found = extract_with_llm(page_text(soup_of(html), url), src, url, tz, ai, today, stats)
        upcoming = _upcoming(found, today)
        notes.append(f"{label} {url}: {stats.get('chars', 0)} chars of text, {stats.get('found', 0)} events, "
                     f"{stats.get('dropped', 0)} without verifiable date, {len(upcoming)} upcoming")
        return upcoming

    for url, html in pages:
        events = read(url, html, "page")
        if events:
            return events, "claude"
    if renderer is not None:
        for url, _ in pages:
            try:
                html = renderer(url)
            except Exception as e:
                log.info("%s: rendering %s failed: %s", src.name, url, e)
                notes.append(f"render failed {url}: {str(e)[:80]}")
                continue
            for ics_url in find_ics_links(soup_of(html), url)[:1]:
                try:
                    events = _upcoming(parse_ics(fetcher.text(ics_url), src, tz), today)
                    if events:
                        return events, "ics (rendered page)"
                except Exception:
                    pass
            events = _upcoming(parse_jsonld(soup_of(html), src, url, tz), today)
            if events:
                return events, "json-ld (rendered page)"
            events = read(url, html, "rendered")
            if events:
                return events, "claude (rendered page)"
    return [], "claude found no upcoming events. " + " | ".join(notes)
