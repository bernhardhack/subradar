"""Command line: subradar build | sample | serve"""
from __future__ import annotations

import argparse
import functools
import http.server
import logging
import os
from pathlib import Path

import httpx

from .build import build, build_sample


def notify_failures(results) -> None:
    failed = [r for r in results if not r.ok]
    topic = os.environ.get("NTFY_TOPIC")
    if not failed or not topic:
        return
    lines = "\n".join(f"- {r.name}: {r.error or r.method or 'no events'}" for r in failed)
    try:
        httpx.post(
            f"https://ntfy.sh/{topic}",
            content=f"{len(failed)} source(s) returned nothing:\n{lines}".encode(),
            headers={"Title": "SubRadar: sources need a look", "Tags": "warning"},
            timeout=10,
        )
    except httpx.HTTPError as e:
        logging.warning("ntfy failed: %s", e)


def send_digest(site: Path, url: str) -> None:
    """Thursday push: the five best weekend picks."""
    import json
    from datetime import datetime, timedelta

    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC not set, skipping digest")
        return
    data = json.loads((site / "data" / "events.json").read_text(encoding="utf-8"))
    now = datetime.fromisoformat(data["generated"])
    fri = (now + timedelta(days=(4 - now.weekday()) % 7)).date()
    days = {fri, fri + timedelta(days=1), fri + timedelta(days=2)}
    picks = sorted(
        (e for e in data["events"] if datetime.fromisoformat(e["start"]).date() in days),
        key=lambda e: -(e.get("score") or 0),
    )[:5]
    if not picks:
        return
    lines = "\n".join(
        f"{datetime.fromisoformat(e['start']):%a %H:%M}  {e['title']} ({e['venue']}, {e['city']})" for e in picks
    )
    httpx.post(
        f"https://ntfy.sh/{topic}",
        content=lines.encode(),
        headers={"Title": "Dein Wochenende", "Click": url, "Tags": "calendar"},
        timeout=10,
    )


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="subradar")
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--out", type=Path, default=None, help="output folder (default: <root>/site)")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="fetch sources, score, write the site")
    b.add_argument("--no-ai", action="store_true", help="skip Claude even if a key is set")
    sub.add_parser("sample", help="write the site with sample data for design work")
    d = sub.add_parser("digest", help="push the weekend's top picks to ntfy")
    d.add_argument("--url", default="https://bernhardhack.github.io/subradar/")
    s = sub.add_parser("serve", help="serve the site locally")
    s.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request drowns the log
    out = args.out or args.root / "site"

    if args.cmd == "build":
        results = build(args.root, out, use_ai=not args.no_ai)
        notify_failures(results)
    elif args.cmd == "sample":
        build_sample(args.root, out, args.root / "tests" / "fixtures" / "sample_events.json")
        print(f"Sample site written to {out}")
    elif args.cmd == "digest":
        send_digest(out, args.url)
    elif args.cmd == "serve":
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
        print(f"http://localhost:{args.port}")
        http.server.ThreadingHTTPServer(("", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
