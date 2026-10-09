"""Load sources.yaml and taste.md."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .models import SourceConfig


@dataclass
class Config:
    root: Path
    tz: ZoneInfo
    window_days: int
    calendar_min_score: float
    travel: dict[str, dict[str, int]]
    bases: dict[str, str]
    sources: list[SourceConfig]
    keywords_plus: list[str]
    keywords_minus: list[str]
    outdoor: dict = field(default_factory=dict)
    taste: str = ""

    def travel_for(self, city: str) -> dict[str, int]:
        return dict(self.travel.get(city, {}))


def load_config(root: Path) -> Config:
    raw = yaml.safe_load((root / "sources.yaml").read_text(encoding="utf-8")) or {}
    taste_path = root / "taste.md"
    kw = raw.get("keywords") or {}
    return Config(
        root=root,
        tz=ZoneInfo(raw.get("timezone", "Europe/Vienna")),
        window_days=int(raw.get("window_days", 120)),
        calendar_min_score=float(raw.get("calendar_min_score", 7)),
        travel=raw.get("travel_minutes") or {},
        bases=raw.get("bases") or {"steyr": "Steyr", "wien": "Wien", "brunnbach": "Brunnbach"},
        sources=[SourceConfig(**s) for s in raw.get("sources", [])],
        keywords_plus=[k.lower() for k in kw.get("plus", [])],
        keywords_minus=[k.lower() for k in kw.get("minus", [])],
        outdoor=raw.get("outdoor") or {},
        taste=taste_path.read_text(encoding="utf-8") if taste_path.exists() else "",
    )
