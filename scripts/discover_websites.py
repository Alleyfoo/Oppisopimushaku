#!/usr/bin/env python
"""Discover websites for companies that have none in PRH data.

Strategy
--------
For each company without a known website, search DuckDuckGo for
"<company name> Finland" and pick the first result that:
  - is not a known business directory
  - loosely matches the company name in the domain

Results are cached permanently in data/website_cache.sqlite so the script
can be stopped and resumed without re-searching.

Usage
-----
  python scripts/discover_websites.py [--limit 100] [--sleep 0.6]

  # Refresh only companies added since last run
  python scripts/discover_websites.py --new-only

Output
------
Writes `found_website` column to out/companies.csv in-place.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from ddgs import DDGS

_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = _ROOT / "out" / "companies.csv"
CACHE_PATH = _ROOT / "data" / "website_cache.sqlite"

# Domains to skip — business directories, social media, news sites, aggregators
SKIP_DOMAINS = {
    # Finnish business registries & directories
    "finder.fi",
    "asiakastieto.fi",
    "proff.fi",
    "ytj.fi",
    "kauppalehti.fi",
    "taloussanomat.fi",
    "yrittajat.fi",
    "yritystele.fi",
    "fonecta.fi",
    "yellow.fi",
    "eniro.fi",
    "yritysopas.fi",
    "yrityshaku.fi",
    "ytunnus.fi",
    "b2bsuomi.fi",
    "cylex.fi",
    "yritystieto.fi",
    # International business data
    "cybo.com",
    "northdata.com",
    "dnb.com",
    "rocketreach.co",
    "bloomberg.com",
    "lei.bloomberg.com",
    "opencorporates.com",
    "crunchbase.com",
    "zoominfo.com",
    "companieshouse.gov.uk",
    # Social media
    "linkedin.com",
    "facebook.com",
    "twitter.com",
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    # Review / map sites
    "yelp.com",
    "tripadvisor.com",
    "google.com",
    "google.fi",
    "yandex.com",
    "bing.com",
    "maps.google.com",
    # PR / press
    "cision.com",
    "mb.cision.com",
    "globenewswire.com",
    "businesswire.com",
    # Knowledge bases
    "wikipedia.org",
    "wikidata.org",
    # Finnish news
    "seiska.fi",
    "iltalehti.fi",
    "iltasanomat.fi",
    "hs.fi",
    "yle.fi",
    "mtv.fi",
    # Government
    "prh.fi",
    "vero.fi",
    "te-palvelut.fi",
    # Review / opinion
    "kokemuksia.fi",
    "trustpilot.com",
}

# Noise words to strip when matching company name to domain
_STRIP = re.compile(
    r"\b(oy|ab|oyj|ky|avoin yhtiö|yhtiöt|finland|suomi|group|holding"
    r"|palvelut|services|solutions|technologies|tech|digital)\b",
    re.IGNORECASE,
)


def _name_slug(name: str) -> str:
    """Return a simplified lowercase slug of the company name for matching."""
    name = _STRIP.sub("", name)
    name = re.sub(r"[^a-z0-9]", "", name.lower())
    return name


def _domain_slug(url: str) -> str:
    """Return the domain without www., TLDs stripped."""
    netloc = urlparse(url).netloc.lstrip("www.")
    # strip .fi .com .net etc — first segment only
    return re.sub(r"[^a-z0-9]", "", netloc.split(".")[0].lower())


def _is_plausible(company_name: str, url: str) -> bool:
    """Return True if the URL domain loosely matches the company name."""
    c = _name_slug(company_name)
    d = _domain_slug(url)
    if not c or not d:
        return False
    # Accept if company slug starts with domain or domain starts with company slug (3+ chars)
    min_len = max(3, min(len(c), len(d)) - 1)
    return c[:min_len] == d[:min_len] or d[:min_len] == c[:min_len]


def _search(name: str, ddgs: DDGS, sleep: float) -> str:
    """Return best discovered URL or empty string."""
    query = f"{name} Finland"
    try:
        results = list(ddgs.text(query, max_results=5))
    except Exception:
        return ""
    finally:
        time.sleep(sleep)

    # Only accept results where domain loosely matches company name
    for r in results:
        url = r.get("href", "")
        domain = urlparse(url).netloc.lstrip("www.")
        if any(skip in domain for skip in SKIP_DOMAINS):
            continue
        if _is_plausible(name, url):
            return url

    return ""


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _init_cache(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE IF NOT EXISTS website_search "
        "(business_id TEXT PRIMARY KEY, found_url TEXT, searched_at TEXT)"
    )
    con.commit()
    return con


def _load_cache(con: sqlite3.Connection) -> dict[str, str]:
    rows = con.execute("SELECT business_id, found_url FROM website_search").fetchall()
    return {r[0]: r[1] for r in rows}


def _save(con: sqlite3.Connection, business_id: str, url: str) -> None:
    con.execute(
        "INSERT OR REPLACE INTO website_search (business_id, found_url, searched_at) "
        "VALUES (?, ?, datetime('now'))",
        (business_id, url),
    )
    con.commit()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--limit", type=int, default=0, help="Max companies to search (0=all)"
    )
    ap.add_argument("--sleep", type=float, default=0.7, help="Seconds between searches")
    ap.add_argument(
        "--new-only", action="store_true", help="Only search companies not yet in cache"
    )
    args = ap.parse_args()

    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")

    con = _init_cache(CACHE_PATH)
    cache = _load_cache(con)

    # Companies without a PRH website
    no_web = df[df["website"].isna()].copy()
    print(f"Companies without PRH website: {len(no_web)}")
    print(f"Already in cache: {no_web['business_id'].isin(cache).sum()}")

    if args.new_only:
        no_web = no_web[~no_web["business_id"].isin(cache)]

    if args.limit:
        no_web = no_web.head(args.limit)

    to_search = no_web[~no_web["business_id"].isin(cache)]
    print(f"Will search: {len(to_search)}")

    if len(to_search) == 0:
        print(
            "Nothing to search — all companies are cached. Re-run without --new-only to use cache."
        )
    else:
        with DDGS() as ddgs:
            for i, (_, row) in enumerate(to_search.iterrows(), 1):
                url = _search(row["name"], ddgs, args.sleep)
                _save(con, row["business_id"], url)
                status = "✓" if url else "·"
                if i % 20 == 0 or url:
                    print(
                        f"[{i}/{len(to_search)}] {status} {row['name'][:45]} -> {url or '(not found)'}"
                    )

    # Reload full cache and apply to CSV
    cache = _load_cache(con)
    df["found_website"] = df.apply(
        lambda r: (
            r["website"] if pd.notna(r["website"]) else cache.get(r["business_id"], "")
        ),
        axis=1,
    )
    df["found_website"] = df["found_website"].replace("", pd.NA)

    # Stats
    prh_count = df["website"].notna().sum()
    found_count = df["found_website"].notna().sum()
    print(
        f"\nWebsite coverage: {prh_count} PRH → {found_count} after discovery "
        f"(+{found_count - prh_count}, {100*found_count/len(df):.1f}% total)"
    )

    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    print(f"Saved {CSV_PATH}")
    con.close()


if __name__ == "__main__":
    main()
