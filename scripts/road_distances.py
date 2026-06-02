#!/usr/bin/env python
"""Precompute walking *road* distance from each company to its station.

Straight-line (haversine) distance underestimates the real walk — roads detour
around blocks, rivers and rail lines. This uses the OpenStreetMap walking
network (via OSMnx) to compute the shortest-path distance from each company's
street point to its nearest railway station, and writes ``road_distance_km``
into ``out/companies.csv``.

This is a BUILD-TIME step: OSMnx/OSM downloads happen here, the deployed app only
reads the committed column. OSMnx graph downloads are cached under
``data/osmnx_cache`` and computed distances in ``data/road_distance_cache.sqlite``
(keyed by station + rounded coordinate), so re-runs are cheap and resumable.

Unreachable points (rare, disconnected nodes) fall back to haversine × a detour
factor so every row gets a value.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd

from apprscan.distance import haversine_km
from apprscan.transit import STATION_COORDS as RAIL

_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = _ROOT / "out" / "companies.csv"
CACHE_PATH = _ROOT / "data" / "road_distance_cache.sqlite"
AREAS = ["Lahti", "Kerava", "Savio", "Pasila", "Tikkurila"]
GRAPH_DIST_M = 6000  # covers companies up to ~4.3 km from the station + margin
DETOUR_FALLBACK = 1.35  # haversine × this when the network can't route a point

ox.settings.use_cache = True
ox.settings.cache_folder = str(_ROOT / "data" / "osmnx_cache")


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS road_cache (key TEXT PRIMARY KEY, km REAL)")
    conn.commit()


def _key(station: str, lat: float, lon: float) -> str:
    return f"{station}|{round(float(lat), 6)}|{round(float(lon), 6)}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=str(CSV_PATH))
    ap.add_argument("--only", default=None, help="Process a single station (validation)")
    args = ap.parse_args()

    df = pd.read_csv(args.csv, encoding="utf-8-sig")
    print(f"Loaded {len(df)} companies")
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_PATH)
    _ensure(conn)

    if "road_distance_km" not in df.columns:
        df["road_distance_km"] = pd.NA

    areas = [args.only] if args.only else AREAS
    for area in areas:
        if area not in RAIL:
            print(f"  {area}: not a known station, skipping")
            continue
        sub = df[(df["nearest_station"] == area)].dropna(subset=["lat", "lon"])
        if sub.empty:
            continue
        slat, slon = RAIL[area]
        uniq = sub.drop_duplicates(["lat", "lon"])[["lat", "lon"]]

        # Resolve from cache; only build the graph if something is uncached.
        coord_km: dict[tuple[float, float], float] = {}
        uncached = []
        for lat, lon in uniq.itertuples(index=False):
            row = conn.execute(
                "SELECT km FROM road_cache WHERE key = ?", (_key(area, lat, lon),)
            ).fetchone()
            if row is not None:
                coord_km[(round(lat, 6), round(lon, 6))] = float(row[0])
            else:
                uncached.append((lat, lon))

        if uncached:
            print(f"  {area}: building walk graph ({len(uncached)} new of {len(uniq)} points)…")
            G = ox.graph_from_point((slat, slon), dist=GRAPH_DIST_M, network_type="walk")
            station_node = ox.distance.nearest_nodes(G, X=slon, Y=slat)
            lengths = nx.single_source_dijkstra_path_length(G, station_node, weight="length")
            lats = [p[0] for p in uncached]
            lons = [p[1] for p in uncached]
            nodes = np.atleast_1d(ox.distance.nearest_nodes(G, X=lons, Y=lats)).tolist()
            for (lat, lon), node in zip(uncached, nodes):
                meters = lengths.get(node)
                if meters is None:
                    km = haversine_km(slat, slon, lat, lon) * DETOUR_FALLBACK
                else:
                    km = meters / 1000.0
                coord_km[(round(lat, 6), round(lon, 6))] = km
                conn.execute(
                    "INSERT OR REPLACE INTO road_cache(key, km) VALUES (?, ?)",
                    (_key(area, lat, lon), km),
                )
            conn.commit()

        # Apply to every company in the area by its coordinate.
        mask = (df["nearest_station"] == area) & df["lat"].notna() & df["lon"].notna()
        raw = pd.Series(
            [
                coord_km.get((round(float(la), 6), round(float(lo), 6)), float("nan"))
                for la, lo in zip(df.loc[mask, "lat"], df.loc[mask, "lon"])
            ],
            index=df.loc[mask].index,
            dtype=float,
        )
        # Guard against routing artifacts (isolated nodes / barrier detours):
        # the walk is at least the straight line and at most 2.5× it + 200 m.
        straight = df.loc[mask, "distance_km"].astype(float)
        df.loc[mask, "road_distance_km"] = (
            raw.clip(lower=straight, upper=straight * 2.5 + 0.2).round(3)
        )
        rd = df.loc[mask, "road_distance_km"].astype(float)
        st_ratio = (rd / df.loc[mask, "distance_km"].astype(float)).replace([float("inf")], float("nan"))
        print(
            f"  {area}: road km min/median/max = "
            f"{rd.min():.2f}/{rd.median():.2f}/{rd.max():.2f} · "
            f"avg road/straight ratio = {st_ratio.mean():.2f}"
        )

    conn.close()
    df.to_csv(args.csv, index=False, encoding="utf-8-sig")
    print(f"Wrote {args.csv}")


if __name__ == "__main__":
    main()
