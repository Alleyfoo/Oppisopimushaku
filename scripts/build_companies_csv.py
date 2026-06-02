#!/usr/bin/env python
"""Build out/companies.csv from the enriched PRH parquet.

This is the projection/rename step that turns enrich_google.py's
`out/enriched_prh.parquet` (raw PRH column names) into the dashboard-facing
`out/companies.csv` schema. It was previously done by hand / an uncommitted
script; committing it makes the pipeline reproducible end to end:

    discover_streets.py -> fetch_prh_area.py -> enrich_google.py
        -> build_companies_csv.py -> discover_websites.py -> geocode_streets.py

`found_website` (added by discover_websites.py) and `geocode_quality` (added by
geocode_streets.py) are intentionally not produced here.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = _ROOT / "out" / "enriched_prh.parquet"
DEFAULT_OUT = _ROOT / "out" / "companies.csv"

# PRH languageCode: 1 = Finnish, 2 = Swedish, 3 = English.
FINNISH, ENGLISH = "1", "3"


def _finnish_description(descriptions) -> str:
    """Pick the Finnish business-line description, falling back to any present."""
    if not isinstance(descriptions, (list, tuple)) or len(descriptions) == 0:
        return ""
    by_lang = {}
    for d in descriptions:
        if isinstance(d, dict) and d.get("description"):
            by_lang[str(d.get("languageCode"))] = d["description"]
    for lang in (FINNISH, ENGLISH):
        if lang in by_lang:
            return by_lang[lang]
    return next(iter(by_lang.values()), "")


def build(enriched: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["name"] = enriched["name"]
    out["business_id"] = enriched["business_id"]
    out["industry"] = enriched["industry"]
    out["toi_code"] = enriched["mainBusinessLine.type"]
    out["toi_description"] = enriched["mainBusinessLine.descriptions"].apply(_finnish_description)
    out["nearest_station"] = enriched["nearest_station"]
    out["distance_km"] = pd.to_numeric(enriched["distance_km"], errors="coerce").round(2)
    out["address"] = enriched["full_address"]
    out["website"] = enriched["website.url"]
    out["status"] = pd.to_numeric(enriched["status"], errors="coerce").astype("Int64")
    out["registered"] = enriched["registrationDate"]
    out["lat"] = enriched["lat"]
    out["lon"] = enriched["lon"]
    # De-duplicate to one row per company, keeping the nearest assignment.
    out = (
        out.dropna(subset=["business_id"])
        .sort_values(["business_id", "distance_km"])
        .drop_duplicates("business_id", keep="first")
        .reset_index(drop=True)
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="inp", default=str(DEFAULT_IN), help="enriched parquet")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="companies.csv output")
    args = ap.parse_args()

    enriched = pd.read_parquet(args.inp)
    df = build(enriched)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"Wrote {len(df)} companies to {args.out}")
    print("Per station:", df.groupby("nearest_station").size().to_dict())


if __name__ == "__main__":
    main()
