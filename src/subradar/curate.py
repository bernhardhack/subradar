"""Score events against Ben's taste — Claude when available, keywords otherwise."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .ai import Claude
from .config import Config
from .models import Event

log = logging.getLogger(__name__)

BATCH = 30

SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "score": {"type": "number", "description": "0-10, how much this person would want to go"},
                    "why": {"type": "string", "description": "One short German sentence addressed to the person (du), max 110 characters, concrete, no hype"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "1-3 short lowercase genre/format tags, e.g. post-punk, medienkunst, lesung"},
                    "advance": {"type": "boolean", "description": "True if likely to sell out or a rare chance: book early"},
                },
                "required": ["id", "score", "why", "tags", "advance"],
            },
        }
    },
    "required": ["scores"],
}

SYSTEM = (
    "You are a friend with deep knowledge of independent music, media art and subculture in Austria. "
    "Score events for one specific person using their taste notes and their recent swipe decisions. "
    "Be strict: most events should land between 2 and 6; reserve 8+ for clear matches. "
    "If you know the act, use that knowledge; if not, judge from the description and venue."
)


def load_swipes(path: Path, limit: int = 60) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        swipes = data.get("swipes", data) if isinstance(data, dict) else data
        return [s for s in swipes if isinstance(s, dict) and s.get("verdict") in ("yes", "no")][-limit:]
    except (json.JSONDecodeError, OSError) as e:
        log.warning("could not read swipes: %s", e)
        return []


def _swipe_lines(swipes: list[dict]) -> str:
    if not swipes:
        return "(no swipes yet)"
    return "\n".join(
        f"- {'YES' if s['verdict'] == 'yes' else 'no '}: {s.get('title', '?')} @ {s.get('venue', '?')} {s.get('tags', [])}"
        for s in swipes
    )


def score_with_claude(events: list[Event], cfg: Config, ai: Claude, swipes: list[dict]) -> None:
    by_id = {e.id: e for e in events}
    todo = [e for e in events if e.kind == "event"]
    for i in range(0, len(todo), BATCH):
        batch = todo[i : i + BATCH]
        listing = "\n".join(
            json.dumps(
                {"id": e.id, "title": e.title, "venue": e.venue, "city": e.city,
                 "date": e.start.strftime("%a %Y-%m-%d %H:%M"), "description": e.description[:300]},
                ensure_ascii=False,
            )
            for e in batch
        )
        prompt = (
            f"Taste notes:\n{cfg.taste}\n\nRecent swipes (YES = wanted to go):\n{_swipe_lines(swipes)}\n\n"
            f"Score each of these events:\n{listing}"
        )
        try:
            result = ai.structured(system=SYSTEM, prompt=prompt, tool_name="scores", schema=SCHEMA)
        except Exception as e:
            log.warning("scoring batch failed, using keywords: %s", e)
            score_with_keywords(batch, cfg)
            continue
        for s in result.get("scores", []):
            ev = by_id.get(s.get("id", ""))
            if ev is None:
                continue
            ev.score = max(0.0, min(10.0, float(s.get("score", 0))))
            ev.why = str(s.get("why", ""))[:140]
            ev.tags = [str(t).lower()[:24] for t in s.get("tags", [])][:3]
            ev.advance = bool(s.get("advance", False))
        score_with_keywords([e for e in batch if e.score is None], cfg)


def score_with_keywords(events: list[Event], cfg: Config) -> None:
    for e in events:
        if e.kind != "event":
            continue
        hay = f"{e.title} {e.description}".lower()
        plus = [k for k in cfg.keywords_plus if k in hay]
        minus = [k for k in cfg.keywords_minus if k in hay]
        e.score = max(0.0, min(10.0, 4.0 + 1.5 * len(plus) - 3.0 * len(minus)))
        e.tags = e.tags or plus[:3]
        e.why = e.why or (f"Passt zu: {', '.join(plus[:3])}" if plus else "")


def curate(events: list[Event], cfg: Config, ai: Claude | None, swipes_path: Path) -> str:
    if ai is not None:
        score_with_claude(events, cfg, ai, load_swipes(swipes_path))
        return "claude"
    score_with_keywords(events, cfg)
    return "keywords"
