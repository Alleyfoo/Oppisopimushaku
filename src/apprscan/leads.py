"""Lead scoring — the single source of truth shared by the dashboard and the
analysis-queue builder (scripts/lead_targets.py), so the leads shown in the app
are exactly the ones picked for LLM analysis.

Score 0-8 per service axis: TOI industry fit + company age (old = likely
modernisation need) + has a website (digitally reachable).
"""

from __future__ import annotations

import pandas as pd

WEBSHOP = {
    "4754": 6, "4763": 6, "4764": 6, "4761": 6, "4762": 6, "4752": 6, "4741": 6,
    "4753": 5, "4759": 5, "4771": 5, "4772": 5, "4775": 5, "4776": 5, "4774": 5,
    "4779": 5, "4781": 5, "4782": 5, "4789": 5, "4791": 5,
    "474": 5, "475": 5, "476": 5, "477": 5, "478": 5, "479": 5,
    "47": 4, "472": 3, "471": 3, "473": 2, "46": 3, "45": 2,
    "10": 2, "11": 2, "13": 2, "14": 2, "20": 2, "22": 2, "23": 2, "24": 2,
    "25": 2, "26": 2, "27": 2, "28": 2, "29": 2, "31": 2, "32": 2,
    "33": 1, "49": 1, "52": 1,
}
PIM = {
    "4684": 5, "4641": 5, "4642": 5, "4664": 5, "4663": 5, "4665": 4, "4649": 4,
    "4646": 4, "464": 3, "463": 3, "46": 2, "47": 2,
    "28": 3, "29": 3, "25": 3, "26": 3, "27": 3, "20": 2, "22": 2,
}
DATA = {
    "52": 4, "49": 4, "64": 3, "65": 3, "33": 3, "71": 3, "86": 3,
    "28": 2, "25": 2, "26": 2, "46": 2, "85": 1, "35": 2,
}

LEAD_AXES = {"Verkkokauppa": "s_webshop", "PIM": "s_pim", "Data": "s_data"}
LEAD_SCORE_MAX = 8


def prefix_score(toi, smap) -> int:
    code = str(toi).split(".")[0].strip() if pd.notna(toi) else ""
    return max((v for k, v in smap.items() if code.startswith(k)), default=0)


def add_lead_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """Add lead scores (s_webshop/s_pim/s_data, 0-8) for sales prioritisation."""
    out = frame.copy()
    out["s_webshop"] = out["toi_code"].apply(lambda t: prefix_score(t, WEBSHOP))
    out["s_pim"] = out["toi_code"].apply(lambda t: prefix_score(t, PIM))
    out["s_data"] = out["toi_code"].apply(lambda t: prefix_score(t, DATA))
    legacy = (
        pd.to_datetime(out["registered"], errors="coerce").dt.year.fillna(2020) <= 2010
    ).astype(int)
    web = out["best_website"] if "best_website" in out.columns else out.get("website")
    has_web = web.notna().astype(int) if web is not None else 0
    for col in ("s_webshop", "s_pim", "s_data"):
        out[col] = out[col] + legacy + has_web
    return out
