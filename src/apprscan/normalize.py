"""Data normalization helpers for PRH rows."""

from __future__ import annotations

import ast
from typing import Iterable, List, Mapping, Any

import pandas as pd
from unidecode import unidecode


ADDR_CANDIDATES = {
    "street": ["addresses.0.street", "street"],
    "postCode": ["addresses.0.postCode", "postCode"],
    "city": ["addresses.0.city", "city", "domicile", "_source_city"],
}


def pick_first(row: Mapping[str, Any], candidates: List[str]) -> str:
    for col in candidates:
        if col in row and pd.notna(row[col]) and str(row[col]).strip():
            return str(row[col]).strip()
    return ""


def clean_address(street: str, post_code: str, city: str) -> str:
    parts = [p.strip() for p in [street or "", post_code or "", city or ""] if p and p.strip()]
    return unidecode(", ".join(parts))


def normalize_companies(rows: Iterable[dict], *, industry_groups: Mapping[str, list] | None = None) -> pd.DataFrame:
    rows_list = list(rows)
    df = pd.json_normalize(rows_list, sep=".")
    if df.empty:
        df["full_address"] = []
        return df

    streets = []
    posts = []
    cities = []
    business_ids = []
    names_out = []
    industries = []
    for idx, row_series in df.iterrows():
        row = row_series.to_dict()
        original = rows_list[idx]

        def pick_name_from_names(raw) -> str:
            names_parsed = None
            if isinstance(raw, str) and raw.strip().startswith("["):
                try:
                    parsed = ast.literal_eval(raw)
                    if isinstance(parsed, list):
                        names_parsed = parsed
                except Exception:
                    names_parsed = None
            elif isinstance(raw, list):
                names_parsed = raw
            if not names_parsed:
                return ""
            names_list = [n for n in names_parsed if isinstance(n, dict)]
            if not names_list:
                return ""
            active = [n for n in names_list if not n.get("endDate")]
            candidates = active or names_list
            type1 = [n for n in candidates if str(n.get("type") or "") == "1"]
            if type1:
                candidates = type1
            def reg_key(n):
                return str(n.get("registrationDate") or "")
            candidates = sorted(candidates, key=reg_key, reverse=True)
            return candidates[0].get("name", "") if candidates else ""

        addresses = original.get("addresses") if isinstance(original, dict) else None
        if isinstance(addresses, list) and addresses:
            first_addr = addresses[0] or {}
            for key, value in first_addr.items():
                row[f"addresses.0.{key}"] = value

            if "_source_city" in original:
                # Prefer address where city matches _source_city.
                for addr in addresses:
                    if not addr:
                        continue
                    city_val = str(addr.get("city", "")).strip()
                    if city_val and city_val == str(original.get("_source_city", "")).strip():
                        for key, value in addr.items():
                            row[f"addresses.0.{key}"] = value
                        break

        street = pick_first(row, ADDR_CANDIDATES["street"])
        post = pick_first(row, ADDR_CANDIDATES["postCode"])
        city = pick_first(row, ADDR_CANDIDATES["city"])
        streets.append(street)
        posts.append(post)
        cities.append(city)

        business_id = ""
        for key in ("businessId", "businessId.value", "business_id"):
            if key in row and pd.notna(row[key]) and str(row[key]).strip():
                business_id = str(row[key]).strip()
                break
        business_ids.append(business_id)

        # Name normalization
        name_val = row.get("name") or ""
        parsed_name = pick_name_from_names(original.get("names")) if isinstance(original, dict) else ""
        if parsed_name:
            name_val = parsed_name
        names_out.append(name_val)

        # Industry classification
        code = (
            row.get("main_business_line.type")
            or row.get("mainBusinessLine.type")
            or row.get("main_business_line")
            or row.get("mainBusinessLine")
            or ""
        )
        row["industry_raw"] = code
        industries.append(code)

    df["full_address"] = [
        clean_address(street, post, city) for street, post, city in zip(streets, posts, cities)
    ]
    df["business_id"] = business_ids
    df["name"] = names_out
    df["industry_raw"] = [rows_list[i].get("main_business_line", "") if isinstance(rows_list[i], dict) else industries[i] for i in range(len(rows_list))]
    from .industry import classify_industry, load_industry_groups

    groups = industry_groups or load_industry_groups("config/industry_groups.yaml")
    df["industry"] = [classify_industry(code, groups) for code in industries]
    return df


def deduplicate_companies(df: pd.DataFrame) -> pd.DataFrame:
    """Keep one row per business_id; prefer rows with geocode available."""
    if "business_id" not in df.columns:
        return df

    keep_indices = []
    for bid, group in df.groupby("business_id", dropna=False):
        if bid is None or (isinstance(bid, str) and not bid.strip()):
            keep_indices.extend(list(group.index))
            continue
        if len(group) == 1:
            keep_indices.append(group.index[0])
            continue
        with_geo = group.dropna(subset=["lat", "lon"])
        if not with_geo.empty:
            keep_indices.append(with_geo.index[0])
        else:
            keep_indices.append(group.index[0])
    return df.loc[keep_indices].reset_index(drop=True)
