from pathlib import Path

from apprscan.jobs.extract.jsonld import extract_jobs_from_jsonld


def test_extract_jobs_from_jsonld():
    html = Path("tests/fixtures/jsonld_jobposting.html").read_text(encoding="utf-8")
    company = {"business_id": "123", "name": "Test Oy", "domain": "example.com"}
    jobs = extract_jobs_from_jsonld(html, "https://example.com/careers", company, "2024-01-01T00:00:00Z")
    assert len(jobs) == 2
    urls = {j.job_url for j in jobs}
    assert "https://example.com/jobs/1" in urls
    assert "https://example.com/jobs/2" in urls
