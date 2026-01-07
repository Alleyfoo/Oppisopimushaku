from pathlib import Path

import pandas as pd

from apprscan.jobs.model import JobPosting
from apprscan.jobs.storage import ORDERED_COLUMNS, jobs_to_dataframe, write_jobs_excel, write_jobs_jsonl


def sample_jobs():
    return [
        JobPosting(
            company_business_id="123",
            company_name="Test Oy",
            company_domain="example.com",
            job_title="Apprentice Developer",
            job_url="https://example.com/jobs/1",
            source="jsonld",
            tags=["oppisopimus"],
            crawl_ts="2024-01-01T00:00:00Z",
        )
    ]


def test_jobs_to_dataframe_column_order():
    df = jobs_to_dataframe(sample_jobs())
    assert list(df.columns) == ORDERED_COLUMNS
    assert df.loc[0, "job_title"] == "Apprentice Developer"


def test_write_jobs_files(tmp_path: Path):
    jobs = sample_jobs()
    jsonl_path = tmp_path / "jobs.jsonl"
    excel_path = tmp_path / "jobs.xlsx"

    write_jobs_jsonl(jobs, jsonl_path)
    write_jobs_excel(jobs, excel_path)

    assert jsonl_path.exists()
    assert excel_path.exists()

    # Basic schema check
    df = pd.read_excel(excel_path)
    for col in ORDERED_COLUMNS:
        assert col in df.columns
