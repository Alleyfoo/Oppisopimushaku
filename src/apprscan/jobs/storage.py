"""Storage helpers for JobPosting lists."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

import pandas as pd

from .model import JobPosting

ORDERED_COLUMNS = [
    "company_business_id",
    "company_name",
    "company_domain",
    "job_title",
    "job_url",
    "location_text",
    "employment_type",
    "posted_date",
    "description_snippet",
    "source",
    "tags",
    "crawl_ts",
]


def jobs_to_dataframe(jobs: Iterable[JobPosting]) -> pd.DataFrame:
    rows = [j.to_dict() for j in jobs]
    df = pd.DataFrame(rows)
    for col in ORDERED_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[ORDERED_COLUMNS]


def write_jobs_jsonl(jobs: Iterable[JobPosting], path: str | Path) -> None:
    df = jobs_to_dataframe(jobs)
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_json(out_path, orient="records", lines=True, force_ascii=False)


def write_jobs_excel(jobs: Iterable[JobPosting], path: str | Path) -> None:
    df = jobs_to_dataframe(jobs)
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_path, index=False)


def write_jobs_outputs(jobs_df: pd.DataFrame, stats_df: pd.DataFrame, out_dir: str | Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs_path = out_dir / "jobs.xlsx"
    jsonl_path = out_dir / "jobs.jsonl"
    stats_path = out_dir / "crawl_stats.xlsx"
    jobs_df.to_excel(jobs_path, index=False)
    jobs_df.to_json(jsonl_path, orient="records", lines=True, force_ascii=False)
    stats_df.to_excel(stats_path, index=False)
