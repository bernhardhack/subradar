# SubRadar

A personal weekend radar for independent culture in Upper Austria and Vienna. Every morning a GitHub Action collects venue programmes, has Claude score each event against my taste, and publishes a swipe app to GitHub Pages.

Swipe right ("hin") to save, left ("nö") to skip. Saved events get Google Calendar and `.ics` links. The best picks also appear in a calendar feed you can subscribe to.

## How it works

```
sources.yaml ──► fetch ──► extract ──► score ──► site/
                            │            │        ├─ index.html, app.js, app.css   (swipe app)
       calendar feed (.ics) ┤   taste.md ┤        ├─ data/events.json
   schema.org data on page  ┤   swipes   ┘        ├─ radar.ics                      (subscribable: score ≥ 7)
 Claude reads the page text ┘                     └─ ics/<id>.ics                   (one per event)
```

- **Extraction** tries the cheapest reliable route first: a calendar feed, then schema.org event data on the page, and only then Claude reading the page text. Claude has to quote the date from the page; events whose quote isn't really on the page are dropped, so it can't invent dates.
- **Scoring** reads `taste.md` and your recent swipes (`feedback/swipes.json`). Without an API key it falls back to the keyword lists in `sources.yaml`.
- **"Ich bin in" Steyr / Wien / Brunnbach** re-sorts by travel time (`bases` and `travel_minutes` in `sources.yaml`).
- **Programm tab**: everything coming up, day by day, without deciding anything. "Nur Top-Tipps" narrows it to scores of 7+, and "Merken" saves an event straight to Gemerkt.
- **Moving to another device**: Gemerkt → "Auf anderes Gerät übertragen" makes a link that carries your decisions. Open it on the other device and they are merged in. There's no account and nothing is stored on a server.
- **Hikes**: on dry weekend days (Open-Meteo forecast) one route from `sources.yaml` is suggested.
- **Robustness**: a dead site never breaks the run. The footer of the app lists each source and how it was read. If `NTFY_TOPIC` is set, failing sources trigger a push.
- **Claude calls are cached** (`.cache/`, kept between Action runs), so unchanged pages cost nothing.

## Setup

1. Repository secrets (Settings → Secrets and variables → Actions):
   - `ANTHROPIC_API_KEY` — needed for reading pages without structured data, and for scoring.
   - `NTFY_TOPIC` (optional) — an ntfy.sh topic name for alerts and the Thursday "Dein Wochenende" push.
   - Variable `SUBRADAR_MODEL` (optional) — defaults to `claude-haiku-4-5`.
2. Settings → Pages → Source: **GitHub Actions**.
3. Actions → Radar → **Run workflow**. The app goes live at `https://<user>.github.io/subradar/`.
4. On the phone: open the page, "Zum Home-Bildschirm" for an app icon. In the Gemerkt tab, "Top-Tipps als Kalender abonnieren" adds the radar feed to your calendar.

## Teaching it your taste

Edit `taste.md` in your own words. Then, every week or two: Gemerkt → "Swipes exportieren", and commit the file as `feedback/swipes.json`. The next run uses your last 60 decisions as examples.

Note: in a public repo, `taste.md` and `swipes.json` are public too.

## Local use

```bash
uv run subradar sample   # design work with sample data, never deployed
uv run subradar serve    # http://localhost:8000
uv run subradar build    # real run (set ANTHROPIC_API_KEY for the full pipeline)
uv run --group dev pytest
```

## Adding a venue

Add three lines to `sources.yaml` (`name`, `city`, `url`). If the venue has a calendar feed, add `ics:`; if the programme lives on an odd URL, add `program:`. Check the footer of the app after the next run to see how it was read.

## Next steps

- Sync swipes across devices and serve a personal "saved" calendar feed from a small API (e.g. on the reader droplet), replacing the export step.
- More sources: Vienna venues (Fluc, rhiz are in the config but disabled until checked), and a regional calendar of independent culture initiatives, if one is available, could replace several scrapers at once.
