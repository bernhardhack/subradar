from datetime import date

import httpx
import respx

from conftest import FIX, TZ
from subradar.extract import extract_source
from subradar.extract.html import find_ics_links, find_program_link, page_text, parse_jsonld, soup_of
from subradar.extract.ics import parse_ics
from subradar.extract.llm import evidence_ok, extract_with_llm
from subradar.fetch import Fetcher


def test_jsonld_graph_types_and_broken_blocks(src):
    soup = soup_of((FIX / "jsonld_page.html").read_text())
    events = parse_jsonld(soup, src, "https://venue.example/", TZ)
    assert [e.title for e in events] == ["Noise & Static", "Ganztags-Flohmarkt"]
    noise, market = events
    assert noise.url == "https://venue.example/event/noise"
    assert noise.image == "https://venue.example/img/noise.jpg"
    assert noise.venue == "Saal 2" and noise.description == "Laut."
    assert noise.start.hour == 21 and not noise.all_day
    assert market.all_day and market.venue == "Testhalle"


def test_program_link_stays_on_site(src):
    soup = soup_of((FIX / "jsonld_page.html").read_text())
    assert find_program_link(soup, "https://venue.example/") == "https://venue.example/programm/"


def test_ics_links_found():
    soup = soup_of('<a href="/feed.ics">Kalender</a><a href="webcal://x.example/cal">Abo</a><a href="/x">x</a>')
    assert find_ics_links(soup, "https://venue.example/") == ["https://venue.example/feed.ics", "webcal://x.example/cal"]


def test_ics_parse_skips_broken_entries(src):
    events = parse_ics((FIX / "feed.ics").read_text(), src, TZ)
    assert [e.title for e in events] == ["Darkwave Nacht", "Ausstellung"]
    assert events[0].url == "https://venue.example/darkwave"
    assert events[1].all_day


def test_evidence_guard():
    page = "Programm\nFr 16.10. Einlass 20:00"
    assert evidence_ok("Fr 16.10.", page, date(2026, 10, 16))
    assert not evidence_ok("Fr 16.10.", page, date(2026, 10, 17))  # wrong day
    assert not evidence_ok("Sa 17.10.", page, date(2026, 10, 17))  # quote not on page


def test_llm_extraction_drops_invented_dates(src, fake_claude):
    html = (FIX / "program_text.html").read_text()
    text = page_text(soup_of(html), "https://venue.example/programm/")
    assert "Kältekammer <https://venue.example/e/1>" in text
    assert "Impressum" not in text

    ai, msgs = fake_claude(lambda kw: {"events": [
        {"title": "Kältekammer", "date": "2026-10-16", "start_time": "20:30", "url": "https://venue.example/e/1", "evidence": "Fr 16.10. Einlass 20:00"},
        {"title": "Die Zahnärzte", "date": "2026-10-17", "start_time": "21:00", "evidence": "Sa 17.10. 21:00"},
        {"title": "Erfunden", "date": "2026-10-18", "evidence": "So 18.10."},
        {"title": "Kaputt", "date": "nächste Woche", "evidence": "x"},
    ]})
    events = extract_with_llm(text, src, "https://venue.example/programm/", TZ, ai, date(2026, 10, 9))
    assert [e.title for e in events] == ["Kältekammer", "Die Zahnärzte"]
    assert events[0].start.hour == 20 and events[0].start.minute == 30
    assert events[1].url == "https://venue.example/programm/"

    # second call is served from cache
    extract_with_llm(text, src, "https://venue.example/programm/", TZ, ai, date(2026, 10, 9))
    assert len(msgs.calls) == 1


@respx.mock
def test_extract_source_prefers_jsonld_and_follows_program(src):
    respx.get("https://venue.example/").respond(200, text=(FIX / "jsonld_page.html").read_text())
    respx.get("https://venue.example/programm/").respond(200, text="<html><body>nichts</body></html>")
    events, method = extract_source(src, Fetcher(retries=0), TZ, None, date(2026, 10, 9))
    assert method == "json-ld" and len(events) == 2


@respx.mock
def test_extract_source_without_ai_reports_why(src):
    respx.get("https://venue.example/").respond(200, text=(FIX / "program_text.html").read_text())
    events, method = extract_source(src, Fetcher(retries=0), TZ, None, date(2026, 10, 9))
    assert events == [] and "ANTHROPIC_API_KEY" in method


@respx.mock
def test_fetcher_retries_server_errors_but_not_404():
    route = respx.get("https://flaky.example/").mock(side_effect=[httpx.Response(503), httpx.Response(200, text="ok")])
    assert Fetcher(retries=1, backoff=0).text("https://flaky.example/") == "ok"
    assert route.call_count == 2

    gone = respx.get("https://gone.example/").respond(404)
    try:
        Fetcher(retries=3, backoff=0).text("https://gone.example/")
        raise AssertionError("expected FetchError")
    except Exception as e:
        assert "404" in str(e)
    assert gone.call_count == 1
