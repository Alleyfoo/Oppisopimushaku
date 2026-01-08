"""Filtering helpers for Streamlit viewer/editor."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List

import pandas as pd

HOUSING_NAME_RE = re.compile(r"(?i)\b(as\.?\s*oy|asunto\s*oy|asunto-?osakeyhtio|taloyhtio)")
CITY_TRANSLATION = str.maketrans({"ä": "a", "ö": "o", "å": "a"})


@dataclass
class FilterOptions:
    industries: List[str] = field(default_factory=list)
    include_hidden: bool = False
    include_excluded: bool = False
    include_housing: bool = False
    statuses: List[str] = field(default_factory=list)
    cities: List[str] = field(default_factory=list)
    min_score: float | None = None
    max_distance_km: float | None = None
    stations: List[str] = field(default_factory=list)
    include_tags: List[str] = field(default_factory=list)
    exclude_tags: List[str] = field(default_factory=list)
    search: str | None = None
    only_recruiting: bool = False


def normalize_tags(raw: Iterable[str]) -> List[str]:
    return sorted({str(t).strip().lower() for t in raw if str(t).strip()})


def _norm_city(val: str) -> str:
    return str(val or "").strip().lower().translate(CITY_TRANSLATION)


def filter_data(df: pd.DataFrame, opts: FilterOptions) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()

    # Housing name filter first to avoid unnecessary work.
    if not opts.include_housing and "name" in out.columns:
        out = out[~out["name"].fillna("").str.contains(HOUSING_NAME_RE, regex=True)]

    if not opts.include_hidden and "hide_flag" in out.columns:
        out = out[out["hide_flag"] == False]  # noqa: E712

    if not opts.include_excluded and "excluded_reason" in out.columns:
        out = out[out["excluded_reason"].isna() | (out["excluded_reason"] == "")]

    if opts.statuses and "status" in out.columns:
        out = out[out["status"].isin(opts.statuses)]

    if opts.industries and "industry_effective" in out.columns:
        out = out[out["industry_effective"].isin(opts.industries)]

    if opts.cities:
        cities_lower = {_norm_city(c) for c in opts.cities if c.strip()}
        def city_match(row):
            for col in ["city", "addresses.0.city", "_source_city", "domicile"]:
                if col in row and pd.notna(row[col]):
                    val = _norm_city(row[col])
                    if val in cities_lower:
                        return True
            return False
        out = out[out.apply(city_match, axis=1)]

    if opts.min_score is not None and "score" in out.columns:
        out = out[out["score"] >= opts.min_score]

    if opts.max_distance_km is not None and "distance_km" in out.columns:
        out = out[out["distance_km"].fillna(float("inf")) <= opts.max_distance_km]

    if opts.stations and "nearest_station" in out.columns:
        out = out[out["nearest_station"].isin(opts.stations)]

    if opts.only_recruiting and "recruiting_active" in out.columns:
        out = out[out["recruiting_active"] == True]  # noqa: E712

    if opts.include_tags:
        tags_target = normalize_tags(opts.include_tags)
        if "tags_effective" in out.columns:
            out = out[out["tags_effective"].apply(lambda lst: bool(set(lst) & set(tags_target)))]

    if opts.exclude_tags:
        tags_excl = set(normalize_tags(opts.exclude_tags))
        if "tags_effective" in out.columns:
            out = out[~out["tags_effective"].apply(lambda lst: bool(set(lst) & tags_excl))]

    if opts.search:
        needle = opts.search.lower().strip()
        if needle:
            def matches(row):
                fields = []
                for key in ("name", "business_id", "website.url", "note"):
                    if key in row and pd.notna(row[key]):
                        fields.append(str(row[key]).lower())
                return any(needle in f for f in fields)

            out = out[out.apply(matches, axis=1)]

    return out
