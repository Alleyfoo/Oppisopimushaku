import json
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("fastapi.testclient")

from fastapi.testclient import TestClient

from apprscan.server.app import create_app
from apprscan.server import service


def _minimal_package(run_id: str) -> dict:
    return {
        "status": "ok",
        "schema_version": "0.1",
        "run_id": run_id,
        "created_at": "2026-01-01T00:00:00Z",
        "tool_version": "0.0.0",
        "git_sha": "",
        "source": {
            "source_ref": "https://www.google.com/maps",
            "place_id": "",
            "canonical_domain": "",
            "website_source": "unknown",
            "resolver_notes": "",
        },
        "hiring": {"status": "uncertain", "confidence": 0.0, "signals": [], "evidence": []},
        "industry": {"labels": [], "confidence": 0.0, "evidence": []},
        "roles": {"detected": [], "fit": {"score": 0, "green_flags": [], "red_flags": [], "evidence": []}},
        "links": {"maps_url": "", "website_url": "", "careers_urls": [], "ats_urls": [], "contact_url": ""},
        "next_action": "",
        "safety": {
            "robots_respected": "unknown",
            "pages_fetched": 0,
            "skipped_reasons": [],
            "errors": [],
            "checked_urls": [],
            "llm_used": False,
            "prompt_version": "",
            "ollama_model": "",
            "ollama_temperature": 0.0,
            "deterministic": False,
        },
        "notes": {"note": "", "tags": []},
    }


def _schema_required(schema: dict) -> set[str]:
    required = set(schema.get("required", []))
    return required


def test_ingest_requires_token(monkeypatch):
    monkeypatch.setattr("apprscan.server.routes.process_maps_ingest", lambda **kwargs: None)
    app = create_app(token="test-token")
    client = TestClient(app)
    resp = client.post("/ingest/maps", json={"maps_url": "https://www.google.com/maps"})
    assert resp.status_code == 401
    resp = client.post(
        "/ingest/maps",
        json={"maps_url": "https://www.google.com/maps"},
        headers={"X-APPRSCAN-TOKEN": "bad"},
    )
    assert resp.status_code == 401


def test_ingest_result_flow(monkeypatch):
    monkeypatch.setattr("apprscan.server.routes.process_maps_ingest", lambda **kwargs: None)
    app = create_app(token="test-token")
    client = TestClient(app)
    resp = client.post(
        "/ingest/maps",
        json={"maps_url": "https://www.google.com/maps"},
        headers={"X-APPRSCAN-TOKEN": "test-token"},
    )
    assert resp.status_code == 200
    run_id = resp.json().get("run_id")
    assert run_id
    pending = client.get(f"/result/{run_id}", headers={"X-APPRSCAN-TOKEN": "test-token"})
    assert pending.status_code == 202

    package = _minimal_package(run_id)
    service.write_company_package(run_id, package)
    md_path = Path("out") / "runs" / run_id / "company_package.md"
    assert md_path.exists()

    done = client.get(f"/result/{run_id}", headers={"X-APPRSCAN-TOKEN": "test-token"})
    assert done.status_code == 200
    payload = done.json()
    assert payload["run_id"] == run_id

    schema_path = Path("src/apprscan/schemas/company_package.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert _schema_required(schema).issubset(payload.keys())


def test_rate_limit(monkeypatch):
    monkeypatch.setattr("apprscan.server.routes.process_maps_ingest", lambda **kwargs: None)
    app = create_app(token="test-token")
    app.state.rate_limit_max = 1
    client = TestClient(app)
    first = client.post(
        "/ingest/maps",
        json={"maps_url": "https://www.google.com/maps"},
        headers={"X-APPRSCAN-TOKEN": "test-token"},
    )
    assert first.status_code == 200
    second = client.post(
        "/ingest/maps",
        json={"maps_url": "https://www.google.com/maps"},
        headers={"X-APPRSCAN-TOKEN": "test-token"},
    )
    assert second.status_code == 429
