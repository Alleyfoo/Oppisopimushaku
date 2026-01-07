"""HTTP fetching with guardrails and polite defaults."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

import requests
from requests import Response


@dataclass
class FetchResult:
    status: int
    final_url: str
    html: str
    headers: Dict[str, str]


def _should_retry(status: int) -> bool:
    return status == 429 or 500 <= status < 600


def fetch_url(
    session: requests.Session,
    url: str,
    *,
    timeout: float = 20.0,
    user_agent: str = "apprscan-jobs/0.1",
    max_retries: int = 3,
    rate_limit_state: Optional[Dict[str, float]] = None,
    req_per_second_per_domain: float = 1.0,
    debug_html_dir: Optional[Path] = None,
) -> Tuple[Optional[FetchResult], Optional[str]]:
    parsed = urlparse(url)
    domain = parsed.netloc
    if rate_limit_state is not None:
        last = rate_limit_state.get(domain, 0)
        min_interval = 1.0 / req_per_second_per_domain if req_per_second_per_domain > 0 else 0
        wait = max(0, min_interval - (time.time() - last))
        if wait > 0:
            time.sleep(wait)

    headers = {"User-Agent": user_agent}
    attempt = 0
    backoff = 1.0
    while attempt < max_retries:
        try:
            resp: Response = session.get(url, timeout=timeout, headers=headers, allow_redirects=True)
        except requests.RequestException as exc:  # pragma: no cover - network failures mocked elsewhere
            attempt += 1
            time.sleep(backoff)
            backoff *= 2
            continue

        if _should_retry(resp.status_code) and attempt < max_retries - 1:
            attempt += 1
            time.sleep(backoff)
            backoff *= 2
            continue

        if rate_limit_state is not None:
            rate_limit_state[domain] = time.time()

        if resp.status_code >= 400:
            return None, f"http_{resp.status_code}"

        html = resp.text
        if debug_html_dir:
            debug_html_dir.mkdir(parents=True, exist_ok=True)
            fname = debug_html_dir / f"{domain}_{int(time.time())}.html"
            fname.write_text(html, encoding="utf-8")

        return FetchResult(
            status=resp.status_code,
            final_url=str(resp.url),
            html=html,
            headers=dict(resp.headers),
        ), None

    return None, "max_retries_exceeded"
