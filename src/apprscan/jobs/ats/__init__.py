"""ATS detection and fetchers."""

from __future__ import annotations

from typing import Dict, Optional

from .lever import detect_lever, fetch_lever_jobs
from .greenhouse import detect_greenhouse, fetch_greenhouse_jobs
from .recruitee import detect_recruitee, fetch_recruitee_jobs
from .teamtailor import detect_teamtailor, fetch_teamtailor_jobs


def detect_ats(url: str, html: str) -> Optional[Dict[str, str]]:
    for detector in (detect_lever, detect_greenhouse, detect_recruitee, detect_teamtailor):
        detected = detector(url, html)
        if detected:
            return detected
    return None


def fetch_ats_jobs(detected: Dict[str, str], company: Dict[str, str], crawl_ts: str):
    kind = detected.get("kind")
    slug = detected.get("slug") or detected.get("board")
    if kind == "lever" and slug:
        return fetch_lever_jobs(slug, company, crawl_ts)
    if kind == "greenhouse" and slug:
        return fetch_greenhouse_jobs(slug, company, crawl_ts)
    if kind == "recruitee" and slug:
        return fetch_recruitee_jobs(slug, company, crawl_ts)
    if kind == "teamtailor" and slug:
        return fetch_teamtailor_jobs(slug, company, crawl_ts)
    return [], "ats_missing_slug"
