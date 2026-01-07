"""Jobs pipeline orchestrating discovery, fetching, and extraction."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd
import requests

from .ats import detect_ats, fetch_ats_jobs
from .discovery import DiscoveryResult, discover_paths, parse_sitemap, filter_discovery_results
from .extract import extract_jobs_from_jsonld, extract_jobs_generic
from .fetch import fetch_url
from .constants import ROBOTS_DISALLOW_ALL, ROBOTS_DISALLOW_URL
from .model import JobPosting
from .robots import RobotsChecker
from .storage import jobs_to_dataframe
from .tagging import detect_tags, DEFAULT_TAG_RULES


@dataclass
class CrawlStats:
    domain: str
    pages_fetched: int = 0
    jobs_found: int = 0
    extractor_used: str | None = None
    errors: List[str] = field(default_factory=list)
    skipped_reason: str | None = None
    ats_detected: str | None = None
    ats_fetch_ok: bool = False
    ats_fetch_reason: str | None = None
    robots_rule_hit: str | None = None
    first_blocked_url: str | None = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "domain": self.domain,
            "pages_fetched": self.pages_fetched,
            "jobs_found": self.jobs_found,
            "extractor_used": self.extractor_used,
            "errors": ";".join(self.errors) if self.errors else None,
            "skipped_reason": self.skipped_reason,
            "ats_detected": self.ats_detected,
            "ats_fetch_ok": self.ats_fetch_ok,
            "ats_fetch_reason": self.ats_fetch_reason,
            "robots_rule_hit": self.robots_rule_hit,
            "first_blocked_url": self.first_blocked_url,
        }


def load_companies(path: Path, only_shortlist: bool = True) -> pd.DataFrame:
    if path.suffix.lower() in [".xlsx", ".xls"]:
        sheet = "Shortlist" if only_shortlist else None
        df = pd.read_excel(path, sheet_name=sheet)
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    elif path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    else:
        raise ValueError("Unsupported companies file format.")

    if "business_id" not in df.columns and "businessId" in df.columns:
        df = df.rename(columns={"businessId": "business_id"})
    if "name" not in df.columns and "company_name" in df.columns:
        df = df.rename(columns={"company_name": "name"})
    return df


def build_domain(company_row: pd.Series, domain_map: Dict[str, str]) -> str:
    bid = str(company_row.get("business_id") or "").strip()
    domain = str(company_row.get("domain") or domain_map.get(bid, "")).strip()
    return domain


def crawl_domain(
    company: Dict[str, str],
    domain: str,
    *,
    max_pages: int,
    req_per_second: float,
    rate_limit_state: Dict[str, float],
    debug_html_dir: Optional[Path],
    session: requests.Session,
    crawl_ts: str,
    tag_rules: Dict[str, List[str]] | None = None,
) -> Tuple[List[JobPosting], CrawlStats]:
    stats = CrawlStats(domain=domain)
    robots_checker = RobotsChecker()

    # Fetch base page for ATS detection
    base_url = f"https://{domain}"
    allowed, rule = robots_checker.can_fetch_detail(base_url)
    if not allowed:
        stats.skipped_reason = ROBOTS_DISALLOW_ALL if rule == "Disallow: /" else ROBOTS_DISALLOW_URL
        stats.robots_rule_hit = rule
        stats.first_blocked_url = base_url
        return [], stats
    res, reason = fetch_url(
        session,
        base_url,
        rate_limit_state=rate_limit_state,
        req_per_second_per_domain=req_per_second,
        debug_html_dir=debug_html_dir,
    )
    if res is None:
        stats.skipped_reason = reason or "base_fetch_failed"
        return [], stats

    stats.pages_fetched += 1
    detected = detect_ats(base_url, res.html)
    if detected:
        stats.ats_detected = detected.get("kind")
        jobs, ats_reason = fetch_ats_jobs(detected, company, crawl_ts)
        if jobs:
            stats.ats_fetch_ok = True
            stats.jobs_found = len(jobs)
            stats.extractor_used = detected.get("kind")
            return jobs, stats
        else:
            stats.ats_fetch_reason = ats_reason

    # discovery
    seeds = discover_paths(domain)
    # try sitemap
    sitemap_url = f"https://{domain}/sitemap.xml"
    sm_allowed, sm_rule = robots_checker.can_fetch_detail(sitemap_url)
    sm_res = None
    if sm_allowed:
        sm_res, _ = fetch_url(
            session,
            sitemap_url,
            rate_limit_state=rate_limit_state,
            req_per_second_per_domain=req_per_second,
            debug_html_dir=debug_html_dir,
        )
    else:
        stats.errors.append("robots_disallow_sitemap")
    if sm_res and sm_res.status == 200:
        stats.pages_fetched += 1
        seeds.extend(parse_sitemap(sm_res.html, base_url, max_urls=200))

    seeds = list(dict.fromkeys(seeds))

    all_jobs: List[JobPosting] = []
    for seed in seeds:
        if stats.pages_fetched >= max_pages:
            break
        allowed, rule = robots_checker.can_fetch_detail(seed)
        if not allowed:
            stats.errors.append(ROBOTS_DISALLOW_URL)
            if not stats.first_blocked_url:
                stats.first_blocked_url = seed
                stats.robots_rule_hit = rule
                stats.skipped_reason = stats.skipped_reason or ROBOTS_DISALLOW_URL
            continue
        res, reason = fetch_url(
            session,
            seed,
            rate_limit_state=rate_limit_state,
            req_per_second_per_domain=req_per_second,
            debug_html_dir=debug_html_dir,
        )
        if res is None:
            stats.errors.append(reason or f"fetch_failed:{seed}")
            if reason in (ROBOTS_DISALLOW_ALL, ROBOTS_DISALLOW_URL) and not stats.first_blocked_url:
                stats.first_blocked_url = seed
                stats.robots_rule_hit = reason
                stats.skipped_reason = stats.skipped_reason or reason
            continue
        stats.pages_fetched += 1
        html = res.html
        jsonld_jobs = extract_jobs_from_jsonld(html, res.final_url, company, crawl_ts)
        if jsonld_jobs:
            all_jobs.extend(jsonld_jobs)
            stats.extractor_used = (stats.extractor_used or "") + ";jsonld"
            continue
        # discover more links on this page
        seeds.extend(filter_discovery_results(html, res.final_url))
        generic_jobs = extract_jobs_generic(
            session,
            html,
            res.final_url,
            company,
            crawl_ts,
            rate_limit_state=rate_limit_state,
            debug_html_dir=debug_html_dir,
            req_per_second_per_domain=req_per_second,
        )
        if generic_jobs:
            all_jobs.extend(generic_jobs)
            stats.extractor_used = (stats.extractor_used or "") + ";generic"

    stats.jobs_found = len(all_jobs)
    return all_jobs, stats


def crawl_jobs_pipeline(
    companies_df: pd.DataFrame,
    domain_map: Dict[str, str],
    *,
    max_domains: int = 300,
    max_pages_per_domain: int = 30,
    req_per_second: float = 1.0,
    debug_html: bool = False,
    out_raw_dir: Optional[Path] = None,
    tag_rules: Dict[str, List[str]] | None = None,
    max_workers: int = 5,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    crawl_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    jobs: List[JobPosting] = []
    stats_rows: List[Dict[str, object]] = []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    tasks = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        processed = 0
        for _, row in companies_df.iterrows():
            if processed >= max_domains:
                break
            domain = build_domain(row, domain_map)
            if not domain:
                continue
            company = {
                "business_id": str(row.get("business_id") or ""),
                "name": row.get("name", ""),
                "domain": domain,
            }
            domain_raw_dir = out_raw_dir if debug_html else None
            tasks.append(
                executor.submit(
                    crawl_domain,
                    company,
                    domain,
                    max_pages=max_pages_per_domain,
                    req_per_second=req_per_second,
                    rate_limit_state={},
                    debug_html_dir=domain_raw_dir,
                    session=requests.Session(),
                    crawl_ts=crawl_ts,
                    tag_rules=tag_rules,
                )
            )
            processed += 1

        for fut in as_completed(tasks):
            domain_jobs, stat = fut.result()
            jobs.extend(domain_jobs)
            stats_rows.append(stat.to_dict())

    jobs_df = jobs_to_dataframe(jobs)
    stats_df = pd.DataFrame(stats_rows)
    activity_df = summarize_activity(jobs_df)
    return jobs_df, stats_df, activity_df


def apply_diff(jobs_df: pd.DataFrame, known_path: Path) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Mark is_new and produce diff of new jobs."""
    def fingerprint(row):
        def norm(val: str) -> str:
            import re
            s = str(val or "").lower().strip()
            s = re.sub(r"\s+", " ", s)
            s = s.replace(", finland", "").replace(", suomi", "")
            return s

        title = norm(row.get("job_title"))
        loc = norm(row.get("location_text"))
        posted = norm(row.get("posted_date"))
        domain = norm(row.get("company_domain"))
        return hash((title, loc, posted, domain))

    jobs_df = jobs_df.copy()
    jobs_df["job_fingerprint"] = jobs_df.apply(fingerprint, axis=1)

    known_urls: set[str] = set()
    known_fps: set[int] = set()
    if known_path.exists():
        try:
            known_df = pd.read_parquet(known_path)
        except ImportError:
            known_df = pd.read_csv(known_path)
        if "job_url" in known_df.columns:
            known_urls = set(known_df["job_url"].astype(str))
        if "job_fingerprint" in known_df.columns:
            known_fps = set(known_df["job_fingerprint"].astype(int))
    else:
        csv_alt = known_path.with_suffix(".csv")
        if csv_alt.exists():
            known_df = pd.read_csv(csv_alt)
            if "job_url" in known_df.columns:
                known_urls = set(known_df["job_url"].astype(str))
            if "job_fingerprint" in known_df.columns:
                known_fps = set(known_df["job_fingerprint"].astype(int))

    jobs_df["is_new"] = ~jobs_df["job_url"].astype(str).isin(known_urls) & ~jobs_df[
        "job_fingerprint"
    ].astype(int).isin(known_fps)
    new_jobs = jobs_df[jobs_df["is_new"]]

    known_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        jobs_df[["job_url", "job_fingerprint"]].to_parquet(known_path, index=False)
    except ImportError:
        csv_alt = known_path.with_suffix(".csv")
        jobs_df[["job_url", "job_fingerprint"]].to_csv(csv_alt, index=False)
    return jobs_df, new_jobs


def summarize_activity(jobs_df: pd.DataFrame) -> pd.DataFrame:
    if jobs_df.empty:
        return pd.DataFrame(
            columns=[
                "business_id",
                "job_count_total",
                "job_count_last_30d",
                "job_count_new_since_last",
                "recruiting_active",
                "tag_count_data",
                "tag_count_it_support",
                "tag_count_salesforce",
                "tag_count_oppisopimus",
            ]
        )
    jobs_df = jobs_df.copy()
    jobs_df["posted_date_parsed"] = pd.to_datetime(jobs_df["posted_date"], errors="coerce", utc=True).dt.tz_localize(
        None
    )
    now = pd.Timestamp.utcnow().tz_localize(None)
    last_30 = now - pd.Timedelta(days=30)

    summaries = []
    for bid, group in jobs_df.groupby("company_business_id"):
        total = len(group)
        recent = group[group["posted_date_parsed"] >= last_30]
        if "is_new" in group.columns:
            new_mask = group["is_new"] == True  # noqa: E712
        else:
            new_mask = pd.Series(False, index=group.index)
        new_since_last = group[new_mask]
        # Tag counts
        def count_tag(tag):
            return sum(1 for tags in group["tags"] if isinstance(tags, list) and tag in tags)

        summaries.append(
            {
                "business_id": bid,
                "job_count_total": total,
                "job_count_last_30d": len(recent),
                "job_count_new_since_last": len(new_since_last),
                "recruiting_active": total > 0,
                "tag_count_data": count_tag("data"),
                "tag_count_it_support": count_tag("it_support"),
                "tag_count_salesforce": count_tag("salesforce"),
                "tag_count_oppisopimus": count_tag("oppisopimus"),
            }
        )
    return pd.DataFrame(summaries)
