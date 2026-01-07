"""Watch-mode report generation for new jobs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional, Set

import pandas as pd


def _shortlist_lookup(shortlist: Optional[pd.DataFrame]) -> Dict[str, Dict[str, object]]:
    if shortlist is None or shortlist.empty:
        return {}
    lookup: Dict[str, Dict[str, object]] = {}
    for _, row in shortlist.iterrows():
        bid = str(row.get("business_id") or row.get("businessId") or "").strip()
        if not bid:
            continue
        lookup[bid] = {
            "score": row.get("score"),
            "distance_km": row.get("distance_km"),
            "nearest_station": row.get("nearest_station"),
            "name": row.get("name") or row.get("company_name"),
        }
    return lookup


def _parse_list(val: str) -> Set[str]:
    return {v.strip().lower() for v in val.split(",") if v.strip()} if val else set()


def generate_watch_report(
    shortlist: Optional[pd.DataFrame],
    jobs_diff: pd.DataFrame,
    out_path: Path,
    *,
    include_tags: Iterable[str] | None = None,
    exclude_keywords: Iterable[str] | None = None,
    max_items: int = 0,
    min_score: float | None = None,
    max_distance_km: float | None = None,
    stations: Iterable[str] | None = None,
) -> None:
    include_tags = {t.lower() for t in include_tags or []}
    exclude_keywords = {t.lower() for t in exclude_keywords or []}
    stations = {s.lower() for s in stations or []}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    lines.append(f"Watch report generated: {now}")

    new_jobs = jobs_diff.copy()
    lines.append(f"New jobs (before filters): {len(new_jobs)}")
    lines.append("")

    lookup = _shortlist_lookup(shortlist)

    def passes_filters(row) -> bool:
        tags = row.get("tags") if isinstance(row.get("tags"), list) else []
        title = str(row.get("job_title") or "").lower()
        snippet = str(row.get("description_snippet") or row.get("description") or "").lower()
        text = f"{title} {snippet}"
        # include tags
        if include_tags:
            if not tags or not any(t.lower() in include_tags for t in tags):
                return False
        # exclude keywords
        if exclude_keywords and any(kw in text for kw in exclude_keywords):
            return False
        bid = str(row.get("company_business_id") or row.get("business_id") or "").strip()
        info = lookup.get(bid, {})
        score = info.get("score")
        if min_score is not None and score is not None:
            try:
                if float(score) < float(min_score):
                    return False
            except (TypeError, ValueError):
                pass
        dist = info.get("distance_km")
        if max_distance_km is not None and dist is not None:
            try:
                if float(dist) > float(max_distance_km):
                    return False
            except (TypeError, ValueError):
                pass
        if stations and info.get("nearest_station"):
            if str(info["nearest_station"]).lower() not in stations:
                return False
        return True

    filtered_jobs = [row for _, row in new_jobs.iterrows() if passes_filters(row)]
    lines.append(f"New jobs (after filters): {len(filtered_jobs)}")
    lines.append("")

    if new_jobs.empty:
        lines.append("No new jobs found.")
        out_path.write_text("\n".join(lines), encoding="utf-8")
        return

    # Sort: tag hit (include_tags) first, score desc, distance asc
    def sort_key(row):
        tags = row.get("tags") if isinstance(row.get("tags"), list) else []
        tag_hit = any(t.lower() in include_tags for t in tags) if include_tags else False
        bid = str(row.get("company_business_id") or row.get("business_id") or "").strip()
        info = lookup.get(bid, {})
        score = info.get("score")
        dist = info.get("distance_km")
        score_val = float(score) if score is not None else -1e9
        dist_val = float(dist) if dist is not None else 1e9
        return (int(not tag_hit), -score_val, dist_val)

    filtered_jobs_sorted = sorted(filtered_jobs, key=sort_key)
    if max_items and len(filtered_jobs_sorted) > max_items:
        filtered_jobs_sorted = filtered_jobs_sorted[:max_items]

    # List new jobs
    lines.append("New job postings:")
    for row in filtered_jobs_sorted:
        bid = str(row.get("company_business_id") or row.get("business_id") or "").strip()
        title = row.get("job_title") or ""
        url = row.get("job_url") or ""
        tags = row.get("tags") if isinstance(row.get("tags"), list) else []
        loc = row.get("location_text") or ""
        company_name = row.get("company_name") or lookup.get(bid, {}).get("name") or ""
        lines.append(f"- {company_name} ({bid}): {title}")
        if tags:
            lines.append(f"  tags: {', '.join(tags)}")
        if loc:
            lines.append(f"  location: {loc}")
        info = lookup.get(bid, {})
        extras = []
        if info.get("score") is not None:
            extras.append(f"score={info['score']}")
        if info.get("distance_km") is not None:
            extras.append(f"distance_km={info['distance_km']}")
        if info.get("nearest_station"):
            extras.append(f"station={info['nearest_station']}")
        if extras:
            lines.append("  " + ", ".join(extras))
        lines.append(f"  link: {url}")
        lines.append("")

    # Top companies by new job count
    lines.append("Top companies by new jobs:")
    bid_series = new_jobs["company_business_id"]
    if "business_id" in new_jobs.columns:
        bid_series = bid_series.fillna(new_jobs["business_id"])
    counts = (
        pd.DataFrame(filtered_jobs_sorted)
        .assign(bid=bid_series.iloc[: len(filtered_jobs_sorted)] if len(bid_series) else None)
        .groupby("bid")
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    for _, r in counts.iterrows():
        bid = str(r["bid"])
        name = lookup.get(bid, {}).get("name") or ""
        lines.append(f"- {name} ({bid}): {int(r['count'])}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
