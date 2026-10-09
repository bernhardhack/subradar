"""Suggest a hike on dry weekend days near Brunnbach (forecast from Open-Meteo, no key needed)."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import Config
from .fetch import Fetcher
from .models import Event

log = logging.getLogger(__name__)

API = "https://api.open-meteo.com/v1/forecast"


def weekend_days(today: date) -> list[date]:
    """Saturday and Sunday of the current or coming weekend."""
    sat = today + timedelta(days=(5 - today.weekday()) % 7)
    if today.weekday() == 6:
        return [today]
    return [sat, sat + timedelta(days=1)]


def outdoor_events(cfg: Config, fetcher: Fetcher, today: date) -> list[Event]:
    conf = cfg.outdoor
    routes = conf.get("routes") or []
    loc = conf.get("location") or {}
    if not routes or "lat" not in loc:
        return []
    days = weekend_days(today)
    try:
        r = fetcher.get(
            f"{API}?latitude={loc['lat']}&longitude={loc['lon']}&timezone={cfg.tz.key}"
            "&daily=precipitation_probability_max,temperature_2m_max&forecast_days=10"
        )
        daily = r.json()["daily"]
        forecast = dict(zip(daily["time"], zip(daily["precipitation_probability_max"], daily["temperature_2m_max"])))
    except Exception as e:
        log.warning("weather forecast unavailable: %s", e)
        return []

    week = today.isocalendar().week
    out: list[Event] = []
    for i, d in enumerate(days):
        rain, tmax = forecast.get(d.isoformat(), (None, None))
        if rain is None or rain >= 40:
            continue
        route = routes[(week * 2 + i) % len(routes)]
        out.append(
            Event(
                title=route["name"],
                start=datetime.combine(d, time(9, 0), tzinfo=ZoneInfo(cfg.tz.key)),
                end=datetime.combine(d, time(16, 0), tzinfo=ZoneInfo(cfg.tz.key)),
                venue=loc.get("name", "Brunnbach"),
                city=loc.get("name", "Brunnbach"),
                url=route.get("url", ""),
                source="Wetter",
                description=route.get("note", ""),
                kind="outdoor",
                score=7.0,
                why=f"Trocken angesagt: {int(rain)} % Regenrisiko, bis {round(tmax)} °C.",
                tags=["draußen"],
            )
        )
    return out
