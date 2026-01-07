import pandas as pd

from apprscan.jobs import pipeline
from apprscan.jobs.model import JobPosting


def test_concurrency_determinism(monkeypatch):
    companies = pd.DataFrame(
        [
            {"business_id": "1", "name": "A", "domain": "a.com"},
            {"business_id": "2", "name": "B", "domain": "b.com"},
        ]
    )
    domain_map = {}

    def fake_crawl_domain(company, domain, **kwargs):
        job = JobPosting(
            company_business_id=company["business_id"],
            company_name=company["name"],
            company_domain=domain,
            job_title="Role",
            job_url=f"https://{domain}/job",
            source="test",
            tags=[],
            crawl_ts="ts",
        )
        stats = pipeline.CrawlStats(domain=domain, pages_fetched=1, jobs_found=1)
        return [job], stats

    monkeypatch.setattr(pipeline, "crawl_domain", fake_crawl_domain)

    jobs1, stats1, _ = pipeline.crawl_jobs_pipeline(
        companies, domain_map, max_domains=10, max_workers=1, max_pages_per_domain=1
    )
    jobs2, stats2, _ = pipeline.crawl_jobs_pipeline(
        companies, domain_map, max_domains=10, max_workers=5, max_pages_per_domain=1
    )

    def normalize_jobs(df):
        return sorted(zip(df["company_domain"], df["job_url"]))

    assert normalize_jobs(jobs1) == normalize_jobs(jobs2)

    def normalize_stats(df):
        return sorted(zip(df["domain"], df["pages_fetched"], df["jobs_found"]))

    assert normalize_stats(stats1) == normalize_stats(stats2)
