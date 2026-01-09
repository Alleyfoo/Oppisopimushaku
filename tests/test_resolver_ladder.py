from datetime import datetime, timezone

from apprscan import __version__
from apprscan.server import service


class DummyScanOutcome:
    def __init__(self, selected):
        self.selected = selected
        self.checked_urls = []
        self.errors = []
        self.skipped_reasons = []
        self.pages_fetched = 1
        self.results_found = bool(selected)
        self.cookie_wall = {
            "detected": False,
            "score": 0.0,
            "hit_count": 0,
            "signals": [],
            "threshold": {"hits_min": 2, "score_min": 0.4, "text_max_len": 2000, "hits_hard": 5},
            "sample_title": "",
            "matches": [],
        }


def _capture_package(monkeypatch):
    captured = {}

    def _fake_write(run_id, package, out_root=None):
        captured["run_id"] = run_id
        captured["package"] = package
        return None

    monkeypatch.setattr(service, "write_company_package", _fake_write)
    return captured


def test_places_resolver_ok(monkeypatch):
    captured = _capture_package(monkeypatch)
    monkeypatch.setattr(service, "resolve_place_id", lambda _: "place_123")
    monkeypatch.setattr(service, "resolve_website", lambda _: "https://example.com")
    monkeypatch.setattr(
        service,
        "scan_domain",
        lambda **kwargs: DummyScanOutcome(
            {
                "signal": "yes",
                "confidence": 0.8,
                "evidence": "job_signal_keywords",
                "evidence_snippets": ["open positions", "apply now"],
                "evidence_urls": ["https://example.com/careers", "https://example.com/jobs"],
            }
        ),
    )
    start = datetime.now(timezone.utc)
    result = service.process_maps_ingest(maps_url="https://www.google.com/maps")
    assert result["status"] == "ok"
    package = captured["package"]
    assert package["status"] == "ok"
    assert package["degraded_reason"] == "none"
    assert package["source"]["website_source"] == "places"
    assert package["hiring"]["status"] == "yes"
    assert package["tool_version"] == __version__
    assert package["git_sha"] == "" or len(package["git_sha"]) >= 7
    created = datetime.fromisoformat(package["created_at"].replace("Z", "+00:00"))
    assert abs((created - start).total_seconds()) < 60


def test_missing_website_degraded(monkeypatch):
    captured = _capture_package(monkeypatch)
    monkeypatch.setattr(service, "resolve_place_id", lambda _: "place_123")
    monkeypatch.setattr(service, "resolve_website", lambda _: "")
    result = service.process_maps_ingest(maps_url="https://www.google.com/maps")
    assert result["status"] == "degraded"
    package = captured["package"]
    assert package["status"] == "degraded"
    assert package["degraded_reason"] == "website_missing"
    assert package["hiring"]["status"] == "uncertain"
    assert "Paste official website URL" in package.get("next_action", "")


def test_invalid_maps_url_error(monkeypatch):
    captured = _capture_package(monkeypatch)
    result = service.process_maps_ingest(maps_url="https://example.com")
    assert result["status"] == "error"
    package = captured["package"]
    assert package["status"] == "error"
    assert package["degraded_reason"] == "none"
    assert "invalid_maps_url" in package.get("error", {}).get("code", "")
