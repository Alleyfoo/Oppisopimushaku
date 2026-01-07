"""JSON-LD JobPosting extractor."""

from __future__ import annotations

import json
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..model import JobPosting
from ..tagging import detect_tags
from ..text import clean_html_snippet


def _iter_items(data):
    if isinstance(data, dict):
        yield data
        if "@graph" in data and isinstance(data["@graph"], list):
            for item in data["@graph"]:
                if isinstance(item, dict):
                    yield item
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item


def extract_jobs_from_jsonld(html: str, base_url: str, company: Dict[str, str], crawl_ts: str) -> List[JobPosting]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: List[JobPosting] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in _iter_items(data):
            types = item.get("@type")
            if isinstance(types, list):
                type_match = "JobPosting" in types
            else:
                type_match = types == "JobPosting"
            if not type_match:
                continue
            title = item.get("title") or ""
            url = item.get("url") or item.get("mainEntityOfPage") or base_url
            job_loc = None
            if isinstance(item.get("jobLocation"), dict):
                addr = item["jobLocation"].get("address", {})
                if isinstance(addr, dict):
                    job_loc = addr.get("addressLocality") or addr.get("streetAddress") or None
            emp_type = item.get("employmentType")
            posted = item.get("datePosted")
            desc_raw = item.get("description") or ""
            snippet = clean_html_snippet(desc_raw, 300)
            tags = detect_tags(f"{title} {desc_raw}")
            jobs.append(
                JobPosting(
                    company_business_id=company.get("business_id", ""),
                    company_name=company.get("name", ""),
                    company_domain=company.get("domain", ""),
                    job_title=title,
                    job_url=urljoin(base_url, url),
                    location_text=job_loc,
                    employment_type=emp_type if isinstance(emp_type, str) else None,
                    posted_date=posted,
                    description_snippet=snippet,
                    source="jsonld",
                    tags=tags,
                    crawl_ts=crawl_ts,
                )
            )
    return jobs
