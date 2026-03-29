from __future__ import annotations

import argparse
import hashlib
import logging
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse
from typing import Optional
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING
import requests
from urllib.parse import urljoin, urlparse
import re

ROOT = "https://www.ola.org/en/legislative-business/house-documents"

# Build proxies from environment variables, returns none if any are missing. A proxy is just a middleman
def build_proxies() -> Optional[dict]:
    proxy = os.getenv("PROXY")
    user = os.getenv("PROXY_USERNAME")
    pw = os.getenv("PROXY_PASSWORD")
    if not (proxy and user and pw):
        return None
    return {scheme: f"http://{user}:{pw}@{proxy}" for scheme in ("http", "https")}

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sleep(min_s: float = 1.0, jitter: float = 2.0) -> None:
    time.sleep(min_s + random.random() * jitter)

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
    proxies: Optional[dict],
    retries: int = 4,
    timeout_s: int = 30,
) -> FetchResult:

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=timeout_s, proxies=proxies, allow_redirects=True)

            # Retry on certain status codes
            if resp.status_code in (429, 503, 502, 504):
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
            sleep(5 * attempt, 5)

        except Exception as exc:
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


#this matches the hansard session pages and the hansard day pages
SESSION_RE = re.compile(r"^/en/legislative-business/house-documents/parliament-\d+/session-\d+/?$")
HANSARD_DAY_RE = re.compile(
    r"^/en/legislative-business/house-documents/parliament-\d+/session-\d+/\d{4}-\d{2}-\d{2}/hansard(-\d+)?/?$"
)
def discover_session_urls(root_html: bytes) -> list[str]:
    soup = BeautifulSoup(root_html, "html.parser")
    out = set() #create a set for results to avoid duplicates
    for a in soup.find_all("a", href=True):
        href = a["href"].strip() #gets the clickable link that matches the regex
        if SESSION_RE.match(href):
            out.add(urljoin(ROOT, href))
    return sorted(out)


def discover_hansard_day_urls(session_html: bytes) -> list[str]:
    soup = BeautifulSoup(session_html, "html.parser")
    out = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if HANSARD_DAY_RE.match(href):
            out.add(urljoin(ROOT, href))
    return sorted(out)