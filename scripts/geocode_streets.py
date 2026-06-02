#!/usr/bin/env python
"""Upgrade out/companies.csv from postcode-centroid to street-level coordinates.

The PRH addresses are `street, postcode` (no house numbers). The original
pipeline geocoded one point per *postcode*, which collapsed every company in an
area onto a single coordinate (e.g. all 642 Kerava companies shared one point),
so `distance_km` was an area centroid rather than a per-company value.

This script re-geocodes each unique (street, postcode) via Photon — biased
toward the company's station and filtered to results whose street name actually
matches — then recomputes `distance_km` against the station. Companies spread
across their real streets; distances finally vary per company. Without house
numbers this is street-centroid, not door-exact, but far better than per-area.

Runs in place on the committed CSV (like analyze_websites.py / discover_websites.py)
and caches every lookup permanently in data/street_cache.sqlite, so re-runs are
free and offline.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests

from apprscan.distance import haversine_km
from apprscan.transit import STATION_COORDS as _RAIL_COORDS

_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = _ROOT / "out" / "companies.csv"
CACHE_PATH = _ROOT / "data" / "street_cache.sqlite"

PHOTON_URL = "https://photon.komoot.io/api/"
PHOTON_DELAY = 0.5
FINLAND_BBOX = (19.0, 32.0, 59.0, 71.0)  # lon_min, lon_max, lat_min, lat_max

# Station coordinates: single source of truth is apprscan.transit, so the
# distance anchor matches the rail model and the dashboard markers exactly.
STATION_COORDS = {k: _RAIL_COORDS[k] for k in ("Lahti", "Kerava", "Savio", "Pasila")}

# Municipality to use in the geocode query (Savio is a district of Kerava,
# Pasila of Helsinki).
CITY_BY_STATION = {
    "Lahti": "Lahti",
    "Kerava": "Kerava",
    "Savio": "Kerava",
    "Pasila": "Helsinki",
}

# A street geocode farther than this from its station is treated as a bad match
# (likely a same-named street elsewhere) and falls back to the existing point.
MAX_PLAUSIBLE_KM = 8.0


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum())


def _parse_address(address: str) -> tuple[str, str]:
    """Return (street, postcode) from an `address` like 'Jukolantie, 04200'."""
    a = str(address or "")
    street = a.split(",")[0].strip()
    m = re.search(r"\b(\d{5})\b", a)
    return street, (m.group(1) if m else "")


def _ensure_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS street_cache (
            key     TEXT PRIMARY KEY,
            lat     REAL,
            lon     REAL,
            matched INTEGER,
            ts      TEXT
        )
        """
    )
    conn.commit()


def _cache_get(conn, key):
    row = conn.execute(
        "SELECT lat, lon, matched FROM street_cache WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    lat = None if row[0] is None else float(row[0])
    lon = None if row[1] is None else float(row[1])
    return (lat, lon, bool(row[2]))


def _cache_set(conn, key, lat, lon, matched):
    conn.execute(
        "INSERT OR REPLACE INTO street_cache(key, lat, lon, matched, ts) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (key, lat, lon, 1 if matched else 0),
    )
    conn.commit()


def _photon_street(
    street: str, postcode: str, city: str, station: tuple[float, float],
    session: requests.Session,
) -> tuple[float | None, float | None, bool]:
    """Geocode a street, biased to the station. Returns (lat, lon, matched)."""
    slat, slon = station
    queries = [f"{street} {postcode} {city}", f"{street}, {city}", f"{street} {postcode}"]
    target = _norm(street)
    best = None
    best_score = -1e9
    for q in queries:
        try:
            resp = session.get(
                PHOTON_URL,
                params={"q": q, "limit": 10, "lat": slat, "lon": slon},
                headers={"User-Agent": "apprscan-street-geocoder/1.0"},
                timeout=15,
            )
            resp.raise_for_status()
            features = resp.json().get("features", [])
        except Exception:
            features = []
        for feat in features:
            coords = feat.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            if not (FINLAND_BBOX[0] < lon < FINLAND_BBOX[1] and FINLAND_BBOX[2] < lat < FINLAND_BBOX[3]):
                continue
            props = feat.get("properties", {})
            matched = target in (_norm(props.get("street", "")), _norm(props.get("name", "")))
            dist = haversine_km(slat, slon, lat, lon)
            # Prefer a true street-name match, then proximity to the station.
            score = (100 if matched else 0) - dist
            if score > best_score:
                best_score = score
                best = (lat, lon, matched, dist)
        if best is not None and best[2]:
            break  # a matched result is good enough; stop trying weaker queries
        time.sleep(PHOTON_DELAY)
    if best is None:
        return None, None, False
    lat, lon, matched, dist = best
    # Reject implausibly far "matches" (same street name in another town).
    if dist > MAX_PLAUSIBLE_KM:
        return None, None, False
    return lat, lon, matched


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=str(CSV_PATH), help="companies.csv path (in place)")
    ap.add_argument("--limit-station", default=None, help="Only process one station (e.g. Kerava) — for validation")
    ap.add_argument("--dry-run", action="store_true", help="Do not write the CSV; just report")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    print(f"Loaded {len(df)} companies from {csv_path}")

    work = df
    if args.limit_station:
        work = df[df["nearest_station"] == args.limit_station]
        print(f"Limiting to station {args.limit_station}: {len(work)} companies")

    parsed = work["address"].apply(_parse_address)
    work = work.assign(
        _street=[p[0] for p in parsed],
        _postcode=[p[1] for p in parsed],
    )
    # Unique (street, postcode, station) combos to minimise lookups.
    combos = (
        work[["_street", "_postcode", "nearest_station"]]
        .drop_duplicates()
        .values.tolist()
    )
    combos = [c for c in combos if c[0] and c[2] in STATION_COORDS]
    print(f"{len(combos)} unique (street, postcode, station) combos to resolve")

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_PATH)
    _ensure_db(conn)
    session = requests.Session()

    resolved: dict[tuple[str, str, str], tuple[float | None, float | None, bool]] = {}
    n_fetch = n_cache = 0
    for i, (street, postcode, station) in enumerate(combos):
        key = f"{station}|{postcode}|{_norm(street)}"
        cached = _cache_get(conn, key)
        if cached is not None:
            resolved[(street, postcode, station)] = cached
            n_cache += 1
            continue
        lat, lon, matched = _photon_street(
            street, postcode, CITY_BY_STATION.get(station, station),
            STATION_COORDS[station], session,
        )
        _cache_set(conn, key, lat, lon, matched)
        resolved[(street, postcode, station)] = (lat, lon, matched)
        n_fetch += 1
        if n_fetch % 25 == 0:
            print(f"  fetched {n_fetch} (cache hits {n_cache}) ...")
        time.sleep(PHOTON_DELAY)
    conn.close()
    print(f"Resolved {len(resolved)} combos (fetched {n_fetch}, cached {n_cache})")

    # Apply to every company; keep existing point when geocoding failed.
    new_lat, new_lon, new_dist, quality = [], [], [], []
    matched_n = fallback_n = 0
    for _, row in work.iterrows():
        station = row["nearest_station"]
        key = (row["_street"], row["_postcode"], station)
        res = resolved.get(key)
        if res and res[0] is not None and station in STATION_COORDS:
            slat, slon = STATION_COORDS[station]
            lat, lon = res[0], res[1]
            new_lat.append(lat)
            new_lon.append(lon)
            new_dist.append(round(haversine_km(slat, slon, lat, lon), 3))
            quality.append("street_match" if res[2] else "street_near")
            matched_n += 1
        else:
            new_lat.append(row["lat"])
            new_lon.append(row["lon"])
            new_dist.append(row["distance_km"])
            quality.append("postcode_fallback")
            fallback_n += 1

    work_idx = work.index
    df.loc[work_idx, "lat"] = new_lat
    df.loc[work_idx, "lon"] = new_lon
    df.loc[work_idx, "distance_km"] = [round(float(d), 3) if pd.notna(d) else d for d in new_dist]
    if "geocode_quality" not in df.columns:
        df["geocode_quality"] = pd.NA
    df.loc[work_idx, "geocode_quality"] = quality

    print(f"\nStreet-level: {matched_n} companies · fallback: {fallback_n}")
    print("\nPer-station unique coordinates AFTER:")
    for st, sub in df.loc[work_idx].groupby("nearest_station"):
        print(
            f"  {st:8s} n={len(sub):5d}  unique_coords={sub.drop_duplicates(['lat','lon']).shape[0]:4d}  "
            f"dist[min/median/max]={sub['distance_km'].min():.2f}/{sub['distance_km'].median():.2f}/{sub['distance_km'].max():.2f}"
        )

    if args.dry_run:
        print("\n[dry-run] CSV not written.")
        return
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\nWrote {csv_path}")


if __name__ == "__main__":
    main()
