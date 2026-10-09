"""Run the whole pipeline and write the static site."""
from __future__ import annotations

import json
import logging
import re
import shutil
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from .ai import Claude
from .calendar import google_url, ics_bytes
from .config import Config, load_config
from .curate import curate
from .extract import extract_source
from .fetch import Fetcher
from .models import Event, SourceConfig, SourceResult
from .outdoor import outdoor_events

log = logging.getLogger(__name__)


def dedupe(events: list[Event]) -> list[Event]:
    seen: dict[str, Event] = {}
    for e in events:
        prev = seen.get(e.id)
        if prev is None or (not prev.image and e.image) or len(e.description) > len(prev.description):
            seen[e.id] = e
    return list(seen.values())


def collect(cfg: Config, fetcher: Fetcher, ai: Claude | None, today: date) -> tuple[list[Event], list[SourceResult]]:
    events: list[Event] = []
    results: list[SourceResult] = []
    for src in cfg.sources:
        if not src.enabled:
            continue
        try:
            found, method = extract_source(src, fetcher, cfg.tz, ai, today)
            found = apply_excludes(found, src)
            events.extend(found)
            results.append(SourceResult(name=src.name, ok=bool(found), method=method, count=len(found)))
            log.info("%-22s %3d events via %s", src.name, len(found), method)
        except Exception as e:  # a dead site never breaks the run
            results.append(SourceResult(name=src.name, ok=False, error=str(e)[:200]))
            log.warning("%-22s failed: %s", src.name, e)
    return events, results


def apply_excludes(events: list[Event], src: SourceConfig) -> list[Event]:
    if not src.exclude:
        return events
    pattern = re.compile("|".join(src.exclude), re.I)
    return [e for e in events if not pattern.search(e.title)]


def cap_repeats(events: list[Event], cfg: Config) -> list[Event]:
    """Recurring programme items (daily shows, tours) keep only their next few dates."""
    limits = {s.name: s.max_repeats for s in cfg.sources}
    seen: dict[tuple[str, str], int] = defaultdict(int)
    keep = []
    for e in sorted(events, key=lambda e: e.start):
        key = (e.source, re.sub(r"\W+", " ", e.title.lower()).strip())
        seen[key] += 1
        if seen[key] <= limits.get(e.source, 2):
            keep.append(e)
    return keep


def window(events: list[Event], cfg: Config, now: datetime) -> list[Event]:
    horizon = now + timedelta(days=cfg.window_days)
    keep = []
    for e in events:
        end = e.end or (e.start + timedelta(hours=3))
        if end >= now and e.start <= horizon:
            keep.append(e)
    return keep


def finish(events: list[Event], cfg: Config) -> None:
    for e in events:
        e.travel = cfg.travel_for(e.city)
        e.gcal = google_url(e)
        e.ics = f"ics/{e.id}.ics"


def write_site(events: list[Event], results: list[SourceResult], cfg: Config, out: Path, web: Path,
               now: datetime, scoring: str, sample: bool = False) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(web, out)
    (out / "data").mkdir(exist_ok=True)
    (out / "ics").mkdir(exist_ok=True)
    events = sorted(events, key=lambda e: e.start)
    for e in events:
        (out / e.ics).write_bytes(ics_bytes([e], name=e.title))
    picks = [e for e in events if (e.score or 0) >= cfg.calendar_min_score]
    (out / "radar.ics").write_bytes(ics_bytes(picks, name="SubRadar"))
    payload = {
        "generated": now.isoformat(),
        "sample": sample,
        "scoring": scoring,
        "bases": {"wien": "Wien", "brunnbach": "Brunnbach"},
        "sources": [r.model_dump() for r in results],
        "events": [e.model_dump(mode="json") for e in events],
    }
    (out / "data" / "events.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def build(root: Path, out: Path, *, use_ai: bool = True, now: datetime | None = None) -> list[SourceResult]:
    cfg = load_config(root)
    now = now or datetime.now(cfg.tz)
    today = now.date()
    ai = Claude(root / ".cache" / "claude") if (use_ai and Claude.available()) else None
    if ai is None:
        log.info("No ANTHROPIC_API_KEY: structured sources only, keyword scoring.")
    fetcher = Fetcher()
    events, results = collect(cfg, fetcher, ai, today)
    events = cap_repeats(window(dedupe(events), cfg, now), cfg)
    scoring = curate(events, cfg, ai, root / "feedback" / "swipes.json")
    events.extend(outdoor_events(cfg, fetcher, today))
    finish(events, cfg)
    write_site(events, results, cfg, out, root / "web", now, scoring)
    log.info("Wrote %d events to %s", len(events), out)
    return results


def build_sample(root: Path, out: Path, fixture: Path) -> None:
    """Render the app with sample data for local design work (never deployed)."""
    cfg = load_config(root)
    now = datetime.now(cfg.tz)
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    base = now.date() + timedelta(days=(4 - now.weekday()) % 7)  # coming Friday
    events = []
    for item in raw:
        offset = item.pop("day_offset")
        hh, mm = map(int, item.pop("time").split(":"))
        start = datetime(base.year, base.month, base.day, hh, mm, tzinfo=cfg.tz) + timedelta(days=offset)
        events.append(Event(start=start, **item))
    finish(events, cfg)
    write_site(events, [], cfg, out, root / "web", now, "sample", sample=True)
