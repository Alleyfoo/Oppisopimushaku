#!/usr/bin/env python
"""Probe company websites for liveness — a quick "is this a real, active company"
signal. No LLM needed (that's analyze_websites.py).

Many PRH / discovered URLs are dead, parked, or placeholder pages. This fetches
each homepage and classifies ``website_status``:

  live        — reachable 2xx page with real content
  parked      — reachable, but a domain-parking / for-sale / placeholder page
  unreachable — DNS/connection/timeout error, or a 4xx/5xx response
  (blank)     — the company has no website at all

Results are cached in ``data/website_health.sqlite`` (resumable) and written as
``website_status`` (+ ``website_http``) into ``out/companies.csv`` in place.
Probes run concurrently; it is polite (short timeout, identifies itself).
"""

from __future__ import annotations

import argparse
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = _ROOT / "out" / "companies.csv"
CACHE_PATH = _ROOT / "data" / "website_health.sqlite"

TIMEOUT = 8.0
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; tyopaikka-tutka-health/1.0)"}

# Hosts a domain redirects to when it's parked / for sale.
PARKING_HOSTS = (
    "sedoparking.com", "parkingcrew.net", "bodis.com", "above.com", "dan.com",
    "afternic.com", "hugedomains.com", "domainmarket.com", "voodoo.com",
    "parklogic.com", "uniregistry.com", "domainnameshop", "porkbun.com/parked",
)
# Text fragments typical of parked / placeholder / default-host pages (FI + EN).
PARKING_TEXT = (
    "verkkotunnus on varattu", "domain for sale", "this domain is for sale",
    "buy this domain", "domain is parked", "this domain is parked", "parked free",
    "sivusto tulossa", "tulossa pian", "under construction", "coming soon",
    "default web page", "apache2 ubuntu default", "it works!", "welcome to nginx",
    "index of /", "this page is used to test", "hostingpalvelu", "sivua ei löydy",
)


def _normalize(url: str) -> str:
    url = str(url).strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def classify(url: str) -> tuple[str, int | None]:
    """Return (website_status, http_status) for a single URL."""
    target = _normalize(url)
    if not target:
        return "unreachable", None
    try:
        with httpx.Client(follow_redirects=True, timeout=TIMEOUT, headers=HEADERS) as c:
            resp = c.get(target)
    except Exception:
        return "unreachable", None
    code = resp.status_code
    if code >= 400:
        return "unreachable", code
    host = (resp.url.host or "").lower()
    body = resp.text or ""
    low = body[:6000].lower()
    if any(h in host for h in PARKING_HOSTS) or any(t in low for t in PARKING_TEXT):
        return "parked", code
    if len(body.strip()) < 200:  # essentially empty page
        return "parked", code
    return "live", code


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS health (business_id TEXT PRIMARY KEY, "
        "url TEXT, status TEXT, http INTEGER, ts TEXT)"
    )
    conn.commit()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=str(CSV_PATH))
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--limit", type=int, default=0, help="Probe only N (sampling/testing)")
    ap.add_argument("--recheck", action="store_true", help="Ignore cache, re-probe all")
    args = ap.parse_args()

    df = pd.read_csv(args.csv, encoding="utf-8-sig")
    best = df["website"].combine_first(df.get("found_website"))
    df["_url"] = best
    has = df[df["_url"].notna() & (df["_url"].astype(str).str.strip() != "")].copy()
    print(f"{len(has)} of {len(df)} companies have a website")

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_PATH)
    _ensure(conn)
    cached = {}
    if not args.recheck:
        for bid, status, http in conn.execute("SELECT business_id, status, http FROM health"):
            cached[str(bid)] = (status, http)

    todo = has[~has["business_id"].astype(str).isin(cached)] if not args.recheck else has
    if args.limit:
        todo = todo.head(args.limit)
    print(f"probing {len(todo)} (cached {len(cached)})…")

    results: dict[str, tuple[str, int | None]] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(classify, row["_url"]): (str(row["business_id"]), row["_url"])
            for _, row in todo.iterrows()
        }
        done = 0
        for fut in as_completed(futs):
            bid, url = futs[fut]
            status, http = fut.result()
            results[bid] = (status, http)
            conn.execute(
                "INSERT OR REPLACE INTO health(business_id, url, status, http, ts) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (bid, str(url), status, http),
            )
            done += 1
            if done % 100 == 0:
                conn.commit()
                print(f"  {done}/{len(todo)}")
        conn.commit()
    conn.close()

    allres = {**cached, **results}
    df["website_status"] = df["business_id"].astype(str).map(lambda b: allres.get(b, (pd.NA, None))[0])
    df["website_http"] = df["business_id"].astype(str).map(lambda b: allres.get(b, (pd.NA, None))[1])
    df = df.drop(columns=["_url"])
    df["website_http"] = pd.to_numeric(df["website_http"], errors="coerce").astype("Int64")

    print("\nwebsite_status breakdown (of companies with a site):")
    print(df.loc[df["website_status"].notna(), "website_status"].value_counts().to_dict())

    if not args.limit:
        df.to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"\nWrote {args.csv}")
    else:
        print("\n[--limit set] CSV not written (sampling run).")


if __name__ == "__main__":
    main()
