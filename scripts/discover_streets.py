#!/usr/bin/env python
"""Discover street names within a radius of each target station using OpenStreetMap Overpass API.

Outputs a YAML-friendly summary of unique street names per area, ready
to be copied into the area config or used directly as PRH location queries.

Usage:
    python scripts/discover_streets.py
    python scripts/discover_streets.py --radius-m 1500 --out data/area_streets.json
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

import requests

OVERPASS_MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# Target station areas: (label, lat, lon, municipality_for_PRH)
STATIONS = [
    {"label": "Lahti", "lat": 60.9836, "lon": 25.6553, "municipality": "Lahti"},
    {"label": "Kerava", "lat": 60.4032, "lon": 25.0985, "municipality": "Kerava"},
    {"label": "Savio", "lat": 60.3839, "lon": 25.0861, "municipality": "Kerava"},
    {"label": "Pasila", "lat": 60.1994, "lon": 24.9338, "municipality": "Helsinki"},
    {"label": "Tikkurila", "lat": 60.2929, "lon": 25.0452, "municipality": "Vantaa"},
]


def _overpass_streets(lat: float, lon: float, radius_m: int) -> list[str]:
    """Return sorted unique street names within radius of (lat, lon)."""
    query = (
        f"[out:json][timeout:60];"
        f'way["highway"]["name"](around:{radius_m},{lat},{lon});'
        f"out tags;"
    )
    last_exc: Exception | None = None
    for mirror in OVERPASS_MIRRORS:
        try:
            resp = requests.get(mirror, params={"data": query}, timeout=70)
            resp.raise_for_status()
            data = resp.json()
            names: set[str] = set()
            for element in data.get("elements", []):
                name = element.get("tags", {}).get("name")
                if name:
                    names.add(name)
            return sorted(names)
        except Exception as exc:
            print(f"    [mirror {mirror} failed: {exc}]")
            last_exc = exc
            time.sleep(3)
    raise RuntimeError(f"All mirrors failed. Last error: {last_exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover streets near target stations via Overpass API."
    )
    parser.add_argument(
        "--radius-m",
        type=int,
        default=1500,
        help="Search radius in metres (default: 1500)",
    )
    parser.add_argument("--out", default=None, help="Optional JSON output file path")
    args = parser.parse_args()

    results: list[dict[str, Any]] = []

    for i, st in enumerate(STATIONS):
        if i > 0:
            time.sleep(2)  # be polite to Overpass servers

        print(f"\n{'='*60}")
        print(f"  {st['label']}  ({st['lat']}, {st['lon']})  radius={args.radius_m}m")
        print(f"  PRH municipality: {st['municipality']}")
        print("=" * 60)

        try:
            streets = _overpass_streets(st["lat"], st["lon"], args.radius_m)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            streets = []

        print(f"  {len(streets)} unique street names found:")
        for s in streets:
            print(f"    - {s}")

        results.append(
            {
                "label": st["label"],
                "lat": st["lat"],
                "lon": st["lon"],
                "municipality": st["municipality"],
                "radius_m": args.radius_m,
                "streets": streets,
            }
        )

    if args.out:
        import pathlib

        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nSaved to {args.out}")
    else:
        print("\n\n--- JSON summary ---")
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
