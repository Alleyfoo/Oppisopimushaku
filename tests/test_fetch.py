import requests
from requests import Response

from apprscan.jobs.fetch import fetch_url


class DummySession:
    def __init__(self, status_sequence):
        self.status_sequence = status_sequence
        self.calls = 0

    def get(self, url, timeout=20, headers=None, allow_redirects=True):
        self.calls += 1
        status = self.status_sequence[min(self.calls - 1, len(self.status_sequence) - 1)]
        resp = Response()
        resp.status_code = status
        resp.url = url
        resp._content = b"<html></html>"
        return resp


def test_fetch_url_retries_on_429_then_succeeds(tmp_path):
    session = DummySession([429, 200])
    res, reason = fetch_url(session, "https://example.com", rate_limit_state={}, debug_html_dir=tmp_path)
    assert res is not None
    assert session.calls == 2

