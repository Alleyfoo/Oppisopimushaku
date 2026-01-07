"""Teamtailor ATS fetcher (best-effort placeholder)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..model import JobPosting


def detect_teamtailor(url: str, html: str) -> Optional[Dict[str, str]]:
    if "teamtailor" in url or "teamtailor" in html:
        # Look for company slug in URL like https://{slug}.teamtailor.com
        slug = None
        parts = url.split("/")
        for part in parts:
            if part.endswith(".teamtailor.com"):
                slug = part.split(".")[0]
                break
        return {"kind": "teamtailor", "slug": slug}
    return None


def fetch_teamtailor_jobs(slug: str, company: Dict[str, str], crawl_ts: str) -> Tuple[List[JobPosting], str | None]:
    # Teamtailor often requires keys; we leave placeholder.
    return [], "teamtailor_not_implemented"
