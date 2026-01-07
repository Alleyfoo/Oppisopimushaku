"""Recruitee ATS fetcher (best-effort)."""

from __future__ import annotations

import requests
from typing import Dict, List, Optional, Tuple

from ..model import JobPosting
from ..tagging import detect_tags
from ..text import clean_html_snippet


def detect_recruitee(url: str, html: str) -> Optional[Dict[str, str]]:
    if "recruitee.com" in url or "recruitee.com" in html:
        parts = url.split("/")
        slug = None
        for part in parts:
            if part.endswith(".recruitee.com"):
                slug = part.split(".")[0]
                break
        return {"kind": "recruitee", "slug": slug}
    return None


def fetch_recruitee_jobs(slug: str, company: Dict[str, str], crawl_ts: str) -> Tuple[List[JobPosting], str | None]:
    url = f"https://{slug}.recruitee.com/api/offers/"
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code >= 400:
            return [], f"http_{resp.status_code}"
        data = resp.json()
    except Exception as exc:  # pragma: no cover
        return [], str(exc)

    jobs: List[JobPosting] = []
    for item in data.get("offers", []):
        title = item.get("title") or ""
        job_url = item.get("careers_url") or item.get("url") or ""
        loc = item.get("location")
        posted = item.get("created_at")
        desc = item.get("description") or ""
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
                source="recruitee",
                tags=tags,
                crawl_ts=crawl_ts,
            )
        )
    return jobs, None
