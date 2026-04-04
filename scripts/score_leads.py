#!/usr/bin/env python
"""Score companies for digital services lead potential.

Three signal axes
-----------------
webshop   — sells physical products, no/poor online sales channel
pim       — product-catalogue-heavy (many SKUs, several product lines)
data      — data-intensive operations (logistics, finance, manufacturing)

Scoring uses TOI code prefixes + company age (old = legacy modernisation target).
Results saved to out/leads.csv.

Usage
-----
  python scripts/score_leads.py
  python scripts/score_leads.py --top 20 --out out/leads.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
CSV_IN  = _ROOT / "out" / "companies.csv"
CSV_OUT = _ROOT / "out" / "leads.csv"

# ---------------------------------------------------------------------------
# TOI prefix → score maps
# ---------------------------------------------------------------------------

# Which companies are likely to benefit from an e-commerce / web-shop build?
WEBSHOP: dict[str, int] = {
    "47": 4,    # retail — classic B2C shop
    "46": 3,    # wholesale — B2B self-service ordering
    "45": 2,    # motor vehicle parts
    "10": 2, "11": 2, "13": 2, "14": 2,   # food & textile mfg
    "20": 2, "22": 2, "23": 2, "24": 2,   # chemicals, plastics, metals
    "25": 2, "26": 2, "27": 2, "28": 2,   # metal products, electronics, machinery
    "29": 2, "31": 2, "32": 2,             # vehicles, furniture, misc mfg
    "33": 1,    # machine repair — spare-parts shop
    "49": 1, "52": 1,                      # logistics — customer portal / booking
}

# Which companies are likely to have a large product catalogue needing a PIM?
PIM: dict[str, int] = {
    "4684": 5,  # hardware fasteners wholesale (Bufab territory)
    "4641": 5,  # electrical equipment wholesale
    "4642": 5,  # electronic goods wholesale
    "4664": 5,  # other machinery wholesale
    "4663": 5,  # mining/construction machinery wholesale
    "4665": 4,  # furniture / household goods wholesale
    "4649": 4,  # other household goods wholesale
    "4646": 4,  # pharmaceutical/medical wholesale
    "4631": 3,  # fresh food wholesale
    "464":  3,  # general specialty wholesale
    "463":  3,  # food wholesale
    "46":   2,  # wholesale (fallback)
    "47":   2,  # retail
    "28":   3, "29": 3, "25": 3, "26": 3, "27": 3,  # product manufacturers
    "20":   2, "22": 2,                               # process manufacturers
}

# Which companies likely have data they're not fully leveraging?
DATA: dict[str, int] = {
    "52": 4,    # warehousing/storage — inventory & routing analytics
    "49": 4,    # road freight — route optimisation, fleet telematics
    "64": 3,    # finance — risk, portfolio analytics
    "65": 3,    # insurance — pricing, claims analytics
    "33": 3,    # machinery repair — predictive maintenance
    "71": 3,    # engineering/testing — measurement data
    "86": 3,    # health — patient analytics, resource planning
    "28": 2, "25": 2, "26": 2,     # manufacturing — production analytics
    "46": 2,    # wholesale — sales/demand forecasting
    "85": 1,    # education
    "35": 2,    # energy supply
}


def _prefix_score(toi: str | float, score_map: dict[str, int]) -> int:
    """Return the highest-matching prefix score for a TOI code."""
    code = str(toi).split(".")[0].strip() if pd.notna(toi) else ""
    if not code or code == "nan":
        return 0
    best = 0
    for prefix, pts in score_map.items():
        if code.startswith(prefix):
            best = max(best, pts)
    return best


def score(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["s_webshop"] = df["toi_code"].apply(lambda t: _prefix_score(t, WEBSHOP))
    df["s_pim"]     = df["toi_code"].apply(lambda t: _prefix_score(t, PIM))
    df["s_data"]    = df["toi_code"].apply(lambda t: _prefix_score(t, DATA))

    # Bonus: established company (registered ≤ 2010) → +1 on all axes
    reg = pd.to_numeric(df["registered"], errors="coerce").fillna(2020)
    legacy = (reg <= 2010).astype(int)
    df["s_webshop"] += legacy
    df["s_pim"]     += legacy
    df["s_data"]    += legacy

    # Bonus: has a website → already digital-aware → +1
    best_web = df.get("found_website", df.get("website"))
    has_web = (
        best_web.notna() |
        df["website"].notna()
    ).astype(int)
    df["s_webshop"] += has_web
    df["s_pim"]     += has_web
    df["s_data"]    += has_web

    df["score_total"] = df["s_webshop"] + df["s_pim"] + df["s_data"]
    return df


def top_per_axis(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Return a combined frame of top-n per axis, deduplicated."""
    axes = {
        "webshop": "s_webshop",
        "pim":     "s_pim",
        "data":    "s_data",
    }
    frames = []
    for label, col in axes.items():
        sub = (
            df.sort_values(col, ascending=False)
            .head(n)
            .copy()
        )
        sub["lead_type"] = label
        sub["axis_score"] = sub[col]
        frames.append(sub)

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["lead_type", "axis_score"], ascending=[True, False])
    return combined


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--out", default=str(CSV_OUT))
    args = ap.parse_args()

    df = pd.read_csv(CSV_IN, encoding="utf-8-sig")
    df = score(df)

    # Best website column
    if "found_website" in df.columns:
        df["best_website"] = df["website"].combine_first(df["found_website"])
    else:
        df["best_website"] = df["website"]

    SHOW = ["name", "business_id", "toi_code", "toi_description",
            "nearest_station", "distance_km", "best_website",
            "registered", "s_webshop", "s_pim", "s_data", "score_total"]

    print("\n=== TOP OVERALL (by total score) ===")
    top_all = df.sort_values("score_total", ascending=False).head(args.top)
    print(top_all[SHOW].to_string(index=False))

    for label, col, title in [
        ("webshop", "s_webshop",  "WEBSHOP / E-COMMERCE"),
        ("pim",     "s_pim",      "PIM / PRODUCT CATALOGUE"),
        ("data",    "s_data",     "DATA ANALYSIS"),
    ]:
        print(f"\n=== TOP {args.top} — {title} ===")
        sub = df.sort_values(col, ascending=False).head(args.top)
        print(sub[SHOW].to_string(index=False))

    # Save leads CSV with axis scores
    leads = top_per_axis(df, args.top)
    out_cols = ["lead_type", "axis_score", "name", "business_id",
                "toi_code", "toi_description", "nearest_station",
                "distance_km", "best_website", "registered",
                "s_webshop", "s_pim", "s_data"]
    leads[out_cols].to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"\nSaved {len(leads)} leads to {args.out}")


if __name__ == "__main__":
    main()
