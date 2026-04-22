from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sleep(min_s: float = 1.0, jitter: float = 2.0) -> None:
    time.sleep(min_s + random.random() * jitter)


def build_proxies() -> Optional[dict]:
    proxy = os.getenv("PROXY")
    user = os.getenv("PROXY_USERNAME")
    pw = os.getenv("PROXY_PASSWORD")
    if not (proxy and user and pw):
        return None
    return {scheme: f"http://{user}:{pw}@{proxy}" for scheme in ("http", "https")}


@dataclass
class FetchResult:
    ok: bool
    url: str
    final_url: str
    status: Optional[int]
    content: Optional[bytes]
    headers: Optional[dict]
    error: Optional[str]
    fetched_at: datetime

def fetch(
    url: str,
    proxies: Optional[dict] = None,
    retries: int = 4,
    timeout_s: int = 30,
) -> FetchResult:
    
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=timeout_s, proxies=proxies, allow_redirects=True)

            if resp.status_code in (429, 503, 502, 504):
                logger.info("Status %s attempt %s | %s", resp.status_code, attempt, url)
                sleep(10 * attempt, 10)
                continue

            if resp.ok:
                return FetchResult(
                    ok=True,
                    url=url,
                    final_url=str(resp.url),
                    status=resp.status_code,
                    content=resp.content,
                    headers=dict(resp.headers),
                    error=None,
                    fetched_at=utc_now(),
                )

            logger.info("Status %s attempt %s | %s", resp.status_code, attempt, url)
            sleep(5 * attempt, 5)

        except Exception as exc:
            logger.info("Request error attempt %s | %s | %s", attempt, url, exc)
            sleep(5 * attempt, 5)

    return FetchResult(
        ok=False,
        url=url,
        final_url=url,
        status=None,
        content=None,
        headers=None,
        error=f"Failed after {retries} retries",
        fetched_at=utc_now(),
    )
