"""Curation overlay helpers for Streamlit editing without touching master snapshots."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

import pandas as pd
import shutil
import json


CURATION_COLUMNS = [
    "business_id",
    "status",
    "hide_flag",
    "note",
    "industry_override",
    "tags_add",
    "tags_remove",
    "updated_at",
    "updated_by",
    "source_master",
]


def _empty_curation_df() -> pd.DataFrame:
    return pd.DataFrame(columns=CURATION_COLUMNS)


def read_master(path: Path | str) -> pd.DataFrame:
    """Read master Excel shortlist; caller chooses sheet."""
    return pd.read_excel(path, sheet_name="Shortlist")


def read_curation(path: Path | str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return _empty_curation_df()
    df = pd.read_csv(p)
    missing = [c for c in CURATION_COLUMNS if c not in df.columns]
    for col in missing:
        df[col] = None
    return df[CURATION_COLUMNS]


def write_curation(df: pd.DataFrame, path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=p.parent, delete=False, newline="") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = Path(tmp.name)
    tmp_path.replace(p)


def write_curation_with_backup(df: pd.DataFrame, path: Path | str, *, batch_id: str | None = None) -> Path | None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if p.exists():
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_path = p.with_name(f"{p.stem}_{timestamp}.csv")
        p.replace(backup_path)
    with tempfile.NamedTemporaryFile("w", dir=p.parent, delete=False, newline="") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = Path(tmp.name)
    tmp_path.replace(p)
    return backup_path


def restore_curation_from_backup(backup_path: Path | str, target_path: Path | str) -> Path | None:
    """Restore curation from backup. Returns safety backup path of previous target."""
    backup_path = Path(backup_path)
    target_path = Path(target_path)
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    safety = None
    if target_path.exists():
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safety = target_path.with_name(f"{target_path.stem}_safety_{timestamp}.csv")
        shutil.copy2(target_path, safety)
    shutil.copy2(backup_path, target_path)
    return safety


def append_audit(event: dict, path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_audit(path: Path | str, limit: int = 100) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    events = []
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    return events[-limit:]


def _split_tags(raw: str | float | None) -> List[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    if isinstance(raw, list):
        parts = raw
    else:
        parts = str(raw).replace(";", ",").split(",")
    return sorted({p.strip().lower() for p in parts if p and p.strip()})


def normalize_tags(raw: str | list | None) -> List[str]:
    """Normalize tags to lowercased, deduped list preserving order of first appearance."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    if isinstance(raw, list):
        items = raw
    else:
        items = str(raw).replace(";", ",").split(",")
    seen = []
    for item in items:
        val = item.strip().lower()
        if val and val not in seen:
            seen.append(val)
    return seen


def validate_master(df: pd.DataFrame) -> None:
    if "business_id" not in df.columns:
        raise ValueError("Master is missing business_id column.")
    if df["business_id"].isna().any() or (df["business_id"].astype(str).str.strip() == "").any():
        raise ValueError("Master has empty business_id values.")
    dupes = df["business_id"].astype(str).value_counts()
    offending = dupes[dupes > 1]
    if not offending.empty:
        examples = ", ".join(offending.index.tolist()[:10])
        raise ValueError(f"Master has duplicate business_id values: {examples}")


@dataclass
class AppliedCuration:
    view: pd.DataFrame
    changed_rows: List[str] = field(default_factory=list)


def apply_curation(master_df: pd.DataFrame, curation_df: pd.DataFrame) -> AppliedCuration:
    """Overlay editable fields onto master; returns view df and list of business_ids with changes."""
    if master_df.empty:
        return AppliedCuration(master_df.copy(), [])

    curation_df = curation_df.copy()
    curation_df["business_id"] = curation_df["business_id"].astype(str)
    master_df = master_df.copy()
    master_df["business_id"] = master_df["business_id"].astype(str)

    merged = master_df.merge(
        curation_df,
        on="business_id",
        how="left",
        suffixes=("", "_cur"),
    )

    def pick(col: str):
        cur_col = f"{col}_cur"
        if cur_col in merged.columns:
            return merged[cur_col].where(merged[cur_col].notna(), merged[col] if col in merged.columns else None)
        return merged[col] if col in merged.columns else None

    merged["status"] = pick("status")
    merged["hide_flag"] = pick("hide_flag").fillna(False).astype(bool)
    merged["note"] = pick("note")
    merged["industry_override"] = pick("industry_override")
    merged["tags_add"] = pick("tags_add")
    merged["tags_remove"] = pick("tags_remove")

    merged["industry_effective"] = merged["industry_override"].where(
        merged["industry_override"].notna() & (merged["industry_override"].astype(str).str.strip() != ""),
        merged["industry"] if "industry" in merged.columns else "",
    )

    base_tags = merged["tags"] if "tags" in merged.columns else pd.Series([[] for _ in range(len(merged))])

    tags_effective = []
    for i in range(len(merged)):
        base = set(_split_tags(base_tags.iloc[i]))
        add = set(_split_tags(merged["tags_add"].iloc[i]))
        rem = set(_split_tags(merged["tags_remove"].iloc[i]))
        tags_effective.append(sorted((base | add) - rem))
    merged["tags_raw"] = base_tags
    merged["tags_effective"] = tags_effective

    changed = curation_df["business_id"].dropna().astype(str).unique().tolist()
    return AppliedCuration(merged, changed)


def update_curation_from_edits(
    edits: Iterable[dict],
    base_curation: pd.DataFrame,
    *,
    source_master: str | None = None,
    updated_by: str = "local",
) -> pd.DataFrame:
    """Apply edited rows (dicts with business_id) onto curation df."""
    cur = base_curation.copy()
    cur["business_id"] = cur["business_id"].astype(str)
    cur = cur.set_index("business_id", drop=False)

    for row in edits:
        bid = str(row.get("business_id", "")).strip()
        if not bid:
            continue
        payload = {k: row.get(k) for k in ["status", "hide_flag", "note", "industry_override", "tags_add", "tags_remove"]}
        if bid not in cur.index:
            cur.loc[bid] = [None] * len(CURATION_COLUMNS)
            cur.at[bid, "business_id"] = bid
        for key, val in payload.items():
            if key in cur.columns:
                if key in ("tags_add", "tags_remove"):
                    cur.at[bid, key] = ";".join(normalize_tags(val))
                else:
                    cur.at[bid, key] = val
        cur.at[bid, "updated_by"] = updated_by
        cur.at[bid, "source_master"] = source_master or cur.at[bid, "source_master"]
    return cur.reset_index(drop=True)


def compute_edit_diff(before: pd.DataFrame, after: pd.DataFrame, *, key: str = "business_id", fields: list | None = None) -> dict:
    """Return summary of changes between two dataframes keyed by business_id."""
    fields = fields or ["status", "hide_flag", "note", "industry_override", "tags_add", "tags_remove"]
    before_idx = before.set_index(key)
    after_idx = after.set_index(key)
    changed_rows = set(before_idx.index).intersection(set(after_idx.index))
    summary = {f: 0 for f in fields}
    examples = []
    changed_rows_count = 0
    for bid in changed_rows:
        before_row = before_idx.loc[bid]
        after_row = after_idx.loc[bid]
        changed_fields = []
        for f in fields:
            b = before_row.get(f, None)
            a = after_row.get(f, None)
            if str(b) != str(a):
                summary[f] += 1
                changed_fields.append(f)
        if changed_fields:
            changed_rows_count += 1
            if len(examples) < 5:
                examples.append({"business_id": bid, "changed_fields": changed_fields})
    summary["changed_rows_count"] = changed_rows_count
    return {"summary": summary, "examples": examples}
