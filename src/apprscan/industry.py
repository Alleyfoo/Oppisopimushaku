"""Industry grouping (NACE/TOL prefixes) utilities."""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Dict, List


def load_industry_groups(path: str | Path | None) -> Dict[str, List[str]]:
    if path is None:
        return {"other": []}
    path = Path(path)
    if not path.exists():
        return {"other": []}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"other": []}
        result: Dict[str, List[str]] = {}
        for k, v in data.items():
            if isinstance(v, list):
                result[k] = v
            elif isinstance(v, dict):
                # Support {prefixes: [...]} format
                result[k] = v.get("prefixes") or []
            else:
                result[k] = []
        return result
    except Exception:
        return {"other": []}


def _normalize_code(code: str) -> str:
    return "".join(ch for ch in str(code or "") if ch.isdigit())


def classify_industry(code: str, groups: Dict[str, List[str]]) -> str:
    norm = _normalize_code(code)
    if not norm:
        return "other"
    best_group = "other"
    best_len = 0
    for group_name, prefixes in groups.items():
        for pref in prefixes:
            pref_norm = _normalize_code(pref)
            if pref_norm and norm.startswith(pref_norm):
                if len(pref_norm) > best_len:
                    best_len = len(pref_norm)
                    best_group = group_name
    return best_group
