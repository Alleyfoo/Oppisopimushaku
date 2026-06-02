#!/usr/bin/env python
"""Enrich PRH registry with geocoordinates (Nominatim) and optionally Google Places.

Two-layer enrichment
--------------------
Layer 1 — Nominatim geocoding (free, permanent cache)
  - Converts PRH `full_address` + municipality to lat/lon.
  - Cache lives in `data/geocode_cache.sqlite` and never expires.
  - Rate-limited to 1 req/s by geopy RateLimiter.

Layer 2 — Google Places (optional, ephemeral, 30-day TTL)
  - Requires GOOGLE_MAPS_API_KEY env var; skipped gracefully if absent.
  - Looks up each geocoded company by name + address via Places text search.
  - Stores only safe fields: place_id, business_status, types, website_places.
  - Cache lives in `out/google_places_cache.sqlite` (gitignored), TTL=30 days.

Distance filter
---------------
After geocoding, only companies within --max-distance-km of their station are kept.
Default: 1.5 km.

Output
------
out/enriched_prh.parquet   — final enriched table (gitignored)

Usage examples
--------------
  # Geocode+filter only (no Google Places)
  python scripts/enrich_google.py

  # With Google Places lookup
  python scripts/enrich_google.py --google

  # Smaller radius
  python scripts/enrich_google.py --max-distance-km 1.0

  # One area only
  python scripts/enrich_google.py --areas Lahti
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import requests as _requests
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from apprscan.distance import haversine_km  # noqa: E402

DEFAULT_REGISTRY = _ROOT / "data" / "prh_registry.parquet"
DEFAULT_STREETS = _ROOT / "data" / "area_streets.json"
DEFAULT_OUT = _ROOT / "out" / "enriched_prh.parquet"
GOOGLE_CACHE_DB = _ROOT / "out" / "google_places_cache.sqlite"
GEOCODE_CACHE = _ROOT / "data" / "postcode_cache.sqlite"

NOMINATIM_URL = "https://photon.komoot.io/api/"
NOMINATIM_DELAY = 0.5  # Photon is more permissive than Nominatim

GOOGLE_TTL_DAYS = 30
GOOGLE_SLEEP_S = 2.0


# ── Postcode geocoding cache (SQLite, permanent) ─────────────────────────────


def _ensure_pc_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS postcode_cache (
            postcode TEXT PRIMARY KEY,
            lat      REAL,
            lon      REAL,
            ts       TEXT
        )
    """)
    conn.commit()


def _pc_cache_get(
    conn: sqlite3.Connection, postcode: str
) -> tuple[float, float] | None:
    cur = conn.execute(
        "SELECT lat, lon FROM postcode_cache WHERE postcode = ?", (postcode,)
    )
    row = cur.fetchone()
    return (float(row[0]), float(row[1])) if row else None


def _pc_cache_set(
    conn: sqlite3.Connection, postcode: str, lat: float, lon: float
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO postcode_cache(postcode, lat, lon, ts) VALUES (?,?,?,datetime('now'))",
        (postcode, lat, lon),
    )
    conn.commit()


def _nominatim_postcode(
    postcode: str, session: _requests.Session, city_fallback: str = ""
) -> tuple[float, float] | None:
    """Query Photon (OSM-backed) for a Finnish postal code. Returns (lat, lon) or None."""
    headers = {"User-Agent": "apprscan-postcode-geocoder/1.0"}
    queries = [f"{postcode} Finland"]
    if city_fallback:
        queries.append(f"{postcode} {city_fallback}")
    for q in queries:
        try:
            resp = session.get(
                NOMINATIM_URL, params={"q": q, "limit": 5}, headers=headers, timeout=15
            )
            resp.raise_for_status()
            features = resp.json().get("features", [])
            # Keep only results within Finland's bounding box
            for feat in features:
                coords = feat.get("geometry", {}).get("coordinates", [])
                if len(coords) >= 2:
                    lon, lat = float(coords[0]), float(coords[1])
                    if 19.0 < lon < 32.0 and 59.0 < lat < 71.0:
                        return lat, lon
        except Exception:
            pass
        if len(queries) > 1:
            time.sleep(NOMINATIM_DELAY)
    return None


def geocode_postcodes(
    postcodes: list[str],
    cache_path: Path,
    city_by_postcode: dict[str, str] | None = None,
) -> dict[str, tuple[float | None, float | None]]:
    """Return {postcode: (lat, lon)} for each code; fetches uncached ones from Photon."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cache_path)
    _ensure_pc_db(conn)

    result: dict[str, tuple[float | None, float | None]] = {}
    to_fetch = []
    for pc in postcodes:
        cached = _pc_cache_get(conn, pc)
        if cached:
            result[pc] = cached
        else:
            to_fetch.append(pc)

    if to_fetch:
        session = _requests.Session()
        for i, pc in enumerate(to_fetch):
            if i > 0:
                time.sleep(NOMINATIM_DELAY)
            city = (city_by_postcode or {}).get(pc, "")
            coords = _nominatim_postcode(pc, session, city_fallback=city)
            if coords:
                _pc_cache_set(conn, pc, coords[0], coords[1])
                result[pc] = coords
            else:
                result[pc] = (None, None)

    conn.close()
    return result


# ── Google Places cache (SQLite, TTL-based) ──────────────────────────────────


def _ensure_google_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS places_cache (
            business_id     TEXT PRIMARY KEY,
            place_id        TEXT,
            business_status TEXT,
            types           TEXT,
            website_places  TEXT,
            fetched_ts      TEXT
        )
    """)
    conn.commit()


def _google_cache_get(
    conn: sqlite3.Connection, business_id: str, ttl_days: int
) -> dict | None:
    cur = conn.execute(
        """
        SELECT place_id, business_status, types, website_places, fetched_ts
        FROM places_cache
        WHERE business_id = ?
          AND datetime(fetched_ts) > datetime('now', ?)
        """,
        (business_id, f"-{ttl_days} days"),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "place_id": row[0],
        "business_status": row[1],
        "types": row[2],
        "website_places": row[3],
    }


def _google_cache_set(
    conn: sqlite3.Connection,
    business_id: str,
    place_id: str,
    business_status: str,
    types: str,
    website_places: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO places_cache
            (business_id, place_id, business_status, types, website_places, fetched_ts)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        """,
        (business_id, place_id, business_status, types, website_places),
    )
    conn.commit()


def _purge_google_cache(conn: sqlite3.Connection, ttl_days: int) -> int:
    cur = conn.execute(
        "DELETE FROM places_cache WHERE datetime(fetched_ts) <= datetime('now', ?)",
        (f"-{ttl_days} days",),
    )
    conn.commit()
    return cur.rowcount


def _google_lookup(name: str, full_address: str, api_key: str) -> dict[str, Any]:
    """Look up one company via Places text search. Returns safe fields only."""
    from apprscan.places_api import search_text  # deferred import — only if Google used

    query = f"{name}, {full_address}"
    results = search_text(
        query,
        api_key=api_key,
        page_size=1,
        max_pages=1,
        sleep_s=0.0,
    )
    if not results:
        return {}
    place = results[0]
    return {
        "place_id": place.get("place_id") or "",
        "business_status": place.get("business_status") or "",
        "types": json.dumps(place.get("types") or [], ensure_ascii=False),
        "website_places": place.get("website") or "",
    }


# ── Municipality helper ───────────────────────────────────────────────────────


def _load_municipality_map(streets_path: Path) -> dict[str, str]:
    """Return {station_label: municipality_name}."""
    data = json.loads(streets_path.read_text(encoding="utf-8"))
    return {entry["label"]: entry["municipality"] for entry in data}


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich PRH registry with geocoords + optional Google Places."
    )
    parser.add_argument(
        "--registry", default=str(DEFAULT_REGISTRY), help="Input parquet path"
    )
    parser.add_argument("--streets-file", default=str(DEFAULT_STREETS))
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output parquet path")
    parser.add_argument(
        "--max-distance-km",
        type=float,
        default=1.5,
        help="Keep companies within this radius",
    )
    parser.add_argument(
        "--geocode-buffer-km",
        type=float,
        default=0.5,
        help="Extra buffer added to distance filter to account for postcode-centroid imprecision (default: 0.5)",
    )
    parser.add_argument(
        "--google",
        action="store_true",
        help="Enrich with Google Places API (requires GOOGLE_MAPS_API_KEY)",
    )
    parser.add_argument("--google-ttl-days", type=int, default=GOOGLE_TTL_DAYS)
    parser.add_argument(
        "--areas", nargs="*", default=None, help="Filter to specific area labels"
    )
    parser.add_argument(
        "--no-filter-passive",
        action="store_true",
        help="Disable default filter that removes housing companies (Asunto Oy, Kiinteistö Oy) and TOI 6820x",
    )
    args = parser.parse_args()

    registry_path = Path(args.registry)
    if not registry_path.exists():
        print(f"ERROR: registry not found: {registry_path}")
        print("  Run: python scripts/fetch_prh_area.py --out data/prh_registry.parquet")
        sys.exit(1)

    df = pd.read_parquet(registry_path)
    if args.areas:
        df = df[df["nearest_station"].isin(args.areas)].copy()
    print(f"Loaded {len(df)} companies from registry.")

    muni_map = _load_municipality_map(Path(args.streets_file))

    # ── Layer 1: Nominatim geocoding (by postcode centroid) ──────────────────
    # Geocode each *unique postcode* once rather than every address individually.
    # Finnish urban postcodes cover ~200-500m, well within our 1.5 km filter.
    print("\n[Geocoding via Nominatim — postcode centroids]")

    def _extract_postcode(full_address: str) -> str:
        import re

        m = re.search(r"\b(\d{5})\b", str(full_address or ""))
        return m.group(1) if m else ""

    df = df.copy()
    df["_postcode"] = df["full_address"].apply(_extract_postcode)

    unique_postcodes = [pc for pc in df["_postcode"].unique() if pc]
    print(f"  {len(unique_postcodes)} unique postcodes across {len(df)} companies")

    # Build city hint per postcode from the nearest_station → municipality mapping
    city_by_postcode: dict[str, str] = {}
    for pc in unique_postcodes:
        # Find which station/municipality this postcode appears under most
        pc_rows = df[df["_postcode"] == pc]
        if not pc_rows.empty:
            station = pc_rows["nearest_station"].mode().iloc[0]
            city_by_postcode[pc] = muni_map.get(station, "")

    coords_map = geocode_postcodes(
        unique_postcodes, GEOCODE_CACHE, city_by_postcode=city_by_postcode
    )

    cached_count = sum(1 for v in coords_map.values() if v[0] is not None)
    fail_count = sum(1 for v in coords_map.values() if v[0] is None)
    print(
        f"  Resolved: {cached_count}/{len(unique_postcodes)} postcodes (failed: {fail_count})"
    )

    df["lat"] = df["_postcode"].map(lambda pc: coords_map.get(pc, (None, None))[0])
    df["lon"] = df["_postcode"].map(lambda pc: coords_map.get(pc, (None, None))[1])
    df["geocode_source"] = df["_postcode"].apply(
        lambda pc: (
            "postcode_centroid"
            if coords_map.get(pc, (None, None))[0] is not None
            else "failed"
        )
    )
    df = df.drop(columns=["_postcode"])

    total_geo = len(df)
    df = df.dropna(subset=["lat", "lon"])
    print(f"  Geocoded: {len(df)}/{total_geo} (failed/skipped: {total_geo - len(df)})")

    # ── Distance filter ───────────────────────────────────────────────────────
    effective_km = args.max_distance_km + args.geocode_buffer_km
    print(
        f"\n[Distance filter: ≤{args.max_distance_km} km + {args.geocode_buffer_km} km buffer = {effective_km} km]"
    )
    df["distance_km"] = df.apply(
        lambda r: haversine_km(
            float(r["station_lat"]),
            float(r["station_lon"]),
            float(r["lat"]),
            float(r["lon"]),
        ),
        axis=1,
    )
    before = len(df)
    df = df[df["distance_km"] <= effective_km].copy()
    print(f"  Kept {len(df)}/{before} companies within {effective_km} km")
    if df.empty:
        print("  Nothing to enrich. Exiting.")
        sys.exit(0)
    print("\nCounts per area after filter:")
    print(df.groupby("nearest_station").size().to_string())

    # ── Passive company filter (default on) ───────────────────────────────────
    if not args.no_filter_passive:
        import re as _re

        _PASSIVE_NAME = _re.compile(
            r"(?i)^(asunto[\s\-]?oy|as\.?\s*oy\b|asunto-osakeyhti|"
            r"kiinteist[oö][\s\-]?oy|keskin[aä]inen kiinteist|"
            r"kiinteist[oö]osakeyhti)",
        )
        _PASSIVE_TOI = {"68201", "68202"}
        name_passive = df["name"].str.match(_PASSIVE_NAME, na=False)
        toi_passive = df["mainBusinessLine.type"].astype(str).isin(_PASSIVE_TOI)
        before_p = len(df)
        df = df[~(name_passive | toi_passive)].copy()
        print(
            f"\n[Passive filter] Removed {before_p - len(df)} housing/shell companies "
            f"({before_p - len(df)} Asunto Oy / Kiinteistö Oy / TOI 6820x). "
            f"Remaining: {len(df)}"
        )
        print("\nCounts per area after passive filter:")
        print(df.groupby("nearest_station").size().to_string())

    # ── Layer 2: Google Places (optional) ─────────────────────────────────────
    if args.google:
        api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
        if not api_key:
            print(
                "\nWARNING: --google requested but GOOGLE_MAPS_API_KEY not set. Skipping Google enrichment."
            )
        else:
            print(f"\n[Google Places enrichment — TTL {args.google_ttl_days} days]")
            GOOGLE_CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
            gconn = sqlite3.connect(GOOGLE_CACHE_DB)
            _ensure_google_db(gconn)
            purged = _purge_google_cache(gconn, args.google_ttl_days)
            if purged:
                print(f"  Purged {purged} expired Google cache entries.")

            place_ids, statuses, types_list, websites_places = [], [], [], []
            g_hit = g_miss = g_fail = 0

            for idx, (_, row) in enumerate(df.iterrows()):
                bid = str(row.get("business_id") or "")
                cached_entry = _google_cache_get(gconn, bid, args.google_ttl_days)

                if cached_entry:
                    place_ids.append(cached_entry["place_id"])
                    statuses.append(cached_entry["business_status"])
                    types_list.append(cached_entry["types"])
                    websites_places.append(cached_entry["website_places"])
                    g_hit += 1
                else:
                    try:
                        result = _google_lookup(
                            str(row.get("name") or ""),
                            str(row.get("full_address") or ""),
                            api_key,
                        )
                        pid = result.get("place_id", "")
                        status = result.get("business_status", "")
                        types_str = result.get("types", "[]")
                        web = result.get("website_places", "")
                        _google_cache_set(gconn, bid, pid, status, types_str, web)
                        place_ids.append(pid)
                        statuses.append(status)
                        types_list.append(types_str)
                        websites_places.append(web)
                        g_miss += 1
                    except Exception as exc:
                        place_ids.append("")
                        statuses.append("")
                        types_list.append("[]")
                        websites_places.append("")
                        g_fail += 1
                        if g_fail <= 5:
                            print(f"  Google lookup failed for {bid}: {exc}")

                    time.sleep(GOOGLE_SLEEP_S)

                if (idx + 1) % 50 == 0:
                    print(
                        f"  {idx + 1}/{len(df)}  cache={g_hit}  new={g_miss}  fail={g_fail}"
                    )

            gconn.close()
            df["place_id"] = place_ids
            df["business_status"] = statuses
            df["types"] = types_list
            df["website_places"] = websites_places
            df["google_fetched"] = pd.Timestamp.utcnow().isoformat()
            print(f"  Done — cache hits: {g_hit}, new: {g_miss}, failed: {g_fail}")

    # ── Write output ──────────────────────────────────────────────────────────
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Drop raw PRH blob columns that are not needed downstream
    drop_cols = [
        c
        for c in [
            "names",
            "companyForms",
            "companySituations",
            "registeredEntries",
            "addresses",
            "tradeRegisterStatus",
            "registeredEntries",
        ]
        if c in df.columns
    ]
    df = df.drop(columns=drop_cols)

    df.to_parquet(out_path, index=False)
    print(f"\nSaved {len(df)} enriched companies to {out_path}")


if __name__ == "__main__":
    main()
