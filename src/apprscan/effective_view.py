"""Shared builder for effective (curated + filtered) company view."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

import pandas as pd

from .artifacts import artifact_date
from .curation import apply_curation, read_curation, read_master, validate_master
from .filters_view import FilterOptions, filter_data


@dataclass(frozen=True)
class ArtifactPaths:
    master: Path
    curation: Optional[Path] = None
    diff: Optional[Path] = None


@dataclass(frozen=True)
class EffectiveViewResult:
    view_df: pd.DataFrame
    filtered_df: pd.DataFrame
    meta: Dict[str, Any]


def describe_filters(opts: FilterOptions) -> list[str]:
    items = []
    if opts.industries:
        items.append(f"Industry: {', '.join(opts.industries)}")
    if opts.cities:
        items.append(f"City: {', '.join(opts.cities)}")
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


def build_effective_view(paths: ArtifactPaths, filters: FilterOptions) -> EffectiveViewResult:
    master_df = read_master(paths.master)
    validate_master(master_df)
    curation_df = read_curation(paths.curation) if paths.curation else read_curation("out/curation/master_curation.csv")
    applied = apply_curation(master_df, curation_df)
    view_df = applied.view
    filtered_df = filter_data(view_df, filters)
    date_master = artifact_date(paths.master)
    date_diff = artifact_date(paths.diff) if paths.diff else None
    meta = {
        "master": str(paths.master),
        "curation": str(paths.curation) if paths.curation else None,
        "diff": str(paths.diff) if paths.diff else None,
        "rows_master": len(master_df),
        "rows_curation": len(curation_df),
        "rows_filtered": len(filtered_df),
        "date_master": date_master,
        "date_diff": date_diff,
        "mismatch": bool(date_master and date_diff and date_master != date_diff),
        "active_filters": describe_filters(filters),
    }
    return EffectiveViewResult(view_df=view_df, filtered_df=filtered_df, meta=meta)
