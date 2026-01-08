#!/usr/bin/env python
"""Convert Google Places CSV exports into a master.xlsx for apprscan.

Usage example:
  python scripts/places_to_master.py ^
    --station "Mantsala,60.6333,25.3170,out/places_mantsala.csv" ^
    --station "Lahti,60.9836,25.6577,out/places_lahti.csv" ^
    --out out/master_places.xlsx
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from apprscan.distance import haversine_km


def _parse_station(spec: str) -> dict[str, Any]:
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 4:
        raise ValueError(f"Invalid --station spec: {spec}")
    name, lat_s, lon_s, path = parts
    return {
        "name": name,
        "lat": float(lat_s),
        "lon": float(lon_s),
        "path": Path(path),
    }


def _parse_city(formatted_address: str) -> tuple[str, str, str]:
    if not formatted_address:
        return "", "", ""
    parts = [p.strip() for p in formatted_address.split(",") if p.strip()]
    if not parts:
        return "", "", ""
    country = parts[-1].lower()
    city_part = parts[-2] if len(parts) >= 2 and country in {"finland", "suomi"} else parts[-1]
    tokens = city_part.split()
    post_code = tokens[0] if tokens and tokens[0].isdigit() else ""
    city = " ".join(tokens[1:]) if post_code and len(tokens) > 1 else city_part
    street = parts[0] if parts else ""
    return street, post_code, city


def _load_places_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in ["place_id", "name", "formatted_address", "lat", "lon"] if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing columns: {', '.join(missing)}")
    return df


def build_master(stations: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for st in stations:
        df = _load_places_csv(st["path"])
        for _, row in df.iterrows():
            street, post_code, city = _parse_city(str(row.get("formatted_address") or ""))
            lat = row.get("lat")
            lon = row.get("lon")
            dist = None
            try:
                dist = haversine_km(float(st["lat"]), float(st["lon"]), float(lat), float(lon))
            except Exception:
                dist = None
            rows.append(
                {
                    "business_id": str(row.get("place_id") or "").strip(),
                    "name": row.get("name"),
                    "full_address": row.get("formatted_address"),
                    "street": street,
                    "post_code": post_code,
                    "city": city,
                    "_source_city": city,
                    "lat": lat,
                    "lon": lon,
                    "nearest_station": st["name"],
                    "distance_km": dist,
                    "website.url": row.get("website"),
                    "company_domain": "",
                    "score": 0,
                    "score_reasons": "",
                    "excluded_reason": "",
                    "status": "neutral",
                    "hide_flag": False,
                    "industry_raw": "",
                    "industry": "other",
                    "main_business_line": "",
                    "company_form": "",
                    "recruiting_active": False,
                    "job_count_total": 0,
                    "job_count_new_since_last": 0,
                    "tags": "",
                    "source": "google_places_new",
                }
            )
    master = pd.DataFrame(rows)
    if not master.empty:
        master = master[master["business_id"].astype(str).str.strip() != ""]
        if not master.empty:
            master["distance_km"] = pd.to_numeric(master["distance_km"], errors="coerce")
            master = master.sort_values(["business_id", "distance_km"]).drop_duplicates("business_id", keep="first")
    return master.reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build master.xlsx from Places CSV exports.")
    parser.add_argument(
        "--station",
        action="append",
        default=[],
        help="Station spec: Name,lat,lon,csv_path (repeatable).",
    )
    parser.add_argument("--out", required=True, help="Output master xlsx.")
    args = parser.parse_args()

    if not args.station:
        print("Provide at least one --station spec.")
        return 2

    stations = [_parse_station(s) for s in args.station]
    master = build_master(stations)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        master.to_excel(writer, sheet_name="Shortlist", index=False)
        pd.DataFrame(columns=master.columns).to_excel(writer, sheet_name="Excluded", index=False)
    print(f"Wrote master: {out_path} rows={len(master)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
