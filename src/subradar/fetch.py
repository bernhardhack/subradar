"""Polite HTTP fetching with retries."""
from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "SubRadar/0.1 (personal event radar; +https://github.com/bernhardhack/subradar)"


class FetchError(Exception):
    pass


class _Retryable(Exception):
    pass


class Fetcher:
    def __init__(self, client: httpx.Client | None = None, retries: int = 2, backoff: float = 2.0):
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "de-AT,de;q=0.9,en;q=0.6"},
            timeout=httpx.Timeout(20.0),
            follow_redirects=True,
        )
        self.retries = retries
        self.backoff = backoff

    def get(self, url: str) -> httpx.Response:
        url = url.replace("webcal://", "https://", 1)
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = self.client.get(url)
                if r.status_code >= 500 or r.status_code == 429:
                    raise _Retryable(f"HTTP {r.status_code}")
                if r.status_code >= 400:
                    raise FetchError(f"{url}: HTTP {r.status_code}")  # no retry on 4xx
                return r
            except FetchError:
                raise
            except (_Retryable, httpx.HTTPError) as e:
                last = e
            if attempt < self.retries:
                time.sleep(self.backoff * (attempt + 1))
        raise FetchError(f"{url}: {last}")

    def text(self, url: str) -> str:
        return self.get(url).text
