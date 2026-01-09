"""Companion service helpers for Maps ingest and dossier creation."""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

from .. import __version__
from ..hiring_scan import PROMPT_VERSION, _load_env_file, _repo_root, scan_domain, _resolve_git_sha
from ..places_api import fetch_place_details, get_api_key


SCHEMA_VERSION = "0.1"
ALLOWED_HOSTS = {"www.google.com", "google.com", "maps.google.com", "maps.app.goo.gl", "goo.gl"}


@dataclass
class ScanConfig:
    ollama_host: str
    ollama_model: str
    ollama_options: dict[str, Any]
    ollama_temperature: float
    use_llm: bool
    robots_mode: str
    max_urls: int
    sleep_s: float
    deterministic: bool
    prompt_version: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{secrets.token_hex(4)}"


def _repo_env_file() -> Path | None:
    root = _repo_root()
    env_file = root / ".env"
    return env_file if env_file.exists() else None


def load_scan_config(env_file: Path | None = None) -> ScanConfig:
    env_file = env_file or _repo_env_file()
    env = _load_env_file(env_file)
    merged = dict(env)
    for key in ("OLLAMA_HOST", "OLLAMA_URL", "OLLAMA_MODEL", "MODEL_NAME", "OLLAMA_OPTIONS"):
        if key in os.environ:
            merged[key] = os.environ[key]

    host = merged.get("OLLAMA_URL") or merged.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
    if "ollama:11434" in host:
        host = "http://127.0.0.1:11434"
    model = merged.get("OLLAMA_MODEL") or merged.get("MODEL_NAME") or ""
    options: dict[str, Any] = {"temperature": 0.2, "num_predict": 400}
    if merged.get("OLLAMA_OPTIONS"):
        try:
            options.update(json.loads(merged["OLLAMA_OPTIONS"]))
        except json.JSONDecodeError:
            pass
    temperature = float(options.get("temperature", 0.0))
    use_llm = bool(model)
    return ScanConfig(
        ollama_host=host,
        ollama_model=model,
        ollama_options=options,
        ollama_temperature=temperature,
        use_llm=use_llm,
        robots_mode="strict",
        max_urls=2,
        sleep_s=0.5,
        deterministic=False,
        prompt_version=PROMPT_VERSION,
    )


def _expand_maps_url(maps_url: str) -> str:
    parsed = urlparse(maps_url)
    if parsed.netloc not in {"maps.app.goo.gl", "goo.gl"}:
        return maps_url
    try:
        resp = requests.get(maps_url, allow_redirects=True, timeout=10)
        return str(resp.url)
    except requests.RequestException:
        return maps_url


def resolve_place_id(maps_url: str) -> str | None:
    url = maps_url.strip()
    if not url:
        return None
    expanded = _expand_maps_url(url)
    parsed = urlparse(expanded)
    if parsed.netloc not in ALLOWED_HOSTS:
        return None
    qs = parse_qs(parsed.query)
    for key in ("place_id", "placeid", "query_place_id"):
        if key in qs and qs[key]:
            return qs[key][0]
    match = re.search(r"!1s([^!]+)", expanded)
    if match:
        return unquote(match.group(1))
    return None


def resolve_website(place_id: str, api_key: str | None = None) -> str:
    key = api_key or get_api_key()
    details = fetch_place_details(place_id, api_key=key, field_mask="id,websiteUri")
    return str(details.get("website") or "").strip()


def _clean_domain(website_url: str) -> str:
    parsed = urlparse(website_url if "://" in website_url else f"https://{website_url}")
    host = parsed.netloc or parsed.path
    return host.split("/")[0].strip()


def _build_evidence(snippets: list[str], urls: list[str]) -> list[dict[str, str]]:
    evidence = []
    for idx, snippet in enumerate(snippets):
        url = urls[idx] if idx < len(urls) else (urls[0] if urls else "")
        if snippet or url:
            evidence.append({"snippet": snippet, "url": url})
    return evidence


def build_company_package(
    *,
    run_id: str,
    maps_url: str,
    place_id: str | None,
    website_url: str,
    domain: str,
    scan_config: ScanConfig,
    scan_result: dict[str, Any],
    checked_urls: list[str],
    errors: list[str],
    skipped_reasons: list[str],
    pages_fetched: int,
    note: str,
    tags: list[str],
) -> dict[str, Any]:
    signal = str(scan_result.get("signal") or scan_result.get("hiring_signal") or "unclear").lower()
    status_map = {"yes": "yes", "no": "no", "unclear": "uncertain"}
    status = status_map.get(signal, "uncertain")
    snippets = scan_result.get("evidence_snippets") or []
    urls = scan_result.get("evidence_urls") or []
    evidence = _build_evidence([str(s) for s in snippets], [str(u) for u in urls])
    signals = []
    if scan_result.get("evidence"):
        signals.append(str(scan_result.get("evidence")))

    package = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": _now_iso(),
        "tool_version": __version__,
        "git_sha": _resolve_git_sha(_repo_root()),
        "source": {
            "source_ref": maps_url,
            "place_id": place_id or "",
            "canonical_domain": domain,
        },
        "hiring": {
            "status": status,
            "confidence": float(scan_result.get("confidence") or 0.0),
            "signals": signals,
            "evidence": evidence,
        },
        "industry": {"labels": [], "confidence": 0.0, "evidence": []},
        "roles": {
            "detected": [],
            "fit": {
                "score": 0,
                "green_flags": [],
                "red_flags": [],
                "evidence": [],
            },
        },
        "links": {
            "maps_url": maps_url,
            "website_url": website_url,
            "careers_urls": [],
            "ats_urls": [],
            "contact_url": "",
        },
        "safety": {
            "robots_respected": "unknown",
            "pages_fetched": pages_fetched,
            "skipped_reasons": skipped_reasons,
            "errors": errors,
            "checked_urls": checked_urls,
            "llm_used": scan_config.use_llm,
            "prompt_version": scan_config.prompt_version,
            "ollama_model": scan_config.ollama_model,
            "ollama_temperature": scan_config.ollama_temperature,
            "deterministic": scan_config.deterministic,
        },
        "notes": {"note": note or "", "tags": tags or []},
    }
    return package


def write_company_package(run_id: str, package: dict[str, Any], out_root: Path | None = None) -> Path:
    out_root = out_root or Path("out") / "runs"
    out_dir = out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "company_package.json"
    out_path.write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def read_company_package(run_id: str, out_root: Path | None = None) -> dict[str, Any] | None:
    out_root = out_root or Path("out") / "runs"
    path = out_root / run_id / "company_package.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def process_maps_ingest(
    *,
    maps_url: str,
    note: str = "",
    tags: list[str] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or new_run_id()
    tags = tags or []
    place_id = resolve_place_id(maps_url)
    if not place_id:
        package = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": _now_iso(),
            "tool_version": __version__,
            "git_sha": _resolve_git_sha(_repo_root()),
            "source": {"source_ref": maps_url, "place_id": "", "canonical_domain": ""},
            "hiring": {"status": "uncertain", "confidence": 0.0, "signals": [], "evidence": []},
            "industry": {"labels": [], "confidence": 0.0, "evidence": []},
            "roles": {"detected": [], "fit": {"score": 0, "green_flags": [], "red_flags": [], "evidence": []}},
            "links": {"maps_url": maps_url, "website_url": "", "careers_urls": [], "ats_urls": [], "contact_url": ""},
            "safety": {
                "robots_respected": "unknown",
                "pages_fetched": 0,
                "skipped_reasons": [],
                "errors": ["place_id_not_found"],
                "checked_urls": [],
                "llm_used": False,
                "prompt_version": "",
                "ollama_model": "",
                "ollama_temperature": 0.0,
                "deterministic": False,
            },
            "notes": {"note": note or "", "tags": tags or []},
            "error": {"code": "place_id_not_found", "message": "Could not resolve place_id from Maps URL."},
        }
        write_company_package(run_id, package)
        return {"run_id": run_id, "status": "error"}

    try:
        website_url = resolve_website(place_id)
    except Exception as exc:
        package = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": _now_iso(),
            "tool_version": __version__,
            "git_sha": _resolve_git_sha(_repo_root()),
            "source": {"source_ref": maps_url, "place_id": place_id, "canonical_domain": ""},
            "hiring": {"status": "uncertain", "confidence": 0.0, "signals": [], "evidence": []},
            "industry": {"labels": [], "confidence": 0.0, "evidence": []},
            "roles": {"detected": [], "fit": {"score": 0, "green_flags": [], "red_flags": [], "evidence": []}},
            "links": {"maps_url": maps_url, "website_url": "", "careers_urls": [], "ats_urls": [], "contact_url": ""},
            "safety": {
                "robots_respected": "unknown",
                "pages_fetched": 0,
                "skipped_reasons": [],
                "errors": [f"places_lookup_failed:{exc}"],
                "checked_urls": [],
                "llm_used": False,
                "prompt_version": "",
                "ollama_model": "",
                "ollama_temperature": 0.0,
                "deterministic": False,
            },
            "notes": {"note": note or "", "tags": tags or []},
            "error": {"code": "places_lookup_failed", "message": "Places lookup failed."},
        }
        write_company_package(run_id, package)
        return {"run_id": run_id, "status": "error"}

    if not website_url:
        package = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": _now_iso(),
            "tool_version": __version__,
            "git_sha": _resolve_git_sha(_repo_root()),
            "source": {"source_ref": maps_url, "place_id": place_id, "canonical_domain": ""},
            "hiring": {"status": "uncertain", "confidence": 0.0, "signals": [], "evidence": []},
            "industry": {"labels": [], "confidence": 0.0, "evidence": []},
            "roles": {"detected": [], "fit": {"score": 0, "green_flags": [], "red_flags": [], "evidence": []}},
            "links": {"maps_url": maps_url, "website_url": "", "careers_urls": [], "ats_urls": [], "contact_url": ""},
            "safety": {
                "robots_respected": "unknown",
                "pages_fetched": 0,
                "skipped_reasons": [],
                "errors": ["website_missing"],
                "checked_urls": [],
                "llm_used": False,
                "prompt_version": "",
                "ollama_model": "",
                "ollama_temperature": 0.0,
                "deterministic": False,
            },
            "notes": {"note": note or "", "tags": tags or []},
            "error": {"code": "website_missing", "message": "Place has no websiteUri."},
        }
        write_company_package(run_id, package)
        return {"run_id": run_id, "status": "error"}

    domain = _clean_domain(website_url)
    scan_config = load_scan_config()
    scan_outcome = scan_domain(
        domain=domain,
        name=domain,
        website_url=website_url,
        max_urls=scan_config.max_urls,
        sleep_s=scan_config.sleep_s,
        robots_mode=scan_config.robots_mode,
        robots_allowlist=None,
        session=requests.Session(),
        rate_limit_state={},
        ollama_host=scan_config.ollama_host,
        ollama_model=scan_config.ollama_model,
        ollama_options=scan_config.ollama_options,
        use_llm=scan_config.use_llm,
    )
    package = build_company_package(
        run_id=run_id,
        maps_url=maps_url,
        place_id=place_id,
        website_url=website_url,
        domain=domain,
        scan_config=scan_config,
        scan_result=scan_outcome.selected,
        checked_urls=scan_outcome.checked_urls,
        errors=scan_outcome.errors,
        skipped_reasons=scan_outcome.skipped_reasons,
        pages_fetched=scan_outcome.pages_fetched,
        note=note,
        tags=tags,
    )
    write_company_package(run_id, package)
    return {"run_id": run_id, "status": "ok"}
