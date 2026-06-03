#!/usr/bin/env python
"""Build the curated LLM-analysis queue: the top-N live-website leads per category.

Scoring (reused from apprscan.leads — same as the dashboard) ranks on three axes
(webshop / pim / data). This takes the top N per axis that have a *live* website
(website_status == 'live', from website_health.py) and writes them to
``out/lead_targets.csv`` — a short, high-value list to run the Ollama website
analysis on, instead of all ~8k sites.

Note: the scoring already rewards having a website, so the top leads almost all
have one. Companies whose site simply isn't in the registry (and hasn't been
discovered) rank lower; widen coverage with scripts/discover_websites.py first if
you want more candidates.

Usage
-----
  python scripts/lead_targets.py --top 100
  python scripts/lead_targets.py --top 100 --status any   # include dead sites
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from apprscan.leads import add_lead_scores  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
CSV_IN = _ROOT / "out" / "companies.csv"
CSV_OUT = _ROOT / "out" / "lead_targets.csv"
AXES = {"webshop": "s_webshop", "pim": "s_pim", "data": "s_data"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=100, help="Max leads per category")
    ap.add_argument("--status", default="live", help="Required website_status, or 'any'")
    ap.add_argument("--in", dest="inp", default=str(CSV_IN))
    ap.add_argument("--out", default=str(CSV_OUT))
    args = ap.parse_args()

    df = pd.read_csv(args.inp, encoding="utf-8-sig")
    df["best_website"] = df["website"].combine_first(df.get("found_website"))
    df = add_lead_scores(df)  # same scoring as the dashboard (apprscan.leads)
    has_site = df["best_website"].notna() & (df["best_website"].astype(str).str.strip() != "")
    pool = df[has_site].copy()
    if args.status != "any" and "website_status" in pool.columns:
        pool = pool[pool["website_status"] == args.status]

    frames = []
    for label, col in AXES.items():
        sub = pool.sort_values(col, ascending=False).head(args.top).copy()
        sub["lead_type"] = label
        sub["axis_score"] = sub[col]
        frames.append(sub)
    leads = pd.concat(frames, ignore_index=True)

    cols = [
        c
        for c in [
            "lead_type", "axis_score", "name", "business_id", "toi_code",
            "toi_description", "nearest_station", "dist_km", "distance_km",
            "best_website", "website_status", "registered",
            "s_webshop", "s_pim", "s_data",
        ]
        if c in leads.columns
    ]
    leads[cols].to_csv(args.out, index=False, encoding="utf-8-sig")

    uniq = leads["business_id"].nunique()
    print(f"Wrote {len(leads)} rows ({uniq} unique companies) to {args.out}")
    print("per category:", leads.groupby("lead_type")["business_id"].nunique().to_dict())
    print(
        f"\nNext: run the Ollama analysis on these {uniq} companies "
        "(analyze_websites.py reads out/companies.csv; filter to these business_ids)."
    )


if __name__ == "__main__":
    main()
