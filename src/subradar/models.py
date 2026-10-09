"""Data models shared across the pipeline."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from pydantic import BaseModel, Field, computed_field


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


class Event(BaseModel):
    title: str
    start: datetime  # always timezone-aware
    end: datetime | None = None
    all_day: bool = False
    venue: str
    city: str
    url: str
    source: str
    description: str = ""
    image: str | None = None
    kind: str = "event"  # "event" or "outdoor"

    # filled in by the curator
    score: float | None = None
    why: str = ""
    tags: list[str] = Field(default_factory=list)
    advance: bool = False  # worth booking early

    # filled in by the builder
    travel: dict[str, int] = Field(default_factory=dict)
    gcal: str = ""
    ics: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        key = f"{_norm(self.venue)}|{_norm(self.title)}|{self.start.date().isoformat()}"
        return hashlib.sha1(key.encode()).hexdigest()[:12]


class SourceConfig(BaseModel):
    name: str
    city: str
    url: str
    ics: str | None = None
    program: str | None = None
    enabled: bool = True


class SourceResult(BaseModel):
    name: str
    ok: bool
    method: str = ""
    count: int = 0
    error: str = ""
