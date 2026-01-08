"""Helper functions to locate latest run artifacts (master, diff)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence


def _latest(paths: Sequence[Path]) -> Optional[Path]:
    paths = [p for p in paths if p.exists()]
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def find_latest_master(out_dir: str | Path = "out") -> Optional[Path]:
    out_dir = Path(out_dir)
    candidates = list(out_dir.glob("master_*.xlsx"))
    legacy = out_dir / "master.xlsx"
    if legacy.exists():
        candidates.append(legacy)
    return _latest(candidates)


def find_latest_diff(out_dir: str | Path = "out") -> Optional[Path]:
    out_dir = Path(out_dir)
    candidates = list(out_dir.glob("run_*/jobs/diff.xlsx"))
    legacy = out_dir / "jobs" / "diff.xlsx"
    if legacy.exists():
        candidates.append(legacy)
    return _latest(candidates)
