"""Render an interactive jobs map using folium."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import folium
from folium.plugins import MarkerCluster
import pandas as pd
import math


def _marker_color(row: pd.Series) -> str:
    if row.get("job_count_new_since_last", 0) and row.get("job_count_new_since_last", 0) > 0:
        return "red"
    if row.get("recruiting_active"):
        return "green"
    return "blue"


def _marker_radius(count: float, *, max_count: float, scale: str = "log", size_mult: float = 1.0) -> float:
    min_r, max_r = 3.0, 10.0
    if max_count <= 0:
        base = min_r
    else:
        if scale == "linear":
            t = count / max_count
        else:
            t = math.log1p(count) / math.log1p(max_count)
        t = max(0.0, min(1.0, t))
        base = min_r + (max_r - min_r) * t
    base = base * max(0.5, min(size_mult, 3.0))
    return max(min_r, min(10.0, base))


def render_jobs_map(
    shortlist: pd.DataFrame,
    diff_jobs: Optional[pd.DataFrame],
    out_path: str | Path,
    *,
    mode: str = "jobs",
    nace_prefix: Optional[list[str]] = None,
    industries: Optional[list[str]] = None,
    sheet: str = "Shortlist",
    only_recruiting: bool = False,
    min_score: Optional[float] = None,
    max_distance_km: Optional[float] = None,
    skip_housing: bool = True,
    pin_scale: str = "log",
    pin_size: float = 1.0,
) -> None:
    if shortlist.empty:
        raise ValueError("Shortlist is empty; cannot render map.")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    nace_prefix = [p.strip() for p in (nace_prefix or []) if p.strip()]
    industries = [i.strip() for i in (industries or []) if i.strip()]
    if "industry_effective" in shortlist.columns and "industry" not in shortlist.columns:
        shortlist["industry"] = shortlist["industry_effective"]
    if industries and "industry" in shortlist.columns:
        shortlist = shortlist[shortlist["industry"].astype(str).str.lower().isin([i.lower() for i in industries])]
    if nace_prefix:
        def keep_row(r):
            val = r.get("main_business_line") or r.get("mainBusinessLine") or ""
            val = str(val)
            return any(val.startswith(pref) for pref in nace_prefix)
        shortlist = shortlist[shortlist.apply(keep_row, axis=1)]
    if sheet == "all" and "excluded_flag" in shortlist.columns:
        pass  # already combined if caller provided
    if only_recruiting and "recruiting_active" in shortlist.columns:
        shortlist = shortlist[shortlist["recruiting_active"] == True]  # noqa: E712
    if min_score is not None and "score" in shortlist.columns:
        shortlist = shortlist[pd.to_numeric(shortlist["score"], errors="coerce") >= float(min_score)]
    if max_distance_km is not None and "distance_km" in shortlist.columns:
        shortlist = shortlist[pd.to_numeric(shortlist["distance_km"], errors="coerce") <= float(max_distance_km)]

    valid_coords = shortlist.dropna(subset=["lat", "lon"]) if {"lat", "lon"}.issubset(shortlist.columns) else pd.DataFrame()
    center_lat = valid_coords["lat"].median() if not valid_coords.empty else 60.1699
    center_lon = valid_coords["lon"].median() if not valid_coords.empty else 24.9384
    m = folium.Map(location=[center_lat, center_lon], zoom_start=8)

    diff_jobs = diff_jobs if diff_jobs is not None else pd.DataFrame()
    jobs_by_bid = {}
    if not diff_jobs.empty and "company_business_id" in diff_jobs.columns:
        for bid, group in diff_jobs.groupby("company_business_id"):
            jobs_by_bid[str(bid)] = group

    all_layer = folium.FeatureGroup(name="All companies", show=True)
    active_layer = folium.FeatureGroup(name="Recruiting active", show=True)
    new_layer = folium.FeatureGroup(name="New jobs", show=True)
    cluster = MarkerCluster()

    points = []
    max_count = float(shortlist.get("job_count_total", pd.Series([0])).max() or 0)
    for _, row in shortlist.iterrows():
        lat, lon = row.get("lat"), row.get("lon")
        if pd.isna(lat) or pd.isna(lon):
            continue
        if skip_housing:
            try:
                from apprscan.filters import is_housing_company
            except Exception:
                is_housing_company = None
            if is_housing_company and is_housing_company(row.get("name")):
                continue
        bid = str(row.get("business_id") or "")
        company_name = row.get("name") or row.get("company_name") or ""
        if company_name is None or (isinstance(company_name, float) and pd.isna(company_name)) or not str(company_name).strip():
            company_name = row.get("company_domain") or bid
        popup_lines = []
        popup_lines.append(f"<b>{company_name} ({bid})</b>")
        if row.get("main_business_line"):
            popup_lines.append(f"Main business line: {row.get('main_business_line')}")
        popup_lines.append(
            f"Score: {row.get('score')}, Distance km: {row.get('distance_km')}, Station: {row.get('nearest_station')}"
        )
        note = str(row.get("note") or "")
        if note:
            short_note = (note[:117] + "...") if len(note) > 120 else note
            popup_lines.append(f"Note: {short_note}")
        popup_lines.append(
            f"Jobs total: {row.get('job_count_total', 0)}, New since last: {row.get('job_count_new_since_last', 0)}"
        )
        if bid in jobs_by_bid:
            subset = jobs_by_bid[bid].reset_index(drop=True)
            if len(subset) > 0:
                popup_lines.append(f"New jobs ({len(subset)}):")
                for idx, j in subset.head(5).iterrows():
                    title = j.get("job_title") or ""
                    url = j.get("job_url") or ""
                    tags = j.get("tags") if isinstance(j.get("tags"), list) else []
                    tag_text = f" [{', '.join(tags)}]" if tags else ""
                    popup_lines.append(f"- <a href='{url}' target='_blank'>{title}</a>{tag_text}")
                if len(subset) > 5:
                    popup_lines.append(f"... +{len(subset) - 5} more")
        else:
            popup_lines.append("New jobs: 0")

        popup_html = "<br>".join(str(x) for x in popup_lines)
        marker = folium.CircleMarker(
            location=[lat, lon],
            radius=_marker_radius(row.get("job_count_total", 0) or 0, max_count=max_count, scale=pin_scale, size_mult=pin_size),
            color=_marker_color(row),
            fill=True,
            fill_opacity=0.7,
            popup=folium.Popup(popup_html, max_width=350),
            tooltip=f"{company_name} (status: {row.get('status')}, new: {row.get('job_count_new_since_last', 0)})",
        )
        cluster.add_child(marker)
        if row.get("job_count_new_since_last", 0) and row.get("job_count_new_since_last", 0) > 0:
            new_layer.add_child(marker)
        if row.get("recruiting_active"):
            active_layer.add_child(marker)
        if row.get("status") == "shortlist":
            # Show shortlist layer via active/new_layer membership; keep all in all_layer
            pass
        all_layer.add_child(marker)
        points.append((lat, lon))

    all_layer.add_child(cluster)
    m.add_child(all_layer)
    m.add_child(active_layer)
    m.add_child(new_layer)
    m.add_child(folium.LayerControl(collapsed=False))

    legend_html = """
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
    background: white; padding: 10px; border: 2px solid #777; border-radius: 6px;">
    <b>Legend</b><br>
    <span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:red;"></span> New jobs<br>
    <span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:green;"></span> Recruiting active<br>
    <span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:blue;"></span> Other<br>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    if points:
        m.fit_bounds(points)

    m.save(out_path)
