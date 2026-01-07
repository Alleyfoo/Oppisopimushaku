"""Greenhouse ATS fetcher."""

from __future__ import annotations

import requests
from typing import Dict, List, Optional, Tuple

from ..model import JobPosting
from ..tagging import detect_tags
from ..text import clean_html_snippet


def detect_greenhouse(url: str, html: str) -> Optional[Dict[str, str]]:
    if "greenhouse.io" in url or "boards.greenhouse.io" in html:
        parts = url.split("/")
        token = None
        for i, part in enumerate(parts):
            if "greenhouse" in part and i + 1 < len(parts):
                token = parts[i + 1]
                break
        return {"kind": "greenhouse", "slug": token}
    return None


def fetch_greenhouse_jobs(slug: str, company: Dict[str, str], crawl_ts: str) -> Tuple[List[JobPosting], str | None]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code >= 400:
            return [], f"http_{resp.status_code}"
        data = resp.json()
    except Exception as exc:  # pragma: no cover
        return [], str(exc)

    jobs: List[JobPosting] = []
    for item in data.get("jobs", []):
        title = item.get("title") or ""
        job_url = item.get("absolute_url") or ""
        loc = (item.get("location") or {}).get("name")
        posted = item.get("updated_at")
        desc = item.get("content") or ""
        tags = detect_tags(f"{title} {desc}")
        jobs.append(
            JobPosting(
                company_business_id=company.get("business_id", ""),
                company_name=company.get("name", ""),
                company_domain=company.get("domain", ""),
                job_title=title,
                job_url=job_url,
                location_text=loc,
                employment_type=None,
                posted_date=posted,
                description_snippet=clean_html_snippet(desc),
                source="greenhouse",
                tags=tags,
                crawl_ts=crawl_ts,
            )
        )
    return jobs, None
