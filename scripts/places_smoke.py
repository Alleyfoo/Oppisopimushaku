#!/usr/bin/env python
"""Quick smoke test for Google Places API (New) text search.

Reads API key from GOOGLE_MAPS_API_KEY and prints basic stats.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from typing import Any

from apprscan.places_api import get_api_key, search_nearby, search_text


def _require_api_key() -> None:
    try:
        get_api_key()
    except RuntimeError:
        print("GOOGLE_MAPS_API_KEY is not set.", file=sys.stderr)
        print("Set it in PowerShell: $env:GOOGLE_MAPS_API_KEY='YOUR_KEY'", file=sys.stderr)
        sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Google Places API (New).")
    parser.add_argument("--query", default="", help="Text query, e.g. 'business in Mantsala Finland'")
    parser.add_argument("--lat", type=float, default=None, help="Center latitude for nearby search.")
    parser.add_argument("--lon", type=float, default=None, help="Center longitude for nearby search.")
    parser.add_argument("--radius-km", type=float, default=2.0, help="Nearby radius in km (default: 2.0).")
    parser.add_argument("--types", default="", help="Comma-separated types for nearby search.")
    parser.add_argument("--region", default="FI", help="Region code (default: FI).")
    parser.add_argument("--language", default="fi", help="Language code (default: fi).")
    parser.add_argument("--max-pages", type=int, default=1, help="Max pages (1-3).")
    parser.add_argument("--sleep-s", type=float, default=2.0, help="Sleep between page tokens.")
    parser.add_argument("--out", default="", help="Optional CSV output path.")
    args = parser.parse_args()

    _require_api_key()
    items: list[dict[str, Any]] = []
    if args.lat is not None and args.lon is not None:
        types = [t.strip() for t in (args.types or "").split(",") if t.strip()]
        if not types:
            types = [
                "store",
                "restaurant",
                "cafe",
                "supermarket",
                "shopping_mall",
                "convenience_store",
                "hardware_store",
                "car_dealer",
                "car_repair",
                "gas_station",
                "bank",
                "pharmacy",
                "hospital",
                "doctor",
                "dentist",
                "school",
                "gym",
                "lodging",
                "beauty_salon",
                "hair_care",
                "real_estate_agency",
                "accounting",
                "lawyer",
                "insurance_agency",
            ]
        seen: set[str] = set()
        for t in types:
            page_items = search_nearby(
                args.lat,
                args.lon,
                args.radius_km * 1000.0,
                included_type=t,
                region_code=args.region,
                language_code=args.language,
                max_pages=args.max_pages,
                sleep_s=args.sleep_s,
            )
            for item in page_items:
                pid = item.get("place_id")
                if pid and pid in seen:
                    continue
                if pid:
                    seen.add(pid)
                items.append(item)
    else:
        if not args.query:
            print("Provide --query for text search or --lat/--lon for nearby search.", file=sys.stderr)
            return 2
        items = search_text(
            args.query,
            region_code=args.region,
            language_code=args.language,
            max_pages=args.max_pages,
            sleep_s=args.sleep_s,
        )
    print(f"Results: {len(items)}")
    for i, item in enumerate(items[:10], start=1):
        name = item.get("name") or ""
        addr = item.get("formatted_address") or ""
        print(f"{i:>2}. {name} | {addr}")
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["place_id", "name", "formatted_address", "lat", "lon", "types", "website", "business_status"]
            )
            for item in items:
                writer.writerow(
                    [
                        item.get("place_id"),
                        item.get("name"),
                        item.get("formatted_address"),
                        item.get("lat"),
                        item.get("lon"),
                        ";".join(item.get("types") or []),
                        item.get("website"),
                        item.get("business_status"),
                    ]
                )
        print(f"Wrote CSV: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
