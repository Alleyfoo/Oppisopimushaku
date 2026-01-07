import requests
from requests import Response

from apprscan.jobs.extract.generic_html import discover_job_links, extract_jobs_generic


def test_discover_job_links():
    html = """
    <a href="/jobs/1">Apply now</a>
    <a href="/about">About</a>
    """
    urls = discover_job_links(html, "https://example.com")
    assert "https://example.com/jobs/1" in urls
    assert len(urls) == 1


class DummySession:
    def __init__(self, html):
        self.html = html
        self.calls = 0

    def get(self, url, timeout=20, headers=None, allow_redirects=True):
        self.calls += 1
        resp = Response()
        resp.status_code = 200
        resp.url = url
        resp._content = self.html.encode("utf-8")
        return resp


def test_extract_jobs_generic():
    list_html = '<a href="/jobs/1">Apply</a>'
    detail_html = "<h1>Support Engineer</h1><p>Helpdesk support</p>"
    session = DummySession(detail_html)
    company = {"business_id": "123", "name": "Test", "domain": "example.com"}
    jobs = extract_jobs_generic(
        session,
        list_html,
        "https://example.com/careers",
        company,
        "2024-01-01T00:00:00Z",
        rate_limit_state={},
    )
    assert len(jobs) == 1
    assert jobs[0].job_title == "Support Engineer"
