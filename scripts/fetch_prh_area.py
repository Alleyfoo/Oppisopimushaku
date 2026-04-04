#!/usr/bin/env python
"""Fetch PRH companies for target station areas and store as a permanent registry.

Strategy
--------
1. Load area_streets.json produced by discover_streets.py to know which streets
   are within radius of each station.
2. Query PRH API by municipality name for each area.
3. Post-filter returned companies so only those whose registered street address
   matches a street in the area list are kept.
4. Write or append to data/prh_registry.parquet (permanent; commitable).

For Helsinki this fetch is large (~100 k pages) so we cap it per area with
--max-pages; run without the cap for a full refresh.

Usage examples
--------------
  # Quick test: max 5 pages per area
  python scripts/fetch_prh_area.py --max-pages 5 --out data/prh_registry.parquet

  # Full fetch for Lahti only
  python scripts/fetch_prh_area.py --areas Lahti --out data/prh_registry.parquet

  # All areas, no page cap (long-running)
  python scripts/fetch_prh_area.py --out data/prh_registry.parquet
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

# ── project root on sys.path so apprscan is importable ──────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from apprscan.normalize import normalize_companies  # noqa: E402
from apprscan.prh_client import fetch_companies  # noqa: E402

DEFAULT_STREETS_FILE = _ROOT / "data" / "area_streets.json"
DEFAULT_OUT = _ROOT / "data" / "prh_registry.parquet"

# Postal-code hints per area label (used in summary output; not yet a query
# param because the public YTJ v3 API only exposes `location` as a filter).
AREA_POSTAL_CODES: dict[str, list[str]] = {
    "Lahti": ["15100", "15110", "15120", "15130", "15140", "15150"],
    "Kerava": ["04200", "04220", "04230"],
    "Savio": ["04220", "04230", "04240"],
    "Pasila": ["00520", "00530", "00580", "00610"],
    "Tikkurila": ["01300", "01370", "01380"],
}


def _load_area_streets(path: Path) -> dict[str, dict]:
    """Return dict keyed by area label with municipality and street set."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, dict] = {}
    for entry in raw:
        label = entry["label"]
        result[label] = {
            "municipality": entry["municipality"],
            "streets_lower": {s.lower() for s in entry["streets"]},
            "lat": entry["lat"],
            "lon": entry["lon"],
        }
    return result


def _street_from_row(row: dict) -> str:
    """Extract normalised street name from a raw PRH company row."""
    # PRH v3 returns nested addresses array
    addresses = row.get("addresses") or []
    if isinstance(addresses, list) and addresses:
        addr = addresses[0]
    elif isinstance(addresses, dict):
        addr = addresses
    else:
        addr = {}
    return str(addr.get("street") or row.get("street") or "").strip().lower()


def _street_base(street_raw: str) -> str:
    """Strip house number suffix so 'Asemakatu 3' matches 'Asemakatu'."""
    return re.sub(r"\s+\d+.*$", "", street_raw).strip()


def fetch_area(
    label: str,
    area: dict,
    max_pages: int = 0,
) -> pd.DataFrame:
    """Fetch and filter PRH companies for one area."""
    municipality = area["municipality"]
    streets_lower = area["streets_lower"]

    print(
        f"\n[{label}]  municipality={municipality}  street set size={len(streets_lower)}"
    )
    raw = fetch_companies(municipality, max_pages=max_pages)
    print(f"  PRH returned {len(raw)} raw rows")

    # Post-filter: keep only companies whose street is in our area set
    kept = []
    for row in raw:
        street_raw = _street_from_row(row)
        base = _street_base(street_raw)
        if base in streets_lower:
            kept.append(row)

    print(f"  After street filter: {len(kept)} companies")

    if not kept:
        return pd.DataFrame()

    df = normalize_companies(kept)
    df["nearest_station"] = label
    df["station_lat"] = area["lat"]
    df["station_lon"] = area["lon"]
    df["prh_fetched"] = pd.Timestamp.utcnow().isoformat()
    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch PRH companies for target station areas."
    )
    parser.add_argument(
        "--areas",
        nargs="*",
        default=None,
        help="Area labels to process (default: all from streets file)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Max pages per area (0 = unlimited; use ≤10 for a quick test)",
    )
    parser.add_argument(
        "--streets-file",
        default=str(DEFAULT_STREETS_FILE),
        help=f"Path to area_streets.json (default: {DEFAULT_STREETS_FILE})",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help=f"Output parquet path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing registry; dedup on business_id",
    )
    args = parser.parse_args()

    streets_path = Path(args.streets_file)
    if not streets_path.exists():
        print(f"ERROR: streets file not found: {streets_path}")
        print("  Run: python scripts/discover_streets.py --out data/area_streets.json")
        sys.exit(1)

    area_map = _load_area_streets(streets_path)
    labels = args.areas if args.areas else list(area_map.keys())
    unknown = [l for l in labels if l not in area_map]
    if unknown:
        print(f"ERROR: unknown area label(s): {unknown}")
        print(f"  Available: {list(area_map.keys())}")
        sys.exit(1)

    frames: list[pd.DataFrame] = []
    for label in labels:
        df = fetch_area(label, area_map[label], max_pages=args.max_pages)
        if not df.empty:
            frames.append(df)

    if not frames:
        print("\nNo data fetched.")
        sys.exit(0)

    new_data = pd.concat(frames, ignore_index=True)

    out_path = Path(args.out)
    if args.append and out_path.exists():
        existing = pd.read_parquet(out_path)
        combined = pd.concat([existing, new_data], ignore_index=True)
        if "business_id" in combined.columns:
            # Keep latest row per business_id (newest prh_fetched wins)
            combined = combined.sort_values("prh_fetched").drop_duplicates(
                subset=["business_id"], keep="last"
            )
        new_data = combined

    out_path.parent.mkdir(parents=True, exist_ok=True)
    new_data.to_parquet(out_path, index=False)
    print(f"\nSaved {len(new_data)} companies to {out_path}")

    # Summary table
    if "nearest_station" in new_data.columns:
        print("\nCounts per area:")
        print(new_data.groupby("nearest_station").size().to_string())


if __name__ == "__main__":
    main()
