import json
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import httpx
import respx
from icalendar import Calendar

from conftest import FIX, TZ
from subradar.build import build, dedupe
from subradar.calendar import google_url, ics_bytes
from subradar.config import load_config
from subradar.curate import curate, load_swipes
from subradar.models import Event
from subradar.outdoor import weekend_days


def ev(title="Kältekammer", day=16, hour=20, **kw):
    base = dict(title=title, start=datetime(2026, 10, day, hour, 30, tzinfo=TZ), venue="Röda", city="Steyr",
                url="https://www.roeda.at/", source="test")
    base.update(kw)
    return Event(**base)


def test_id_is_stable_and_dedupe_keeps_richer_copy():
    a, b = ev(description=""), ev(title="KÄLTEKAMMER!", description="Mit Support")
    assert a.id == b.id
    assert dedupe([a, b])[0].description == "Mit Support"


def test_google_url_uses_utc_and_exclusive_all_day_end():
    q = parse_qs(urlparse(google_url(ev())).query)
    assert q["dates"] == ["20261016T183000Z/20261016T213000Z"]
    q = parse_qs(urlparse(google_url(ev(all_day=True, hour=0))).query)
    assert q["dates"] == ["20261016/20261017"]


def test_ics_roundtrip():
    cal = Calendar.from_ical(ics_bytes([ev(), ev("Zweites", day=17)]))
    assert [str(c["SUMMARY"]) for c in cal.walk("VEVENT")] == ["Kältekammer", "Zweites"]


def test_weekend_days():
    from datetime import date
    assert weekend_days(date(2026, 10, 9)) == [date(2026, 10, 10), date(2026, 10, 11)]  # Fri
    assert weekend_days(date(2026, 10, 11)) == [date(2026, 10, 11)]  # Sun


def test_keyword_scoring_without_key(project):
    cfg = load_config(project)
    events = [ev("Post-Punk Abend"), ev("Tribute to Queen", day=17)]
    assert curate(events, cfg, None, project / "feedback" / "swipes.json") == "keywords"
    assert events[0].score > events[1].score


def test_claude_scoring_uses_swipes(project, fake_claude):
    (project / "feedback" / "swipes.json").write_text(json.dumps(
        {"swipes": [{"id": "x", "title": "Old Noise Gig", "venue": "KAPU", "verdict": "yes"}, {"bad": 1}]}))
    events = [ev(), ev("Schlagerparty", day=17)]
    ids = [e.id for e in events]
    ai, msgs = fake_claude(lambda kw: {"scores": [
        {"id": ids[0], "score": 12, "why": "Darkwave in Steyr.", "tags": ["Darkwave"], "advance": False},
        {"id": "unknown", "score": 9, "why": "", "tags": [], "advance": True},
    ]})
    cfg = load_config(project)
    curate(events, cfg, ai, project / "feedback" / "swipes.json")
    assert "Old Noise Gig" in msgs.calls[0]["messages"][0]["content"]
    assert events[0].score == 10 and events[0].tags == ["darkwave"]
    assert events[1].score is not None  # missing from reply -> keyword fallback


def test_load_swipes_tolerates_garbage(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json")
    assert load_swipes(p) == []


@respx.mock
def test_build_survives_dead_sites(project, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    respx.get(url__regex=r"https://(www\.)?roeda\.at/.*").respond(200, text=(FIX / "jsonld_page.html").read_text())
    respx.get(url__regex=r".*open-meteo.*").respond(200, json={"daily": {
        "time": ["2026-10-10", "2026-10-11"], "precipitation_probability_max": [10, 80], "temperature_2m_max": [16.4, 9]}})
    respx.route().mock(side_effect=httpx.ConnectError("down"))
    monkeypatch.setattr("subradar.fetch.time.sleep", lambda s: None)

    out = project / "site"
    results = build(project, out, now=datetime(2026, 10, 9, 12, 0, tzinfo=TZ))
    data = json.loads((out / "data" / "events.json").read_text())

    ok = {r.name: r.ok for r in results}
    assert ok["Kulturverein Röda"] and not ok["KAPU"]
    titles = [e["title"] for e in data["events"]]
    assert "Noise & Static" in titles
    hikes = [e for e in data["events"] if e["kind"] == "outdoor"]
    assert len(hikes) == 1 and hikes[0]["start"].startswith("2026-10-10")
    first = next(e for e in data["events"] if e["title"] == "Noise & Static")
    assert first["travel"]["brunnbach"] == 40 and first["gcal"].startswith("https://calendar.google.com")
    assert (out / first["ics"]).exists() and (out / "radar.ics").exists() and (out / "index.html").exists()


def test_excludes_and_repeat_cap(project):
    from subradar.build import apply_excludes, cap_repeats
    from subradar.models import SourceConfig

    cfg = load_config(project)
    src = SourceConfig(name="test", city="Linz", url="https://x", exclude=["Deep Space", "führung"])
    events = [ev("Deep Space Selection (DE)"), ev("Highlightführung"), ev("Noise Talk")]
    assert [e.title for e in apply_excludes(events, src)] == ["Noise Talk"]
    daily = [ev("Kinoabend", day=d) for d in range(10, 16)]
    assert len(cap_repeats(daily, cfg)) == 2


def test_local_times_ignores_wrong_utc_label():
    from subradar.extract.html import parse_jsonld, soup_of
    from subradar.models import SourceConfig

    html = '<script type="application/ld+json">{"@type":"Event","name":"Talk 14:00","startDate":"2026-10-09T14:00:00Z","location":{"name":"Anmeldung an der Kassa erforderlich"}}</script>'
    src = SourceConfig(name="Ars", city="Linz", url="https://x/", local_times=True)
    e = parse_jsonld(soup_of(html), src, "https://x/", TZ)[0]
    assert e.start.hour == 14 and e.venue == "Ars"


def test_empty_model_variable_falls_back_to_default(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from subradar.ai import DEFAULT_MODEL, Claude

    monkeypatch.setenv("SUBRADAR_MODEL", "")  # what GitHub passes for an unset repo variable
    assert Claude(tmp_path, client=SimpleNamespace()).model == DEFAULT_MODEL
