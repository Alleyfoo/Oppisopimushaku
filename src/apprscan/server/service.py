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
import shutil

from .. import __version__
from ..hiring_scan import PROMPT_VERSION, _load_env_file, _repo_root, scan_domain, _resolve_git_sha
from ..places_api import fetch_place_details, get_api_key


SCHEMA_VERSION = "0.1"
ALLOWED_HOSTS = {"www.google.com", "google.com", "maps.google.com", "maps.app.goo.gl", "goo.gl"}
ATS_HOSTS = {
    "greenhouse.io",
    "lever.co",
    "workable.com",
    "smartrecruiters.com",
    "recruitee.com",
    "teamtailor.com",
    "jobylon.com",
    "talentadore.com",
    "sympa.com",
    "jazzhr.com",
}


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


def purge_runs(out_root: Path | None = None, max_age_days: int = 30) -> int:
    out_root = out_root or Path("out") / "runs"
    if not out_root.exists():
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
    purged = 0
    for child in out_root.iterdir():
        if not child.is_dir():
            continue
        stat = child.stat()
        if stat.st_mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            purged += 1
    return purged


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


def _maps_host_allowed(maps_url: str) -> bool:
    expanded = _expand_maps_url(maps_url)
    parsed = urlparse(expanded)
    return parsed.netloc in ALLOWED_HOSTS


def resolve_website(place_id: str, api_key: str | None = None) -> str:
    key = api_key or get_api_key()
    details = fetch_place_details(place_id, api_key=key, field_mask="id,websiteUri")
    return str(details.get("website") or "").strip()


def _clean_domain(website_url: str) -> str:
    parsed = urlparse(website_url if "://" in website_url else f"https://{website_url}")
    host = parsed.netloc or parsed.path
    return host.split("/")[0].strip()


def _is_first_party(url: str, domain: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower()
    if not host or not domain:
        return False
    domain = domain.lower()
    return host == domain or host.endswith(f".{domain}")


def _is_ats_host(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower()
    if not host:
        return False
    return any(host == ats or host.endswith(f".{ats}") for ats in ATS_HOSTS)


def _build_evidence(snippets: list[str], urls: list[str]) -> list[dict[str, str]]:
    evidence = []
    for idx, snippet in enumerate(snippets):
        url = urls[idx] if idx < len(urls) else (urls[0] if urls else "")
        if snippet or url:
            evidence.append({"snippet": snippet, "url": url})
    return evidence


def _default_cookie_wall() -> dict[str, Any]:
    return {
        "detected": False,
        "score": 0.0,
        "hit_count": 0,
        "signals": [],
        "threshold": {"hits_min": 2, "score_min": 0.4, "text_max_len": 2000, "hits_hard": 5},
        "sample_title": "",
        "matches": [],
    }


def _merge_cookie_wall(cookie_wall: dict[str, Any] | None) -> dict[str, Any]:
    merged = _default_cookie_wall()
    if not cookie_wall:
        return merged
    merged.update({key: value for key, value in cookie_wall.items() if value is not None})
    if isinstance(cookie_wall.get("threshold"), dict):
        merged["threshold"] = {**merged["threshold"], **cookie_wall["threshold"]}
    return merged


def _sanitize_errors(errors: list[str]) -> list[str]:
    sanitized = []
    for err in errors:
        if ":cookie_wall:" in err:
            continue
        sanitized.append(err)
    return sanitized


def _enforce_hiring_evidence(
    status: str, evidence_urls: list[str], domain: str
) -> tuple[str, float, list[str]]:
    if status != "yes":
        return status, 0.0, []
    eligible = []
    for url in evidence_urls:
        if _is_first_party(url, domain) or _is_ats_host(url):
            eligible.append(url)
    unique_urls = sorted(set(eligible))
    if len(unique_urls) >= 2:
        return status, 0.0, []
    if len(unique_urls) == 1:
        return "maybe", 0.5, ["insufficient_evidence_urls"]
    return "uncertain", 0.2, ["insufficient_evidence_urls"]


def _markdown_links(title: str, url: str) -> str:
    if not url:
        return ""
    return f"[{title}]({url})"


def render_company_markdown(package: dict[str, Any]) -> str:
    source = package.get("source", {})
    links = package.get("links", {})
    hiring = package.get("hiring", {})
    safety = package.get("safety", {})
    notes = package.get("notes", {})
    domain = source.get("canonical_domain") or ""
    maps_url = links.get("maps_url") or source.get("source_ref") or ""
    website_url = links.get("website_url") or ""
    title = domain or "Unknown company"

    lines = [f"# {title}"]
    if domain:
        lines.append(f"Domain: `{domain}`")
    if website_url:
        lines.append(f"Website: {_markdown_links(website_url, website_url)}")
    if maps_url:
        lines.append(f"Maps: {_markdown_links('Open in Google Maps', maps_url)}")
    lines.append("")

    status = hiring.get("status") or "uncertain"
    confidence = hiring.get("confidence") or 0.0
    lines.append(f"**Decision:** {str(status).upper()} (confidence {confidence:.2f})")
    pipeline_status = package.get("status") or "ok"
    degraded_reason = package.get("degraded_reason") or ""
    if pipeline_status != "ok":
        lines.append(f"Pipeline status: {pipeline_status}")
    if degraded_reason and degraded_reason != "none":
        lines.append(f"Degraded reason: {degraded_reason}")
    lines.append("")

    signals = hiring.get("signals") or []
    why = [str(s) for s in signals if str(s).strip()]
    if not why:
        why = ["No strong deterministic signals found."]
    lines.append("## Why")
    for item in why[:5]:
        lines.append(f"- {item}")
    lines.append("")

    def _evidence_section(title_text: str, evidence_list: list[dict[str, str]]) -> None:
        lines.append(f"## Evidence - {title_text}")
        if not evidence_list:
            lines.append("- No evidence captured.")
        else:
            for entry in evidence_list:
                snippet = entry.get("snippet") or ""
                url = entry.get("url") or ""
                if snippet and url:
                    lines.append(f"- {snippet} ({url})")
                elif url:
                    lines.append(f"- {url}")
                elif snippet:
                    lines.append(f"- {snippet}")
        lines.append("")

    _evidence_section("Hiring", hiring.get("evidence") or [])
    _evidence_section("Industry", package.get("industry", {}).get("evidence") or [])
    _evidence_section("Roles", package.get("roles", {}).get("fit", {}).get("evidence") or [])

    unknowns = []
    skipped = safety.get("skipped_reasons") or []
    errors = safety.get("errors") or []
    cookie_wall = safety.get("cookie_wall") or {}
    if cookie_wall.get("detected"):
        signals = cookie_wall.get("signals") or []
        detail = f" (signals: {', '.join(signals)})" if signals else ""
        unknowns.append(f"Cookie wall detected{detail}.")
    unknowns.extend([f"Skipped: {val}" for val in skipped if val])
    unknowns.extend([f"Error: {val}" for val in errors if val])
    next_action = package.get("next_action") or ""
    if next_action:
        unknowns.append(f"Next action: {next_action}")
    if not unknowns:
        unknowns = ["No major caveats recorded."]
    lines.append("## Unknowns & Caveats")
    for item in unknowns:
        lines.append(f"- {item}")
    lines.append("")

    note = notes.get("note") or ""
    tags = notes.get("tags") or []
    if note or tags:
        lines.append("## Notes")
        if note:
            lines.append(f"- {note}")
        if tags:
            lines.append(f"- Tags: {', '.join(tags)}")
        lines.append("")

    lines.append("## Provenance")
    lines.append(f"- run_id: {package.get('run_id')}")
    lines.append(f"- version: {package.get('tool_version')}")
    lines.append(f"- timestamp: {package.get('created_at')}")
    lines.append(f"- git_sha: {package.get('git_sha')}")
    source = package.get("source", {})
    if source.get("website_source"):
        lines.append(f"- website_source: {source.get('website_source')}")
    lines.append("")
    return "\n".join(lines)


def build_company_package(
    *,
    run_id: str,
    maps_url: str,
    place_id: str | None,
    website_url: str,
    domain: str,
    website_source: str,
    resolver_notes: str,
    scan_config: ScanConfig,
    scan_result: dict[str, Any],
    checked_urls: list[str],
    errors: list[str],
    skipped_reasons: list[str],
    pages_fetched: int,
    note: str,
    tags: list[str],
    pipeline_status: str = "ok",
    degraded_reason: str = "none",
    cookie_wall: dict[str, Any] | None = None,
    next_action: str = "",
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
    downgrade_status, confidence_cap, downgrade_reasons = _enforce_hiring_evidence(status, urls, domain)
    if downgrade_status != status:
        status = downgrade_status
        signals.extend(downgrade_reasons)

    safe_errors = _sanitize_errors(errors)
    cookie_wall = _merge_cookie_wall(cookie_wall)
    package = {
        "status": pipeline_status,
        "degraded_reason": degraded_reason,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": _now_iso(),
        "tool_version": __version__,
        "git_sha": _resolve_git_sha(_repo_root()),
        "source": {
            "source_ref": maps_url,
            "place_id": place_id or "",
            "canonical_domain": domain,
            "website_source": website_source,
            "resolver_notes": resolver_notes,
        },
        "hiring": {
            "status": status,
            "confidence": min(float(scan_result.get("confidence") or 0.0), confidence_cap)
            if confidence_cap
            else float(scan_result.get("confidence") or 0.0),
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
        "next_action": next_action or "",
        "safety": {
            "robots_respected": "unknown",
            "pages_fetched": pages_fetched,
            "skipped_reasons": skipped_reasons,
            "errors": safe_errors,
            "checked_urls": checked_urls,
            "cookie_wall": cookie_wall,
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
    md_path = out_dir / "company_package.md"
    md_path.write_text(render_company_markdown(package), encoding="utf-8")
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
    next_action = ""
    if not _maps_host_allowed(maps_url):
        package = {
            "status": "error",
            "degraded_reason": "none",
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": _now_iso(),
            "tool_version": __version__,
            "git_sha": _resolve_git_sha(_repo_root()),
            "source": {
                "source_ref": maps_url,
                "place_id": "",
                "canonical_domain": "",
                "website_source": "unknown",
                "resolver_notes": "Invalid Maps URL host.",
            },
            "hiring": {"status": "uncertain", "confidence": 0.0, "signals": [], "evidence": []},
            "industry": {"labels": [], "confidence": 0.0, "evidence": []},
            "roles": {"detected": [], "fit": {"score": 0, "green_flags": [], "red_flags": [], "evidence": []}},
            "links": {"maps_url": maps_url, "website_url": "", "careers_urls": [], "ats_urls": [], "contact_url": ""},
            "next_action": "",
            "safety": {
                "robots_respected": "unknown",
                "pages_fetched": 0,
            "skipped_reasons": [],
            "errors": ["invalid_maps_url"],
            "checked_urls": [],
            "cookie_wall": _default_cookie_wall(),
            "llm_used": False,
            "prompt_version": "",
            "ollama_model": "",
                "ollama_temperature": 0.0,
                "deterministic": False,
            },
            "notes": {"note": note or "", "tags": tags or []},
            "error": {"code": "invalid_maps_url", "message": "Maps URL host is not supported."},
        }
        write_company_package(run_id, package)
        return {"run_id": run_id, "status": "error"}

    place_id = resolve_place_id(maps_url)
    if not place_id:
        next_action = "Paste official website URL to proceed."
        package = {
            "status": "degraded",
            "degraded_reason": "place_id_not_found",
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": _now_iso(),
            "tool_version": __version__,
            "git_sha": _resolve_git_sha(_repo_root()),
            "source": {
                "source_ref": maps_url,
                "place_id": "",
                "canonical_domain": "",
                "website_source": "unknown",
                "resolver_notes": "Could not resolve place_id from Maps URL.",
            },
            "hiring": {"status": "uncertain", "confidence": 0.0, "signals": [], "evidence": []},
            "industry": {"labels": [], "confidence": 0.0, "evidence": []},
            "roles": {"detected": [], "fit": {"score": 0, "green_flags": [], "red_flags": [], "evidence": []}},
            "links": {"maps_url": maps_url, "website_url": "", "careers_urls": [], "ats_urls": [], "contact_url": ""},
            "next_action": next_action,
            "safety": {
                "robots_respected": "unknown",
                "pages_fetched": 0,
            "skipped_reasons": [],
            "errors": ["place_id_not_found"],
            "checked_urls": [],
            "cookie_wall": _default_cookie_wall(),
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
        return {"run_id": run_id, "status": "degraded"}

    try:
        website_url = resolve_website(place_id)
    except Exception as exc:
        package = {
            "status": "error",
            "degraded_reason": "none",
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": _now_iso(),
            "tool_version": __version__,
            "git_sha": _resolve_git_sha(_repo_root()),
            "source": {
                "source_ref": maps_url,
                "place_id": place_id,
                "canonical_domain": "",
                "website_source": "places",
                "resolver_notes": "Places lookup failed.",
            },
            "hiring": {"status": "uncertain", "confidence": 0.0, "signals": [], "evidence": []},
            "industry": {"labels": [], "confidence": 0.0, "evidence": []},
            "roles": {"detected": [], "fit": {"score": 0, "green_flags": [], "red_flags": [], "evidence": []}},
            "links": {"maps_url": maps_url, "website_url": "", "careers_urls": [], "ats_urls": [], "contact_url": ""},
            "next_action": "",
            "safety": {
                "robots_respected": "unknown",
                "pages_fetched": 0,
            "skipped_reasons": [],
            "errors": [f"places_lookup_failed:{exc}"],
            "checked_urls": [],
            "cookie_wall": _default_cookie_wall(),
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
        next_action = "Paste official website URL to proceed."
        package = {
            "status": "degraded",
            "degraded_reason": "website_missing",
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": _now_iso(),
            "tool_version": __version__,
            "git_sha": _resolve_git_sha(_repo_root()),
            "source": {
                "source_ref": maps_url,
                "place_id": place_id,
                "canonical_domain": "",
                "website_source": "places",
                "resolver_notes": "Places had no websiteUri.",
            },
            "hiring": {"status": "uncertain", "confidence": 0.0, "signals": [], "evidence": []},
            "industry": {"labels": [], "confidence": 0.0, "evidence": []},
            "roles": {"detected": [], "fit": {"score": 0, "green_flags": [], "red_flags": [], "evidence": []}},
            "links": {"maps_url": maps_url, "website_url": "", "careers_urls": [], "ats_urls": [], "contact_url": ""},
            "next_action": next_action,
            "safety": {
                "robots_respected": "unknown",
                "pages_fetched": 0,
            "skipped_reasons": [],
            "errors": ["website_missing"],
            "checked_urls": [],
            "cookie_wall": _default_cookie_wall(),
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
        return {"run_id": run_id, "status": "degraded"}

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
    pipeline_status = "ok"
    degraded_reason = "none"
    next_action = ""
    if scan_outcome.cookie_wall.get("detected") and not scan_outcome.results_found:
        pipeline_status = "degraded"
        degraded_reason = "cookie_wall"
        next_action = "Cookie wall detected. Open site manually and retry."

    package = build_company_package(
        run_id=run_id,
        maps_url=maps_url,
        place_id=place_id,
        website_url=website_url,
        domain=domain,
        website_source="places",
        resolver_notes="Resolved via Places websiteUri.",
        scan_config=scan_config,
        scan_result=scan_outcome.selected,
        checked_urls=scan_outcome.checked_urls,
        errors=scan_outcome.errors,
        skipped_reasons=scan_outcome.skipped_reasons,
        pages_fetched=scan_outcome.pages_fetched,
        note=note,
        tags=tags,
        pipeline_status=pipeline_status,
        degraded_reason=degraded_reason,
        cookie_wall=scan_outcome.cookie_wall,
        next_action=next_action,
    )
    write_company_package(run_id, package)
    return {"run_id": run_id, "status": pipeline_status}
