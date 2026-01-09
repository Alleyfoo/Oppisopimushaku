import types

from apprscan.server import service


class DummyScanOutcome:
    def __init__(self, selected):
        self.selected = selected
        self.checked_urls = []
        self.errors = []
        self.skipped_reasons = []
        self.pages_fetched = 1


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
    result = service.process_maps_ingest(maps_url="https://www.google.com/maps")
    assert result["status"] == "ok"
    package = captured["package"]
    assert package["status"] == "ok"
    assert package["source"]["website_source"] == "places"
    assert package["hiring"]["status"] == "yes"


def test_missing_website_degraded(monkeypatch):
    captured = _capture_package(monkeypatch)
    monkeypatch.setattr(service, "resolve_place_id", lambda _: "place_123")
    monkeypatch.setattr(service, "resolve_website", lambda _: "")
    result = service.process_maps_ingest(maps_url="https://www.google.com/maps")
    assert result["status"] == "degraded"
    package = captured["package"]
    assert package["status"] == "degraded"
    assert package["hiring"]["status"] == "uncertain"
    assert "Paste official website URL" in package.get("next_action", "")


def test_invalid_maps_url_error(monkeypatch):
    captured = _capture_package(monkeypatch)
    result = service.process_maps_ingest(maps_url="https://example.com")
    assert result["status"] == "error"
    package = captured["package"]
    assert package["status"] == "error"
    assert "invalid_maps_url" in package.get("error", {}).get("code", "")
