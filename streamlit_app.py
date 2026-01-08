"""Streamlit viewer/editor for master shortlist with curation overlay."""

from __future__ import annotations

import argparse
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import pydeck as pdk

from apprscan.artifacts import find_latest_diff, find_latest_master, artifact_date
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


def _resolve_path(path_str: str | None, finder) -> Path | None:
    if path_str:
        return Path(path_str)
    return finder() or None


def load_data(master_path: Path, curation_path: Path | None):
    master_df = read_master(master_path)
    curation_df = read_curation(curation_path) if curation_path else read_curation("out/curation/master_curation.csv")
    return master_df, curation_df


def describe_filters(opts: FilterOptions) -> list[str]:
    items = []
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
        min_score=min_score or None,
        max_distance_km=max_distance or None,
        include_tags=[t.strip() for t in include_tags.split(",") if t.strip()],
        exclude_tags=[t.strip() for t in exclude_tags.split(",") if t.strip()],
        search=search or None,
        only_recruiting=only_recruiting,
    )

    filtered_df = filter_data(view_df, opts)

    st.sidebar.caption("Active filters:\n- " + "\n- ".join(describe_filters(opts)))
    if st.sidebar.button("Reset filters"):
        apply_preset_to_state("Default")
        st.session_state["preset"] = "Default"
        st.experimental_rerun()

    st.markdown(f"**Visible companies:** {len(filtered_df)} / {len(view_df)} (master), using master: `{master_path.name}`")
    st.caption(f"Curation file: {curation_path}")

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
    bid_options = filtered_df["business_id"].tolist()
    bid_to_name = dict(zip(filtered_df["business_id"], filtered_df["name"]))
    selected_bid = st.selectbox("Select company", options=bid_options, format_func=lambda b: f"{bid_to_name.get(b, '')} ({b})")
    if selected_bid:
        row_sel = filtered_df[filtered_df["business_id"] == selected_bid].iloc[0]
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
    if diff_input and Path(diff_input).exists():
        diff_df = pd.read_excel(diff_input) if diff_input.endswith(".xlsx") else pd.read_json(diff_input, lines=True)
        st.dataframe(diff_df[["company_business_id", "company_name", "job_title", "tags", "job_url"]].head(100), use_container_width=True)
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
