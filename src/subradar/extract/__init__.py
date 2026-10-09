"""Source extraction: calendar feeds first, page data second, Claude last."""
from __future__ import annotations

import logging
from datetime import date
from zoneinfo import ZoneInfo

from ..ai import Claude
from ..fetch import Fetcher
from ..models import Event, SourceConfig
from .html import find_ics_links, find_program_link, page_text, parse_jsonld, soup_of
from .ics import parse_ics
from .llm import extract_with_llm

log = logging.getLogger(__name__)


def extract_source(src: SourceConfig, fetcher: Fetcher, tz: ZoneInfo, ai: Claude | None, today: date) -> tuple[list[Event], str]:
    """Return (events, method). Raises on hard failures so the caller can record them."""
    if src.ics:
        return parse_ics(fetcher.text(src.ics), src, tz), "ics"

    pages: list[tuple[str, str]] = []
    home_html = fetcher.text(src.url)
    pages.append((src.url, home_html))
    program_url = src.program or find_program_link(soup_of(home_html), src.url)
    if program_url and program_url != src.url:
        try:
            pages.insert(0, (program_url, fetcher.text(program_url)))
        except Exception as e:  # programme page failing is not fatal
            log.warning("%s: programme page failed: %s", src.name, e)

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

    # 3. Claude reads the page
    if ai is None:
        return [], "none (no structured data; set ANTHROPIC_API_KEY to read the page)"
    url, html = pages[0]
    return extract_with_llm(page_text(soup_of(html), url), src, url, tz, ai, today), "claude"
