"""Lever ATS fetcher."""

from __future__ import annotations

import requests
from typing import Dict, List, Optional, Tuple

from ..model import JobPosting
from ..tagging import detect_tags
from ..text import clean_html_snippet


def detect_lever(url: str, html: str) -> Optional[Dict[str, str]]:
    if "lever.co" in url or "lever.co" in html:
        # Try to extract slug from URL (jobs.lever.co/{slug})
        parts = url.split("/")
        for i, part in enumerate(parts):
            if part.endswith("lever.co") and i + 1 < len(parts):
                return {"kind": "lever", "slug": parts[i + 1]}
        # fallback: search for hire.lever.co script
        if "hire.lever.co" in html:
            return {"kind": "lever", "slug": "hire"}
        return {"kind": "lever", "slug": None}
    return None


def fetch_lever_jobs(slug: str, company: Dict[str, str], crawl_ts: str) -> Tuple[List[JobPosting], str | None]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code >= 400:
            return [], f"http_{resp.status_code}"
        data = resp.json()
    except Exception as exc:  # pragma: no cover - network failure
        return [], str(exc)

    jobs: List[JobPosting] = []
    for item in data:
        title = item.get("text") or ""
        job_url = item.get("hostedUrl") or item.get("applyUrl") or ""
        location = item.get("categories", {}).get("location")
        commitment = item.get("categories", {}).get("commitment")
        desc = item.get("descriptionPlain") or item.get("description") or ""
        posted = item.get("createdAt")
        tags = detect_tags(f"{title} {desc}")
        jobs.append(
            JobPosting(
                company_business_id=company.get("business_id", ""),
                company_name=company.get("name", ""),
                company_domain=company.get("domain", ""),
                job_title=title,
                job_url=job_url,
                location_text=location,
                employment_type=commitment,
                posted_date=str(posted) if posted else None,
                description_snippet=clean_html_snippet(desc),
                source="lever",
                tags=tags,
                crawl_ts=crawl_ts,
            )
        )
    return jobs, None
