"""Helper functions to locate latest run artifacts (master, diff)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence
import re


def _latest(paths: Sequence[Path]) -> Optional[Path]:
    paths = [p for p in paths if p.exists()]
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def _extract_date(path: Path) -> Optional[str]:
    m = re.search(r"(\d{8})", path.name)
    return m.group(1) if m else None


def artifact_date(path: Path | None) -> Optional[str]:
    """Return YYYYMMDD from filename or run_* parent."""
    if path is None:
        return None
    date = _extract_date(path)
    if date:
        return date
    for parent in [path.parent, path.parent.parent]:
        if parent is None:
            continue
        if parent.name.startswith("run_") and len(parent.name) >= 12 and parent.name[4:12].isdigit():
            return parent.name[4:12]
    return None


def _pick_by_date_then_mtime(candidates: list[Path]) -> Optional[Path]:
    if not candidates:
        return None
    dated = []
    for p in candidates:
        date = _extract_date(p)
        if date:
            dated.append((date, p))
    if dated:
        dated.sort(key=lambda x: x[0], reverse=True)
        return dated[0][1]
    return _latest(candidates)


def find_latest_master(out_dir: str | Path = "out", run_id: str | None = None) -> Optional[Path]:
    out_dir = Path(out_dir)
    candidates = []
    if run_id:
        rid = run_id.replace("run_", "")
        candidates.extend(out_dir.glob(f"master_{rid}.xlsx"))
    else:
        candidates.extend(out_dir.glob("master_*.xlsx"))
    legacy = out_dir / "master.xlsx"
    if legacy.exists():
        candidates.append(legacy)
    return _pick_by_date_then_mtime(candidates)


def find_latest_diff(out_dir: str | Path = "out", run_id: str | None = None) -> Optional[Path]:
    out_dir = Path(out_dir)
    candidates = []
    if run_id:
        rid = run_id.replace("run_", "")
        candidates.extend(out_dir.glob(f"run_{rid}/jobs/diff.xlsx"))
    else:
        candidates.extend(out_dir.glob("run_*/jobs/diff.xlsx"))
    legacy = out_dir / "jobs" / "diff.xlsx"
    if legacy.exists():
        candidates.append(legacy)
    return _pick_by_date_then_mtime(candidates)
