"""Generic HTML fallback extractor."""

from __future__ import annotations

from typing import Dict, List, Optional, Set
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..fetch import FetchResult, fetch_url
from ..model import JobPosting
from ..tagging import detect_tags
from ..text import clean_html_snippet

JOB_URL_HINTS = ["/jobs", "/careers", "/positions", "/rekry", "/tyopaikat", "?job", "open-position"]
JOB_TEXT_HINTS = ["apply", "hae", "avoin", "position", "job", "role", "tehtävä"]


def discover_job_links(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: List[str] = []
    seen: Set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text(" ", strip=True) or "").lower()
        target = urljoin(base_url, href)
        if target in seen:
            continue
        if any(hint in href.lower() for hint in JOB_URL_HINTS) or any(ht in text for ht in JOB_TEXT_HINTS):
            seen.add(target)
            urls.append(target)
    return urls


def extract_jobs_generic(
    session,
    html: str,
    base_url: str,
    company: Dict[str, str],
    crawl_ts: str,
    *,
    max_detail_pages: int = 20,
    rate_limit_state=None,
    debug_html_dir=None,
    req_per_second_per_domain: float = 1.0,
) -> List[JobPosting]:
    jobs: List[JobPosting] = []
    candidates = discover_job_links(html, base_url)[:max_detail_pages]
    for url in candidates:
        res, reason = fetch_url(
            session,
            url,
            rate_limit_state=rate_limit_state,
            req_per_second_per_domain=req_per_second_per_domain,
            debug_html_dir=debug_html_dir,
        )
        if res is None:
            continue
        detail_soup = BeautifulSoup(res.html, "html.parser")
        title_tag = detail_soup.find("h1")
        title = title_tag.get_text(" ", strip=True) if title_tag else res.final_url
        body_text = detail_soup.get_text(" ", strip=True)
        snippet = body_text[:300] if body_text else None
        tags = detect_tags(f"{title} {snippet or ''}")
        jobs.append(
            JobPosting(
                company_business_id=company.get("business_id", ""),
                company_name=company.get("name", ""),
                company_domain=company.get("domain", ""),
                job_title=title,
                job_url=res.final_url,
                location_text=None,
                employment_type=None,
                posted_date=None,
                description_snippet=snippet,
                source="generic_html",
                tags=tags,
                crawl_ts=crawl_ts,
            )
        )
    return jobs
