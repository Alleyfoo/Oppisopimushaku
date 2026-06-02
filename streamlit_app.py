"""Streamlit viewer/editor for master shortlist with curation overlay."""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import pydeck as pdk

# Make the src-layout `apprscan` package importable on Streamlit Cloud, where
# only requirements.txt is installed (the package itself is not pip-installed).
_SRC = Path(__file__).parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from apprscan.artifacts import find_latest_diff, find_latest_master, artifact_date
from apprscan.analytics import io as a_io
from apprscan.analytics import summarize
from apprscan.curation import (
    apply_curation,
    append_audit,
    compute_edit_diff,
    load_audit,
    normalize_tags,
    read_curation,
    read_master,
    restore_curation_from_backup,
    update_curation_from_edits,
    validate_master,
    write_curation_with_backup,
)
from apprscan.filters_view import FilterOptions, filter_data
from apprscan.inspector import explain_company, select_company_jobs, get_prev_next
from apprscan.jobs_view import join_new_jobs_with_companies


def _resolve_path(path_str: str | None, finder) -> Path | None:
    if path_str:
        return Path(path_str)
    return finder() or None


def _file_mtime(path: Path | None) -> float:
    if path and path.exists():
        return path.stat().st_mtime
    return 0.0


@st.cache_data(show_spinner=False)
def _cached_read_master(path_str: str, mtime: float) -> pd.DataFrame:
    return read_master(Path(path_str))


@st.cache_data(show_spinner=False)
def _cached_read_curation(path_str: str, mtime: float) -> pd.DataFrame:
    return read_curation(Path(path_str))


@st.cache_data(show_spinner=False)
def _cached_read_diff(path_str: str, mtime: float) -> pd.DataFrame:
    p = Path(path_str)
    if p.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(p)
    if p.suffix.lower() == ".jsonl":
        return pd.read_json(p, lines=True)
    return pd.DataFrame()


@st.cache_data(show_spinner=False)
def _cached_read_master_sheet(path_str: str, mtime: float, sheet: str) -> pd.DataFrame:
    return pd.read_excel(path_str, sheet_name=sheet)


def load_data(master_path: Path, curation_path: Path | None):
    master_df = _cached_read_master(str(master_path), _file_mtime(master_path))
    cur_path = curation_path or Path("out/curation/master_curation.csv")
    curation_df = _cached_read_curation(str(cur_path), _file_mtime(cur_path))
    return master_df, curation_df


def describe_filters(opts: FilterOptions) -> list[str]:
    items = []
    if opts.focus_business_id:
        items.append(f"Focus: {opts.focus_business_id}")
    if opts.industries:
        items.append(f"Industry: {', '.join(opts.industries)}")
    if opts.statuses:
        items.append(f"Status: {', '.join(opts.statuses)}")
    if opts.only_recruiting:
        items.append("Only recruiting")
    if opts.min_score is not None:
        items.append(f"Min score: {opts.min_score}")
    if opts.max_distance_km is not None:
        items.append(f"Max distance: {opts.max_distance_km} km")
    if opts.stations:
        items.append(f"Stations: {', '.join(opts.stations)}")
    if opts.include_tags:
        items.append(f"Include tags: {', '.join(opts.include_tags)}")
    if opts.exclude_tags:
        items.append(f"Exclude tags: {', '.join(opts.exclude_tags)}")
    if opts.search:
        items.append(f"Search: {opts.search}")
    if not items:
        items.append("None")
    return items


def artifact_dates_info(master_path: Path | None, diff_path: Path | None) -> tuple[dict, bool]:
    dates = {
        "master": artifact_date(master_path),
        "diff": artifact_date(diff_path),
    }
    mismatch = bool(dates["master"] and dates["diff"] and dates["master"] != dates["diff"])
    return dates, mismatch


def load_diff_df(diff_path: Path | None) -> pd.DataFrame:
    if diff_path is None or not diff_path.exists():
        return pd.DataFrame()
    return _cached_read_diff(str(diff_path), _file_mtime(diff_path))


def load_jobs_all(master_path: Path | None) -> pd.DataFrame:
    if master_path is None or not master_path.exists():
        return pd.DataFrame()
    try:
        return _cached_read_master_sheet(str(master_path), _file_mtime(master_path), "Jobs_All")
    except Exception:
        return pd.DataFrame()


def load_stats_df(master_path: Path | None) -> pd.DataFrame:
    if master_path is None or not master_path.exists():
        return pd.DataFrame()
    try:
        return _cached_read_master_sheet(str(master_path), _file_mtime(master_path), "Crawl_Stats")
    except Exception:
        return pd.DataFrame()


def merge_edits(*edits_lists: list[dict]) -> list[dict]:
    """Merge multiple edit lists by business_id; later lists win."""
    merged: dict[str, dict] = {}
    for edits in edits_lists:
        for row in edits:
            bid = str(row.get("business_id", "")).strip()
            if not bid:
                continue
            if bid not in merged:
                merged[bid] = {"business_id": bid}
            merged[bid].update({k: v for k, v in row.items() if k != "business_id"})
    return list(merged.values())


def apply_preset_to_state(preset: str):
    defaults = {
        "Default": {
            "industries": [],
            "statuses": [],
            "include_hidden": False,
            "include_excluded": False,
            "include_housing": False,
            "only_recruiting": False,
            "min_score": 0,
            "max_distance": 5.0,
            "search": "",
            "include_tags": "",
            "exclude_tags": "",
        },
        "Shortlist": {
            "industries": [],
            "statuses": ["shortlist"],
            "include_hidden": False,
            "include_excluded": False,
            "include_housing": False,
            "only_recruiting": False,
            "min_score": 0,
            "max_distance": 5.0,
            "search": "",
            "include_tags": "",
            "exclude_tags": "",
        },
        "Recruiting": {
            "industries": [],
            "statuses": [],
            "include_hidden": False,
            "include_excluded": False,
            "include_housing": False,
            "only_recruiting": True,
            "min_score": 0,
            "max_distance": 3.0,
            "search": "",
            "include_tags": "",
            "exclude_tags": "",
        },
        "Cleanup Other": {
            "industries": ["other"],
            "statuses": [],
            "include_hidden": True,
            "include_excluded": True,
            "include_housing": False,
            "only_recruiting": False,
            "min_score": 0,
            "max_distance": 10.0,
            "search": "",
            "include_tags": "",
            "exclude_tags": "",
        },
        "Hidden review": {
            "industries": [],
            "statuses": [],
            "include_hidden": True,
            "include_excluded": True,
            "include_housing": True,
            "only_recruiting": False,
            "min_score": 0,
            "max_distance": 10.0,
            "search": "",
            "include_tags": "",
            "exclude_tags": "",
        },
        "Excluded review": {
            "industries": [],
            "statuses": ["excluded"],
            "include_hidden": True,
            "include_excluded": True,
            "include_housing": True,
            "only_recruiting": False,
            "min_score": 0,
            "max_distance": 10.0,
            "search": "",
            "include_tags": "",
            "exclude_tags": "",
        },
    }
    d = defaults.get(preset, defaults["Default"])
    st.session_state["filt_industries"] = d["industries"]
    st.session_state["filt_statuses"] = d["statuses"]
    st.session_state["filt_include_hidden"] = d["include_hidden"]
    st.session_state["filt_include_excluded"] = d["include_excluded"]
    st.session_state["filt_include_housing"] = d["include_housing"]
    st.session_state["filt_only_recruiting"] = d["only_recruiting"]
    st.session_state["filt_min_score"] = d["min_score"]
    st.session_state["filt_max_distance"] = d["max_distance"]
    st.session_state["filt_search"] = d["search"]
    st.session_state["filt_include_tags"] = d["include_tags"]
    st.session_state["filt_exclude_tags"] = d["exclude_tags"]


def prepare_map(filtered_df: pd.DataFrame, radius: float):
    df_map = filtered_df.dropna(subset=["lat", "lon"])
    if df_map.empty:
        st.info("No coordinates to render map.")
        return
    def color(row):
        if row.get("status") == "shortlist":
            return [0, 150, 255, 180]
        if row.get("status") == "excluded" or row.get("hide_flag"):
            return [160, 160, 160, 120]
        if row.get("recruiting_active"):
            return [0, 200, 0, 180]
        return [255, 140, 0, 160]

    df_map = df_map.copy()
    df_map["color"] = df_map.apply(color, axis=1)
    initial_view = {
        "latitude": df_map["lat"].astype(float).mean(),
        "longitude": df_map["lon"].astype(float).mean(),
        "zoom": 8,
    }
    layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_map,
        get_position=["lon", "lat"],
        get_radius=radius,
        get_fill_color="color",
        pickable=True,
    )
    tooltip = {
        "html": "<b>{name}</b><br>ID: {business_id}<br>Status: {status}<br>Score: {score}<br>Dist km: {distance_km}",
        "style": {"color": "white"},
    }
    deck = pdk.Deck(layers=[layer], initial_view_state=initial_view, tooltip=tooltip)
    st.pydeck_chart(deck)


def render_train_reach():
    """Phase 1: train commute reach from Mäntsälä as an isochrone with a slider."""
    from apprscan import transit

    st.subheader("Train reach from Mäntsälä")
    st.caption(
        "Offline estimate: train time to each station (calibrated direct-line model) "
        "plus a last-mile disk for the chosen access mode. The shaded union is roughly "
        "how far you can get within the time budget."
    )

    controls = st.columns([2, 1, 1])
    budget = controls[0].slider("Time budget (minutes)", min_value=15, max_value=90, value=60, step=5)
    mode = controls[1].selectbox("Last mile", options=list(transit.ACCESS_SPEEDS_KMH.keys()), index=0)
    origin = controls[2].selectbox(
        "Origin", options=sorted(transit.STATION_COORDS.keys()),
        index=sorted(transit.STATION_COORDS.keys()).index(transit.DEFAULT_ORIGIN),
    )

    reach = transit.reachable_stations(float(budget), origin=origin, mode=mode)
    if not reach:
        st.info("No stations reachable within the budget.")
        return

    o_lat, o_lon = transit.STATION_COORDS[origin]
    rows = [
        {
            "name": r.name,
            "lat": r.lat,
            "lon": r.lon,
            "rail_minutes": round(r.rail_minutes, 1),
            "reach_km": round(r.reach_km, 2),
            "radius_m": r.reach_km * 1000.0,
        }
        for r in reach
    ]
    disk_df = pd.DataFrame(rows)

    # Colour disks from green (close) to red (near the budget edge) by rail time.
    max_rail = max((r["rail_minutes"] for r in rows), default=1.0) or 1.0

    def disk_color(row):
        t = min(1.0, row["rail_minutes"] / max_rail)
        return [int(255 * t), int(180 * (1 - t)) + 40, 60, 70]

    disk_df["color"] = disk_df.apply(disk_color, axis=1)

    disk_layer = pdk.Layer(
        "ScatterplotLayer",
        data=disk_df,
        get_position=["lon", "lat"],
        get_radius="radius_m",
        get_fill_color="color",
        stroked=True,
        get_line_color=[80, 80, 80, 120],
        line_width_min_pixels=1,
        pickable=True,
    )
    station_layer = pdk.Layer(
        "ScatterplotLayer",
        data=disk_df,
        get_position=["lon", "lat"],
        get_radius=400,
        get_fill_color=[30, 30, 30, 220],
        pickable=True,
    )
    origin_layer = pdk.Layer(
        "ScatterplotLayer",
        data=pd.DataFrame([{"name": origin, "lat": o_lat, "lon": o_lon}]),
        get_position=["lon", "lat"],
        get_radius=900,
        get_fill_color=[0, 90, 255, 230],
        pickable=True,
    )
    tooltip = {
        "html": "<b>{name}</b><br>Train: {rail_minutes} min<br>Last-mile reach: {reach_km} km",
        "style": {"color": "white"},
    }
    deck = pdk.Deck(
        layers=[disk_layer, station_layer, origin_layer],
        initial_view_state={"latitude": o_lat, "longitude": o_lon, "zoom": 8},
        tooltip=tooltip,
    )
    st.pydeck_chart(deck)

    st.caption(f"{len(reach)} stations reachable within {budget} min by train from {origin}.")
    st.dataframe(
        disk_df[["name", "rail_minutes", "reach_km"]].rename(
            columns={"rail_minutes": "train min", "reach_km": "last-mile km"}
        ),
        use_container_width=True,
        hide_index=True,
    )


def render_overview(
    view_df: pd.DataFrame,
    filtered_df: pd.DataFrame,
    diff_df: pd.DataFrame,
    jobs_all_df: pd.DataFrame,
    stats_df: pd.DataFrame,
):
    st.subheader("Overview")
    kpi_df = summarize.summarize_kpi(diff_df, filtered_df, stats_df)
    kpi = kpi_df.iloc[0].to_dict() if not kpi_df.empty else {}
    cols = st.columns(4)
    cols[0].metric("New jobs", kpi.get("new_jobs_total", 0) or 0)
    cols[1].metric("Recruiting active", kpi.get("companies_recruiting_active", 0) or 0)
    cols[2].metric("Domains crawled", kpi.get("domains_crawled", 0) or 0)
    cols[3].metric("Domains with jobs", kpi.get("domains_with_jobs", 0) or 0)
    if kpi.get("top_skip_reasons"):
        st.caption(f"Top skip reasons: {kpi.get('top_skip_reasons')}")

    st.subheader("Top companies right now")
    top_source = filtered_df.copy()
    if "recruiting_active" in top_source.columns:
        top_source = top_source[top_source["recruiting_active"] == True]  # noqa: E712
    if "hide_flag" in top_source.columns:
        top_source = top_source[top_source["hide_flag"] == False]  # noqa: E712
    if "status" in top_source.columns:
        top_source = top_source[top_source["status"] != "excluded"]
    top_df = summarize.summarize_top_companies(top_source, diff_df, jobs_all_df, top_n=10)
    st.dataframe(top_df, use_container_width=True)
    if not top_df.empty:
        inspect_id = st.selectbox(
            "Open in Inspector",
            options=top_df["business_id"].astype(str).tolist(),
            format_func=lambda bid: f"{top_df[top_df['business_id'].astype(str)==bid]['name'].iloc[0]} ({bid})",
        )
        if st.button("Inspect selected"):
            st.session_state["selected_bid"] = inspect_id
            st.session_state["page"] = "Inspector"
            st.session_state["jobs_context"] = None
            st.experimental_rerun()

    st.subheader("New jobs by tag / industry / station")
    tags_df = summarize.summarize_tags(diff_df, filtered_df).head(10)
    stations_df = summarize.summarize_stations(filtered_df, diff_df).head(10)
    industry_df = summarize.summarize_industry(filtered_df, diff_df).head(10)
    cols = st.columns(3)
    cols[0].caption("Tags")
    cols[0].dataframe(tags_df, use_container_width=True)
    cols[1].caption("Stations")
    cols[1].dataframe(stations_df, use_container_width=True)
    cols[2].caption("Industry")
    cols[2].dataframe(industry_df, use_container_width=True)

    st.subheader("Data quality alerts")
    alerts = {
        "missing_website": int(filtered_df["website.url"].isna().sum()) if "website.url" in filtered_df.columns else None,
        "missing_latlon": int(
            filtered_df[filtered_df["lat"].isna() | filtered_df["lon"].isna()].shape[0]
        )
        if {"lat", "lon"}.issubset(filtered_df.columns)
        else None,
        "missing_industry": int(
            filtered_df["industry_effective"].isna().sum()
        )
        if "industry_effective" in filtered_df.columns
        else None,
    }
    st.write(alerts)


def render_inspector(
    view_df: pd.DataFrame,
    filtered_df: pd.DataFrame,
    diff_df: pd.DataFrame,
    jobs_all_df: pd.DataFrame,
    opts: FilterOptions,
):
    st.subheader("Inspector")
    jobs_ctx = st.session_state.get("jobs_context") or {}
    if jobs_ctx.get("source") == "jobs":
        st.info(f"Opened from Jobs · New jobs: {jobs_ctx.get('job_count', 0)}")
    selected_bid = st.session_state.get("selected_bid")
    view_ids = [str(x) for x in st.session_state.get("view_ids", [])]
    base_df = filtered_df if not filtered_df.empty else view_df
    options = base_df["business_id"].astype(str).tolist()
    if selected_bid and selected_bid not in options and "business_id" in view_df.columns:
        if str(selected_bid) in view_df["business_id"].astype(str).tolist():
            options = [str(selected_bid)] + options
    bid_to_name = dict(zip(view_df["business_id"].astype(str), view_df.get("name", "")))
    default_bid = selected_bid if selected_bid in options else None
    if not options:
        st.info("No companies available for inspection.")
        return
    selected_bid = st.selectbox(
        "Select company",
        options=options,
        index=options.index(default_bid) if default_bid else 0,
        format_func=lambda b: f"{bid_to_name.get(b, '')} ({b})",
    )
    st.session_state["selected_bid"] = selected_bid
    prev_bid, next_bid = get_prev_next(view_ids, selected_bid)
    nav_cols = st.columns(3)
    if nav_cols[0].button("Prev") and prev_bid:
        st.session_state["selected_bid"] = prev_bid
        st.experimental_rerun()
    nav_cols[1].button("Current")
    if nav_cols[2].button("Next") and next_bid:
        st.session_state["selected_bid"] = next_bid
        st.experimental_rerun()
    if selected_bid not in view_ids:
        st.warning("Selected company is outside the current filtered set.")
        if st.button("Reset selection to first visible"):
            st.session_state["selected_bid"] = view_ids[0] if view_ids else None
            st.experimental_rerun()
        if st.button("Reset filters to Default"):
            apply_preset_to_state("Default")
            st.session_state["preset"] = "Default"
            st.experimental_rerun()
    row = base_df[base_df["business_id"].astype(str) == selected_bid].iloc[0]
    st.markdown(f"**{row.get('name','')}** (`{selected_bid}`)")
    if row.get("website.url"):
        st.markdown(f"[Website]({row.get('website.url')})")

    facts = {
        "city": row.get("city") or row.get("addresses.0.city") or row.get("_source_city") or row.get("domicile"),
        "nearest_station": row.get("nearest_station"),
        "distance_km": row.get("distance_km"),
        "industry_raw": row.get("industry_raw"),
        "industry_effective": row.get("industry_effective"),
        "tags_raw": row.get("tags_raw"),
        "tags_effective": row.get("tags_effective"),
        "status": row.get("status"),
        "hide_flag": row.get("hide_flag"),
        "note": row.get("note"),
    }
    st.write(facts)
    if opts.cities:
        st.caption(f"City filter matched: input={', '.join(opts.cities)} / data={facts.get('city')}")

    st.subheader("Score & reasons")
    score_val = row.get("score")
    st.write({"score": score_val, "score_reasons": row.get("score_reasons"), "excluded_reason": row.get("excluded_reason")})
    if row.get("score_reasons"):
        reasons = [r.strip() for r in str(row.get("score_reasons")).replace(",", ";").split(";") if r.strip()]
        st.write("Reasons:", reasons)

    expl = explain_company(row, opts)
    if expl["passes"]:
        st.success(f"Passes filters: {expl['reasons']}")
    else:
        st.warning(f"Fails filters: {expl['fails']}")

    st.subheader("Jobs")
    new_jobs = select_company_jobs(selected_bid, diff_df)
    all_jobs = select_company_jobs(selected_bid, jobs_all_df)
    expand_new = jobs_ctx.get("source") == "jobs"
    with st.expander("New jobs", expanded=expand_new):
        if not new_jobs.empty:
            st.dataframe(new_jobs[["job_title", "job_url", "tags", "location_text"]].head(20), use_container_width=True)
        else:
            st.caption("No new jobs for this company.")
    with st.expander("All jobs", expanded=not expand_new):
        if not all_jobs.empty:
            st.dataframe(all_jobs[["job_title", "job_url", "tags", "location_text"]].head(50), use_container_width=True)
        else:
            st.caption("No jobs available.")


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--master", help="Path to master Excel (Shortlist sheet).")
    parser.add_argument("--curation", help="Path to curation CSV (overlay).")
    parser.add_argument("--diff", help="Path to jobs diff (optional).")
    args, _ = parser.parse_known_args()

    st.set_page_config(page_title="Apprscan Viewer", layout="wide")
    st.title("Apprscan viewer / editor")

    latest_master = find_latest_master()
    master_path = _resolve_path(args.master, find_latest_master)
    diff_path = _resolve_path(args.diff, find_latest_diff)
    curation_default = args.curation or "out/curation/master_curation.csv"

    st.sidebar.subheader("Paths")
    master_input = st.sidebar.text_input("Master path", value=str(master_path) if master_path else "")
    diff_input = st.sidebar.text_input("Jobs diff path (optional)", value=str(diff_path) if diff_path else "")
    curation_input = st.sidebar.text_input("Curation overlay", value=curation_default)
    page = st.sidebar.radio("View", ["Overview", "Inspector", "Curate", "Jobs", "Train reach"], key="page")
    last_page = st.session_state.get("last_page")
    if page != "Jobs" and last_page != "Jobs":
        if st.session_state.get("jobs_context"):
            st.session_state["jobs_context"] = None
    if st.session_state.get("focus_bid") and not st.session_state.get("keep_focus"):
        if last_page and page != last_page:
            st.session_state["focus_bid"] = None
    st.session_state["last_page"] = page

    # Train reach is independent of master/curation data — render it before the
    # data-loading requirements so it works on a fresh deploy with no master.
    if page == "Train reach":
        render_train_reach()
        st.stop()

    if not master_input:
        st.warning("Master path missing. Run apprscan run to generate master.xlsx or provide a path.")
        return

    master_path = Path(master_input)
    if not master_path.exists():
        st.error(f"Master not found: {master_path}")
        return

    curation_path = Path(curation_input)

    master_df, curation_df = load_data(master_path, curation_path)
    try:
        validate_master(master_df)
    except ValueError as exc:
        st.error(f"Master validation failed: {exc}")
        return
    applied = apply_curation(master_df, curation_df)
    view_df = applied.view

    dates, mismatch = artifact_dates_info(master_path, Path(diff_input) if diff_input else None)
    with st.expander("Resolved artifacts", expanded=True):
        st.write(
            {
                "master": str(master_path),
                "diff": diff_input or "(none)",
                "curation": str(curation_path),
                "rows_master": len(master_df),
                "rows_curation": len(curation_df),
                "date_master": dates.get("master"),
                "date_diff": dates.get("diff"),
            }
        )
    if mismatch:
        st.error("Master date and diff run date do not match.")

    st.sidebar.subheader("Filters")
    industries = sorted(view_df["industry_effective"].dropna().unique()) if "industry_effective" in view_df.columns else []

    if "preset" not in st.session_state:
        st.session_state["preset"] = "Default"
        apply_preset_to_state("Default")

    preset_choice = st.sidebar.selectbox(
        "View preset",
        options=["Default", "Shortlist", "Recruiting", "Cleanup Other", "Hidden review", "Excluded review"],
        index=["Default", "Shortlist", "Recruiting", "Cleanup Other", "Hidden review", "Excluded review"].index(st.session_state["preset"]) if st.session_state.get("preset") else 0,
    )
    if preset_choice != st.session_state["preset"]:
        st.session_state["preset"] = preset_choice
        apply_preset_to_state(preset_choice)
        st.session_state["focus_bid"] = None

    industry_sel = st.sidebar.multiselect("Industry", industries, default=st.session_state.get("filt_industries", industries), key="filt_industries")
    city_candidates = sorted(
        {
            str(val).strip()
            for col in ["city", "addresses.0.city", "_source_city", "domicile"]
            if col in view_df.columns
            for val in view_df[col].dropna().unique().tolist()
            if str(val).strip()
        }
    )
    city_sel = st.sidebar.multiselect("City", city_candidates, key="filt_cities")
    status_sel = st.sidebar.multiselect("Status", ["shortlist", "excluded", "neutral"], default=st.session_state.get("filt_statuses", []), key="filt_statuses")
    include_hidden = st.sidebar.checkbox("Include hidden", value=st.session_state.get("filt_include_hidden", False), key="filt_include_hidden")
    include_housing = st.sidebar.checkbox("Include housing-like names", value=st.session_state.get("filt_include_housing", False), key="filt_include_housing")
    include_excluded = st.sidebar.checkbox("Include excluded", value=st.session_state.get("filt_include_excluded", False), key="filt_include_excluded")
    only_recruiting = st.sidebar.checkbox("Only recruiting active", value=st.session_state.get("filt_only_recruiting", False), key="filt_only_recruiting")
    min_score = st.sidebar.number_input("Min score", value=float(st.session_state.get("filt_min_score", 0)), step=1.0, key="filt_min_score")
    max_distance = st.sidebar.number_input("Max distance km", value=float(st.session_state.get("filt_max_distance", 5.0)), step=0.5, key="filt_max_distance")
    search = st.sidebar.text_input("Search (name/id/domain/note)", value=st.session_state.get("filt_search", ""), key="filt_search")
    include_tags = st.sidebar.text_input("Include tags (comma)", value=st.session_state.get("filt_include_tags", ""), key="filt_include_tags")
    exclude_tags = st.sidebar.text_input("Exclude tags (comma)", value=st.session_state.get("filt_exclude_tags", ""), key="filt_exclude_tags")

    opts = FilterOptions(
        industries=industry_sel,
        cities=city_sel,
        include_hidden=include_hidden,
        include_excluded=include_excluded,
        include_housing=include_housing,
        statuses=status_sel,
        focus_business_id=st.session_state.get("focus_bid"),
        min_score=min_score or None,
        max_distance_km=max_distance or None,
        include_tags=[t.strip() for t in include_tags.split(",") if t.strip()],
        exclude_tags=[t.strip() for t in exclude_tags.split(",") if t.strip()],
        search=search or None,
        only_recruiting=only_recruiting,
    )
    opts_nofocus = FilterOptions(
        industries=industry_sel,
        cities=city_sel,
        include_hidden=include_hidden,
        include_excluded=include_excluded,
        include_housing=include_housing,
        statuses=status_sel,
        focus_business_id=None,
        min_score=min_score or None,
        max_distance_km=max_distance or None,
        include_tags=[t.strip() for t in include_tags.split(",") if t.strip()],
        exclude_tags=[t.strip() for t in exclude_tags.split(",") if t.strip()],
        search=search or None,
        only_recruiting=only_recruiting,
    )

    filtered_df = filter_data(view_df, opts)
    filtered_df_no_focus = filter_data(view_df, opts_nofocus)
    st.session_state["view_ids"] = filtered_df["business_id"].astype(str).tolist()
    st.session_state["view_label"] = "; ".join(describe_filters(opts))
    if "pending_extra" not in st.session_state:
        st.session_state["pending_extra"] = []
    diff_df = load_diff_df(Path(diff_input) if diff_input else None)
    jobs_all_df = load_jobs_all(master_path)
    stats_df = load_stats_df(master_path)

    st.sidebar.caption("Active filters:\n- " + "\n- ".join(describe_filters(opts)))
    view_ids = st.session_state.get("view_ids", [])
    sel_bid = st.session_state.get("selected_bid")
    if sel_bid in view_ids:
        idx = view_ids.index(sel_bid) + 1
        total = len(view_ids)
        sel_name = ""
        if "name" in filtered_df.columns:
            match = filtered_df[filtered_df["business_id"].astype(str) == sel_bid]
            if not match.empty:
                sel_name = match.iloc[0].get("name", "")
        st.sidebar.caption(f"Selected: {sel_name} ({idx}/{total})")
    focus_bid = st.session_state.get("focus_bid")
    if focus_bid:
        keep_tag = " [Keep]" if st.session_state.get("keep_focus") else ""
        st.sidebar.caption(f"Focus: {focus_bid}{keep_tag}")
        if st.sidebar.button("Clear focus", key="sidebar_clear_focus"):
            st.session_state["focus_bid"] = None
            st.experimental_rerun()
    if st.session_state.get("view_label"):
        st.sidebar.caption(f"View context: {st.session_state['view_label']}")
    st.sidebar.caption(f"Pending edits: {len(st.session_state.get('pending_extra', []))}")
    if st.sidebar.button("Reset filters"):
        apply_preset_to_state("Default")
        st.session_state["preset"] = "Default"
        st.session_state["focus_bid"] = None
        st.experimental_rerun()

    if st.session_state.get("focus_bid"):
        st.warning(
            f"FOCUS MODE: Only showing {st.session_state.get('focus_bid')}",
            icon="⚠️",
        )
        st.session_state["keep_focus"] = st.checkbox("Keep focus while switching views", value=True)
        if st.button("Clear focus"):
            st.session_state["focus_bid"] = None
            st.experimental_rerun()
    st.markdown(f"**Visible companies:** {len(filtered_df)} / {len(view_df)} (master), using master: `{master_path.name}`")
    st.caption(f"Curation file: {curation_path}")

    if page == "Overview":
        render_overview(view_df, filtered_df, diff_df, jobs_all_df, stats_df)
        st.stop()
    if page == "Inspector":
        render_inspector(view_df, filtered_df, diff_df, jobs_all_df, opts)
        st.stop()
    if page == "Jobs":
        st.subheader("Jobs (new since last run)")
        if diff_df.empty:
            st.info("No jobs diff available.")
            st.stop()
        joined = join_new_jobs_with_companies(diff_df, filtered_df)
        company_list = []
        if "company_business_id" in joined.columns:
            for bid, group in joined.groupby("company_business_id"):
                bid_str = str(bid)
                name = ""
                if "company_name" in group.columns and group["company_name"].notna().any():
                    name = str(group["company_name"].dropna().iloc[0])
                elif "name" in group.columns and group["name"].notna().any():
                    name = str(group["name"].dropna().iloc[0])
                score = group["score"].max() if "score" in group.columns else 0
                company_list.append(
                    {"business_id": bid_str, "name": name, "job_count": len(group), "score": score}
                )
        if company_list:
            company_df = pd.DataFrame(company_list)
            company_df = company_df.sort_values(
                ["job_count", "score", "name"], ascending=[False, False, True]
            )
            selected_company = st.selectbox(
                "Selected company",
                options=company_df["business_id"].tolist(),
                format_func=lambda b: f"{company_df[company_df['business_id']==b]['name'].iloc[0]} ({b})",
            )
            if st.button("Open in Inspector"):
                st.session_state["selected_bid"] = selected_company
                st.session_state["jobs_context"] = {
                    "source": "jobs",
                    "opened_at": datetime.utcnow().isoformat(),
                    "job_count": int(company_df[company_df["business_id"] == selected_company]["job_count"].iloc[0]),
                }
                st.session_state["page"] = "Inspector"
                st.experimental_rerun()
        group_mode = st.radio("Group by", ["None", "Company", "Tag"], horizontal=True)
        if group_mode == "Company" and "company_business_id" in joined.columns:
            st.dataframe(
                joined.groupby("company_business_id")
                .size()
                .reset_index(name="new_jobs")
                .sort_values("new_jobs", ascending=False)
                .head(50),
                use_container_width=True,
            )
        elif group_mode == "Tag" and "tags" in joined.columns:
            tags = joined.explode("tags")
            st.dataframe(
                tags.groupby("tags")
                .size()
                .reset_index(name="new_jobs")
                .sort_values("new_jobs", ascending=False)
                .head(50),
                use_container_width=True,
            )
        cols = [c for c in ["company_business_id", "company_name", "job_title", "tags", "job_url", "nearest_station", "distance_km", "score"] if c in joined.columns]
        st.dataframe(joined[cols].head(200), use_container_width=True)
        st.stop()

    st.subheader("Curate toolbar")
    view_ids = st.session_state.get("view_ids", [])
    if view_ids:
        if st.session_state.get("selected_bid") not in view_ids:
            st.session_state["selected_bid"] = view_ids[0]
        selected_bid = st.selectbox("Selected company", options=view_ids, key="selected_bid")
        prev_bid, next_bid = get_prev_next(view_ids, selected_bid)
        nav_cols = st.columns(5)
        if nav_cols[0].button("Prev", disabled=prev_bid is None) and prev_bid:
            st.session_state["selected_bid"] = prev_bid
            st.experimental_rerun()
        if nav_cols[1].button("Next", disabled=next_bid is None) and next_bid:
            st.session_state["selected_bid"] = next_bid
            st.experimental_rerun()
        if nav_cols[2].button("Open in Inspector"):
            st.session_state["page"] = "Inspector"
            st.session_state["jobs_context"] = None
            st.experimental_rerun()
        if nav_cols[3].button("Stage Shortlist"):
            st.session_state["pending_extra"].append({"business_id": selected_bid, "status": "shortlist"})
        if nav_cols[4].button("Stage Exclude"):
            st.session_state["pending_extra"].append({"business_id": selected_bid, "status": "excluded"})
    else:
        st.info("No rows in current filtered set.")

    # Inline map (read-only) for current filtered set
    st.subheader("Map (current filtered view)")
    preview_pending = st.checkbox("Preview pending changes on map", value=False)
    map_source_df = filtered_df
    if preview_pending:
        st.warning("Previewing pending changes (not committed).")
        pending_curation = update_curation_from_edits(
            merge_edits([], st.session_state.get("pending_extra", [])),
            curation_df,
            source_master=master_path.name,
            updated_by="preview",
        )
        applied_preview = apply_curation(master_df, pending_curation)
        map_source_df = filter_data(applied_preview.view, opts)
        badge = "PREVIEWING PENDING CHANGES"
    else:
        badge = "COMMITTED VIEW"
    st.caption(badge)
    max_points = st.slider("Max points on map", min_value=200, max_value=5000, value=2000, step=100)
    pin_radius = st.slider("Pin radius (meters)", min_value=100, max_value=3000, value=600, step=50)
    if len(map_source_df) > max_points:
        st.warning(f"Showing first {max_points} of {len(map_source_df)} points. Tighten filters or increase limit.")
        map_source_df = map_source_df.head(max_points)
    prepare_map(map_source_df, radius=pin_radius)

    edit_cols = ["status", "hide_flag", "note", "industry_override", "tags_add", "tags_remove"]
    display_cols = ["business_id", "name"] + edit_cols + ["industry_effective", "score", "distance_km", "nearest_station"]
    for col in display_cols:
        if col not in filtered_df.columns:
            filtered_df[col] = None
    edit_df = filtered_df[display_cols].copy()
    edit_df.set_index("business_id", inplace=True)
    edited = st.data_editor(edit_df, num_rows="dynamic", use_container_width=True)

    # Session state for pending extra edits (quick/bulk)
    if "pending_extra" not in st.session_state:
        st.session_state["pending_extra"] = []

    # Row details + quick actions
    st.subheader("Row details / quick actions")
    selected_bid = st.session_state.get("selected_bid")
    if selected_bid and selected_bid in filtered_df["business_id"].astype(str).tolist():
        row_sel = filtered_df[filtered_df["business_id"].astype(str) == str(selected_bid)].iloc[0]
        st.markdown(f"**{row_sel.get('name','')}** (`{selected_bid}`)")
        col1, col2 = st.columns(2)
        with col1:
            status_val = st.radio("Status", options=["shortlist", "neutral", "excluded"], index=["shortlist", "neutral", "excluded"].index(row_sel.get("status") or "neutral") if (row_sel.get("status") or "neutral") in ["shortlist", "neutral", "excluded"] else 1)
            hide_val = st.checkbox("Hide", value=bool(row_sel.get("hide_flag", False)))
            note_val = st.text_area("Note", value=row_sel.get("note") or "")
        with col2:
            industry_override_val = st.text_input("Industry override", value=row_sel.get("industry_override") or "")
            tags_add_val = st.text_input("Tags add (comma/;)", value=row_sel.get("tags_add") or "")
            tags_remove_val = st.text_input("Tags remove (comma/;)", value=row_sel.get("tags_remove") or "")
            st.text(f"Industry raw: {row_sel.get('industry_raw', '')}")
            st.text(f"Industry effective: {row_sel.get('industry_effective', '')}")
            st.text(f"Tags raw: {row_sel.get('tags_raw', [])}")
            st.text(f"Tags effective: {row_sel.get('tags_effective', [])}")
            st.text(f"Score: {row_sel.get('score', '')}, Distance km: {row_sel.get('distance_km', '')}, Station: {row_sel.get('nearest_station', '')}")

        if st.button("Apply row edits to pending"):
            st.session_state["pending_extra"].append(
                {
                    "business_id": selected_bid,
                    "status": status_val,
                    "hide_flag": hide_val,
                    "note": note_val,
                    "industry_override": industry_override_val,
                    "tags_add": tags_add_val,
                    "tags_remove": tags_remove_val,
                }
            )
            st.success("Row edits staged.")

        quick_cols = st.columns(4)
        if quick_cols[0].button("Quick: Shortlist"):
            st.session_state["pending_extra"].append({"business_id": selected_bid, "status": "shortlist"})
        if quick_cols[1].button("Quick: Exclude"):
            st.session_state["pending_extra"].append({"business_id": selected_bid, "status": "excluded"})
        if quick_cols[2].button("Quick: Hide"):
            st.session_state["pending_extra"].append({"business_id": selected_bid, "hide_flag": True})
        if quick_cols[3].button("Quick: Unhide"):
            st.session_state["pending_extra"].append({"business_id": selected_bid, "hide_flag": False})
        if st.button("Focus: this company only"):
            st.session_state["focus_bid"] = selected_bid
            st.experimental_rerun()
    else:
        st.info("Select a company using the Curate toolbar above.")

    # Bulk actions
    with st.expander("Bulk actions (current filtered set)", expanded=False):
        st.write(f"Affects {len(filtered_df)} rows (current filters).")
        st.caption("Active filters: " + "; ".join(describe_filters(opts)))
        bulk_status = st.selectbox("Set status", options=["", "shortlist", "neutral", "excluded"], index=0)
        bulk_hide = st.selectbox("Set hide_flag", options=["", "hide", "unhide"], index=0)
        bulk_tag_add = st.text_input("Bulk add tag(s) (comma/;)")
        bulk_tag_remove = st.text_input("Bulk remove tag(s) (comma/;)")
        bulk_industry = st.text_input("Bulk set industry override")
        if st.button("Stage bulk changes"):
            edits = []
            for bid in filtered_df["business_id"].tolist():
                payload = {"business_id": bid}
                if bulk_status:
                    payload["status"] = bulk_status
                if bulk_hide:
                    payload["hide_flag"] = True if bulk_hide == "hide" else False
                if bulk_tag_add:
                    payload["tags_add"] = bulk_tag_add
                if bulk_tag_remove:
                    payload["tags_remove"] = bulk_tag_remove
                if bulk_industry:
                    payload["industry_override"] = bulk_industry
                edits.append(payload)
            st.session_state["pending_extra"].extend(edits)
            st.success(f"Bulk staged for {len(filtered_df)} rows.")

    # Proposed curation and diff summary (dry-run)
    edited_records = edited.reset_index().to_dict(orient="records")
    combined_edits = merge_edits(edited_records, st.session_state["pending_extra"])
    proposed_curation = update_curation_from_edits(
        combined_edits,
        curation_df,
        source_master=master_path.name,
        updated_by="streamlit",
    )
    before_cur = curation_df[["business_id", "status", "hide_flag", "note", "industry_override", "tags_add", "tags_remove"]] if not curation_df.empty else pd.DataFrame(columns=["business_id", "status", "hide_flag", "note", "industry_override", "tags_add", "tags_remove"])
    after_cur = proposed_curation[["business_id", "status", "hide_flag", "note", "industry_override", "tags_add", "tags_remove"]]
    diff_info = compute_edit_diff(before_cur, after_cur)

    with st.expander("Pending changes (dry-run)", expanded=True):
        st.write(diff_info["summary"])
        if diff_info["examples"]:
            st.write("Examples:", diff_info["examples"])
        if st.button("Export outreach.xlsx (current filters)"):
            out_dir = Path("out/curation")
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"outreach_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
            export_cols = [c for c in ["business_id", "name", "website.url", "nearest_station", "distance_km", "score", "industry_effective", "tags_effective", "note", "status", "recruiting_active", "job_count_total", "job_count_new_since_last"] if c in filtered_df.columns]
            filters_text = "; ".join(describe_filters(opts))
            with pd.ExcelWriter(out_path) as writer:
                filtered_df[export_cols].to_excel(writer, index=False, sheet_name="Outreach")
                meta = pd.DataFrame(
                    [
                        {
                            "master": str(master_path),
                            "diff": diff_input or "(none)",
                            "curation": str(curation_path),
                            "date_master": dates.get("master"),
                            "date_diff": dates.get("diff"),
                            "filters": filters_text,
                            "exported_at": datetime.utcnow().isoformat(),
                        }
                    ]
                )
                meta.to_excel(writer, index=False, sheet_name="Meta")
            st.success(f"Exported {len(filtered_df)} rows to {out_path}")

    if st.button("Commit changes"):
        batch_id = uuid.uuid4().hex[:8]
        backup = None
        try:
            backup = write_curation_with_backup(proposed_curation, curation_path, batch_id=batch_id)
        except Exception as exc:
            st.error(f"Failed to write curation: {exc}")
            return
        append_audit(
            {
                "ts": datetime.utcnow().isoformat(),
                "batch_id": batch_id,
                "changed_rows": diff_info["summary"].get("changed_rows_count", 0),
                "source_master": master_path.name,
                "curation_path": str(curation_path),
                "backup_path": str(backup) if backup else None,
                "diff": diff_info["summary"],
            },
            Path("out/curation/audit_log.jsonl"),
        )
        st.success(f"Saved changes ({diff_info['summary'].get('changed_rows_count', 0)} rows). Backup: {backup}")
        st.stop()

    st.subheader("New jobs (diff)")
    if not diff_df.empty:
        cols = [c for c in ["company_business_id", "company_name", "job_title", "tags", "job_url"] if c in diff_df.columns]
        st.dataframe(diff_df[cols].head(100), use_container_width=True)
    else:
        st.caption("No diff provided.")

    # Audit / undo tab
    st.subheader("Audit / Undo")
    audit_path = Path("out/curation/audit_log.jsonl")
    events = load_audit(audit_path, limit=200)
    if not events:
        st.caption("No audit log yet.")
    else:
        events_sorted = list(reversed(events))
        options = [f"{e.get('ts','')} | batch {e.get('batch_id','')} | rows {e.get('changed_rows', e.get('changed_rows_count','0'))}" for e in events_sorted]
        idx = st.selectbox("Select event", options=range(len(options)), format_func=lambda i: options[i])
        event = events_sorted[idx]
        st.write(event)
        backup_path = event.get("backup_path")
        if backup_path and Path(backup_path).exists():
            st.success(f"Backup exists: {backup_path}")
            if st.checkbox("I understand this will overwrite current curation"):
                if st.button("Restore from backup"):
                    try:
                        safety = restore_curation_from_backup(backup_path, curation_path)
                    except Exception as exc:
                        st.error(f"Restore failed: {exc}")
                        return
                    append_audit(
                        {
                            "ts": datetime.utcnow().isoformat(),
                            "type": "restore",
                            "restored_from_batch_id": event.get("batch_id"),
                            "backup_used": backup_path,
                            "safety_backup": str(safety) if safety else None,
                            "curation_path": str(curation_path),
                        },
                        audit_path,
                    )
                    st.success(f"Restored from {backup_path}. Safety backup: {safety}")
                    st.session_state["pending_extra"] = []
                    st.experimental_rerun()
        else:
            st.warning("Backup not found for this event; cannot restore.")


if __name__ == "__main__":
    main()
