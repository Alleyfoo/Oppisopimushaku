"""LLM-assisted hiring signal scan for company websites."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

from . import __version__
from .domains_discovery import COMMON_PATHS, contains_job_signal
from .jobs.ats import detect_ats
from .jobs.constants import ROBOTS_DISALLOW_ALL, ROBOTS_DISALLOW_URL
from .jobs.fetch import fetch_url
from .jobs.robots import RobotsChecker


PROMPT_SYSTEM = (
    "You classify if a company page indicates hiring or recruiting. "
    "Return ONLY JSON with keys: hiring_signal (yes|no|unclear), confidence (0-1), "
    "evidence (short phrase), evidence_snippets (list of 2-6 short snippets), "
    "evidence_urls (list of URLs), next_url_hint (optional)."
)
PROMPT_VERSION = hashlib.sha256(PROMPT_SYSTEM.encode("utf-8")).hexdigest()[:8]
EVIDENCE_KEYWORDS = [
    "open positions",
    "open roles",
    "openings",
    "apply",
    "job",
    "jobs",
    "career",
    "careers",
    "hiring",
    "rekry",
    "rekrytointi",
    "ura",
    "tyopaikat",
    "avoin tehtava",
    "hae tahan",
]
COOKIE_WALL_KEYWORDS = [
    "cookie",
    "cookies",
    "we use cookies",
    "accept all",
    "reject all",
    "manage preferences",
    "consent",
    "gdpr",
    "eväste",
    "evästeet",
    "hyväksy evästeet",
    "salli kaikki",
    "hylkää kaikki",
    "tietosuoj",
]
NEGATIVE_KEYWORDS = [
    "no open positions",
    "no openings",
    "no vacancies",
    "no open roles",
    "not hiring",
    "not recruiting",
    "ei avoimia",
    "ei avoimia paikkoja",
]


@dataclass
class ScanConfig:
    master_path: Path
    sheet: str
    domains_path: Path
    station: str
    max_distance_km: float
    limit: int
    max_urls: int
    sleep_s: float
    output_format: str
    robots_mode: str
    robots_allowlist: Path | None
    deterministic: bool
    out_path: Path
    env_file: Path | None
    ollama_host: str
    ollama_model: str
    ollama_options: Dict[str, Any]
    ollama_temperature: float
    prompt_version: str
    use_llm: bool
    run_id: str


@dataclass
class DomainScanResult:
    selected: Dict[str, Any]
    checked_urls: list[str]
    errors: list[str]
    skipped_reasons: list[str]
    pages_fetched: int
    results_found: bool
    cookie_wall: Dict[str, Any]


def _load_env_file(path: Path | None) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not path or not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _clean_domain(val: object) -> str:
    raw = str(val or "").strip()
    if not raw or raw.lower() in {"nan", "none", "null"}:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = parsed.netloc or parsed.path
    return host.split("/")[0].strip()


def _load_domain_map(path: Path | None) -> Dict[str, str]:
    if path is None or not path.exists():
        return {}
    df = pd.read_csv(path)
    if "business_id" not in df.columns or "domain" not in df.columns:
        return {}
    dom_map = {}
    for _, row in df.iterrows():
        bid = str(row.get("business_id") or "").strip()
        domain = _clean_domain(row.get("domain"))
        if bid and domain:
            dom_map[bid] = domain
    return dom_map


def _extract_text(html: str, max_chars: int = 6000) -> Tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "").strip()
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.stripped_strings)
    if len(text) > max_chars:
        text = text[:max_chars]
    return title, text


def _extract_snippets(text: str, keywords: list[str], max_snippets: int = 4, window: int = 80) -> list[str]:
    lowered = text.lower()
    snippets: list[str] = []
    for key in keywords:
        idx = lowered.find(key)
        if idx == -1:
            continue
        start = max(0, idx - window)
        end = min(len(text), idx + window)
        snippet = text[start:end].strip()
        if snippet and snippet not in snippets:
            snippets.append(snippet)
        if len(snippets) >= max_snippets:
            break
    return snippets


def _cookie_wall_threshold() -> dict[str, float | int]:
    return {"hits_min": 2, "score_min": 0.4, "text_max_len": 2000, "hits_hard": 5}


def _cookie_wall_signals(
    title: str, text: str
) -> tuple[bool, int, float, list[str], list[str], dict[str, float | int]]:
    combined = f"{title} {text}".lower()
    matches = [key for key in COOKIE_WALL_KEYWORDS if key in combined]
    hits = len(matches)
    score = min(1.0, hits / 5.0) if hits else 0.0
    threshold = _cookie_wall_threshold()
    is_wall = (
        hits >= threshold["hits_min"]
        and score >= threshold["score_min"]
        and len(text) < threshold["text_max_len"]
    ) or hits >= threshold["hits_hard"]
    signals = []
    if any(key in combined for key in ("cookie", "cookies", "we use cookies", "eväste", "evästeet")):
        signals.append("cookie_banner")
    if any(key in combined for key in ("consent", "gdpr", "manage preferences", "tietosuoj")):
        signals.append("consent_manager")
    if any(key in combined for key in ("accept all", "reject all", "salli kaikki", "hylkää kaikki")):
        signals.append("cookie_actions")
    return is_wall, hits, score, matches, signals, threshold


def _load_allowlist(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(line.lower())
    return set(items)


def _normalize_skip_reason(reason: str | None) -> str:
    if not reason:
        return ""
    if reason == "Disallow: /":
        return ROBOTS_DISALLOW_ALL
    if reason in {"blocked_by_robots", "robots_disallow"}:
        return ROBOTS_DISALLOW_URL
    return reason


def scan_domain(
    *,
    domain: str,
    name: str,
    website_url: str | None,
    max_urls: int,
    sleep_s: float,
    robots_mode: str,
    robots_allowlist: Path | None,
    session: requests.Session | None,
    rate_limit_state: Dict[str, float] | None,
    ollama_host: str,
    ollama_model: str,
    ollama_options: Dict[str, Any],
    use_llm: bool,
) -> DomainScanResult:
    allowlist = _load_allowlist(robots_allowlist)
    robots = None if robots_mode == "off" else RobotsChecker(user_agent="apprscan-scan")
    rate_limit_state = rate_limit_state or {}
    session = session or requests.Session()

    candidates = _build_candidates(domain, website_url)[: int(max_urls)]
    checked_urls: list[str] = []
    errors: list[str] = []
    skip_reasons: list[str] = []
    results: list[Dict[str, Any]] = []
    pages_fetched = 0
    cookie_wall = {
        "detected": False,
        "score": 0.0,
        "hit_count": 0,
        "signals": [],
        "threshold": _cookie_wall_threshold(),
        "sample_title": "",
        "matches": [],
    }

    for url in candidates:
        robots_override = robots_mode == "allowlist" and domain.lower() in allowlist
        if robots and not robots_override:
            allowed, reason = robots.can_fetch_detail(url)
            if not allowed:
                checked_urls.append(url)
                normalized = _normalize_skip_reason(reason or "blocked_by_robots")
                skip_reasons.append(normalized)
                errors.append(f"{url}:{normalized}")
                continue
        res, fetch_reason = fetch_url(
            session,
            url,
            rate_limit_state=rate_limit_state,
            req_per_second_per_domain=0.5,
            robots=None if robots_override else robots,
            max_bytes=2_000_000,
        )
        if res is None:
            checked_urls.append(url)
            normalized = _normalize_skip_reason(fetch_reason or "fetch_failed")
            skip_reasons.append(normalized)
            errors.append(f"{url}:{normalized}")
            continue
        pages_fetched += 1
        checked_urls.append(res.final_url)
        title, text = _extract_text(res.html)
        is_wall, hits, score, matches, signals, threshold = _cookie_wall_signals(title, text)
        if is_wall:
            matched = ",".join(matches[:5])
            errors.append(f"{res.final_url}:cookie_wall:{hits}:{score:.2f}:{matched}")
            if not cookie_wall["detected"] or score > cookie_wall["score"]:
                cookie_wall.update(
                    {
                        "detected": True,
                        "score": score,
                        "hit_count": hits,
                        "signals": signals,
                        "threshold": threshold,
                        "sample_title": title[:120],
                        "matches": matches[:5],
                    }
                )
            continue
        heuristic = evaluate_html(res.html, res.final_url)
        if heuristic["signal"] == "yes":
            results.append(
                {
                    "hiring_signal": "yes",
                    "confidence": heuristic["confidence"],
                    "evidence": heuristic["evidence"],
                    "evidence_snippets": heuristic.get("evidence_snippets") or [],
                    "evidence_urls": heuristic.get("evidence_urls") or [res.final_url],
                    "next_url_hint": "",
                    "url_checked": res.final_url,
                }
                )
            continue
        if use_llm and ollama_model:
            try:
                result = _evaluate_page(
                    res.final_url,
                    title,
                    text,
                    company_name=name,
                    host=ollama_host,
                    model=ollama_model,
                    options=ollama_options,
                )
                if not result.get("evidence_urls"):
                    result["evidence_urls"] = [res.final_url]
                if "evidence_snippets" not in result:
                    result["evidence_snippets"] = _extract_snippets(text, EVIDENCE_KEYWORDS, max_snippets=3)
                result["url_checked"] = res.final_url
                result = _ensure_evidence(result)
                results.append(result)
            except Exception as exc:
                errors.append(f"{res.final_url}:{exc}")
        else:
            results.append(
                {
                    "hiring_signal": "unclear",
                    "confidence": 0.0,
                    "evidence": "",
                    "evidence_snippets": [],
                    "evidence_urls": [res.final_url],
                    "next_url_hint": "",
                    "url_checked": res.final_url,
                }
            )
        if sleep_s:
            time.sleep(sleep_s)

    selected = _select_result(results)
    return DomainScanResult(
        selected=selected,
        checked_urls=checked_urls,
        errors=errors,
        skipped_reasons=skip_reasons,
        pages_fetched=pages_fetched,
        results_found=bool(results),
        cookie_wall=cookie_wall,
    )


def _ensure_evidence(result: Dict[str, Any]) -> Dict[str, Any]:
    signal = str(result.get("hiring_signal") or result.get("signal") or "").lower()
    if signal not in {"yes", "no"}:
        return result
    snippets = result.get("evidence_snippets") or []
    urls = result.get("evidence_urls") or []
    if not isinstance(snippets, list):
        snippets = []
    if not isinstance(urls, list):
        urls = []
    snippets = [str(s).strip() for s in snippets if str(s).strip()]
    urls = [str(u).strip() for u in urls if str(u).strip()]
    if len(snippets) > 6:
        snippets = snippets[:6]
    if len(snippets) < 2 or not urls:
        result["hiring_signal"] = "unclear"
        result["confidence"] = min(float(result.get("confidence") or 0.0), 0.2)
        result["evidence"] = "insufficient_evidence"
        result["evidence_snippets"] = []
        result["evidence_urls"] = []
        return result

    def _has_keyword(items: list[str], keywords: list[str]) -> bool:
        return any(k in snippet.lower() for snippet in items for k in keywords)

    if signal == "yes" and not _has_keyword(snippets, EVIDENCE_KEYWORDS):
        result["hiring_signal"] = "unclear"
        result["confidence"] = min(float(result.get("confidence") or 0.0), 0.2)
        result["evidence"] = "generic_evidence"
        result["evidence_snippets"] = []
        result["evidence_urls"] = []
        return result

    if signal == "no" and not _has_keyword(snippets, NEGATIVE_KEYWORDS):
        result["hiring_signal"] = "unclear"
        result["confidence"] = min(float(result.get("confidence") or 0.0), 0.2)
        result["evidence"] = "generic_evidence"
        result["evidence_snippets"] = []
        result["evidence_urls"] = []
        return result

    result["evidence_snippets"] = snippets
    result["evidence_urls"] = urls
    return result


def _build_candidates(domain: str, website_url: str | None) -> list[str]:
    candidates: list[str] = []
    base = f"https://{domain}"
    if website_url:
        url = str(website_url).strip()
        if url and "://" not in url:
            url = f"https://{url}"
        if url:
            candidates.append(url)
    # Prioritize at least one careers-like path early.
    if COMMON_PATHS:
        candidates.append(f"{base}{COMMON_PATHS[0]}")
    candidates.append(base)
    for path in COMMON_PATHS[1:]:
        candidates.append(f"{base}{path}")
    seen = set()
    ordered = []
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        ordered.append(url)
    return ordered


def _ollama_chat(host: str, model: str, system: str, user: str, options: Dict[str, Any]) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": options,
    }
    url = host.rstrip("/") + "/api/chat"
    resp = requests.post(url, json=payload, timeout=90)
    if resp.status_code >= 400:
        raise RuntimeError(f"ollama_http_{resp.status_code}")
    data = resp.json()
    content = data.get("message", {}).get("content")
    if not isinstance(content, str):
        raise RuntimeError("ollama_empty_response")
    return content


def _parse_json(content: str) -> Dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(content[start : end + 1])
    raise json.JSONDecodeError("No JSON block", content, 0)


def evaluate_html(html: str, url: str) -> Dict[str, Any]:
    title, text = _extract_text(html)
    detected = detect_ats(url, html)
    if detected:
        evidence_snippets = [
            f"ATS detected: {detected.get('kind')}",
            "ATS job board link found",
        ]
        return {
            "signal": "yes",
            "confidence": 0.9,
            "evidence": f"ats:{detected.get('kind')}",
            "evidence_snippets": evidence_snippets,
            "evidence_urls": [url],
        }
    if "jobposting" in html.lower():
        return {
            "signal": "yes",
            "confidence": 0.8,
            "evidence": "jobposting_structured_data",
            "evidence_snippets": ["JobPosting structured data found", f"Title: {title}"],
            "evidence_urls": [url],
        }
    if contains_job_signal(html):
        snippets = _extract_snippets(text, EVIDENCE_KEYWORDS, max_snippets=3)
        if len(snippets) < 2:
            return {"signal": "unclear", "confidence": 0.2, "evidence": "weak_job_signal"}
        return {
            "signal": "yes",
            "confidence": 0.7,
            "evidence": "job_signal_keywords",
            "evidence_snippets": snippets[:3],
            "evidence_urls": [url],
        }
    return {"signal": "unclear", "confidence": 0.0, "evidence": ""}


def _evaluate_page(
    url: str,
    title: str,
    text: str,
    *,
    company_name: str,
    host: str,
    model: str,
    options: Dict[str, Any],
) -> Dict[str, Any]:
    system = PROMPT_SYSTEM
    user = (
        f"Company: {company_name}\n"
        f"URL: {url}\n"
        f"Title: {title}\n"
        "Page text snippet:\n"
        f"{text}\n\n"
        "Decision rules:\n"
        "- yes: explicit hiring, careers, open positions, job listings, 'rekry', 'ura', 'tyopaikat'.\n"
        "- no: clearly not hiring and no recruiting content.\n"
        "- unclear: insufficient or ambiguous.\n"
        "- evidence must include 2-6 snippets + URLs; otherwise return unclear.\n"
    )
    raw = _ollama_chat(host, model, system, user, options)
    return _parse_json(raw)


def _score_signal(signal: str) -> int:
    if signal == "yes":
        return 2
    if signal == "unclear":
        return 1
    return 0


def _select_result(results: list[Dict[str, Any]]) -> Dict[str, Any]:
    if not results:
        return {"hiring_signal": "unclear", "confidence": 0.0}

    def _key(item: Dict[str, Any]) -> Tuple[int, float]:
        signal = str(item.get("hiring_signal") or item.get("signal") or "").lower()
        conf = float(item.get("confidence") or 0.0)
        return (_score_signal(signal), conf)

    return sorted(results, key=_key, reverse=True)[0]


def _load_master(path: Path, sheet: str) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        try:
            return pd.read_excel(path, sheet_name=sheet)
        except ValueError:
            return pd.read_excel(path, sheet_name=0)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    raise ValueError("Unsupported master format (use xlsx/csv/parquet).")


def _resolve_git_sha(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except Exception:
        return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_config(args: argparse.Namespace) -> ScanConfig:
    repo_root = _repo_root()
    env_file = Path(args.env_file) if args.env_file else (repo_root / ".env" if (repo_root / ".env").exists() else None)
    env = _load_env_file(env_file)

    ollama_host = args.ollama_host or env.get("OLLAMA_URL") or env.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
    ollama_model = args.ollama_model or env.get("MODEL_NAME") or env.get("OLLAMA_MODEL") or ""
    if "ollama:11434" in ollama_host:
        ollama_host = "http://127.0.0.1:11434"
    options: Dict[str, Any] = {"temperature": 0.2, "num_predict": 400}
    if env.get("OLLAMA_OPTIONS"):
        try:
            options.update(json.loads(env["OLLAMA_OPTIONS"]))
        except json.JSONDecodeError:
            pass
    if args.ollama_options:
        try:
            options.update(json.loads(args.ollama_options))
        except json.JSONDecodeError:
            pass
    if args.deterministic:
        options["temperature"] = 0.0
    run_id = args.run_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    ollama_temperature = float(options.get("temperature", 0.0))

    return ScanConfig(
        master_path=Path(args.master),
        sheet=args.sheet,
        domains_path=Path(args.domains),
        station=str(args.station or "").strip(),
        max_distance_km=float(args.max_distance_km),
        limit=int(args.limit),
        max_urls=int(args.max_urls),
        sleep_s=float(args.sleep_s),
        output_format=str(args.format).lower(),
        robots_mode=str(args.robots_mode).lower(),
        robots_allowlist=Path(args.robots_allowlist) if args.robots_allowlist else None,
        deterministic=bool(args.deterministic),
        out_path=Path(args.out),
        env_file=env_file,
        ollama_host=ollama_host,
        ollama_model=ollama_model,
        ollama_options=options,
        ollama_temperature=ollama_temperature,
        prompt_version=PROMPT_VERSION,
        use_llm=not args.no_llm,
        run_id=run_id,
    )


def run_scan(config: ScanConfig) -> int:
    if not config.station:
        print("Station filter is required.")
        return 2
    if config.use_llm and not config.ollama_model:
        print("Missing ollama model name (set MODEL_NAME/OLLAMA_MODEL or --ollama-model).")
        return 2

    master = _load_master(config.master_path, config.sheet)
    domain_map = _load_domain_map(config.domains_path)

    station_mask = master.get("nearest_station").astype(str).str.lower() == config.station.lower()
    dist_mask = pd.to_numeric(master.get("distance_km"), errors="coerce") <= float(config.max_distance_km)
    filtered = master[station_mask & dist_mask].copy()

    def _resolve_domain(row: pd.Series) -> str:
        bid = str(row.get("business_id") or "").strip()
        domain = domain_map.get(bid, "")
        if domain:
            return domain
        return _clean_domain(row.get("website.url") or "")

    filtered["domain"] = filtered.apply(_resolve_domain, axis=1)
    filtered = filtered[filtered["domain"].astype(str).str.strip() != ""]
    if filtered.empty:
        print("No rows match station + distance + domain filters.")
        return 1

    target = filtered.head(int(config.limit))
    rate_limit_state: Dict[str, float] = {}
    crawl_ts = _now_iso()
    git_sha = _resolve_git_sha(_repo_root())
    session = requests.Session()

    rows: list[Dict[str, Any]] = []
    for _, row in target.iterrows():
        bid = str(row.get("business_id") or "").strip()
        name = str(row.get("name") or "")
        domain = str(row.get("domain") or "").strip()
        website_url = row.get("website.url")
        scan_result = scan_domain(
            domain=domain,
            name=name,
            website_url=website_url,
            max_urls=config.max_urls,
            sleep_s=config.sleep_s,
            robots_mode=config.robots_mode,
            robots_allowlist=config.robots_allowlist,
            session=session,
            rate_limit_state=rate_limit_state,
            ollama_host=config.ollama_host,
            ollama_model=config.ollama_model,
            ollama_options=config.ollama_options,
            use_llm=config.use_llm,
        )
        selected = scan_result.selected
        skipped_reason = ""
        if not scan_result.results_found and scan_result.skipped_reasons:
            skipped_reason = ";".join(sorted(set(scan_result.skipped_reasons)))
            print(f"Skipped {domain}: {skipped_reason}")
        rows.append(
            {
                "run_id": config.run_id,
                "tool_version": __version__,
                "git_sha": git_sha,
                "crawl_ts": crawl_ts,
                "station": config.station,
                "max_distance_km": config.max_distance_km,
                "business_id": bid,
                "name": name,
                "domain": domain,
                "signal": str(selected.get("hiring_signal") or selected.get("signal") or "").lower(),
                "confidence": selected.get("confidence"),
                "evidence": selected.get("evidence") or "",
                "evidence_snippets": selected.get("evidence_snippets") or [],
                "evidence_urls": selected.get("evidence_urls") or [],
                "signal_url": selected.get("url_checked") or "",
                "checked_urls": ";".join(scan_result.checked_urls),
                "next_url_hint": selected.get("next_url_hint") or "",
                "errors": ";".join(scan_result.errors),
                "skipped_reason": skipped_reason,
                "ollama_model": config.ollama_model or "",
                "ollama_temperature": config.ollama_temperature,
                "prompt_version": config.prompt_version,
                "deterministic": bool(config.deterministic),
                "llm_used": bool(config.use_llm),
                "output_format": config.output_format,
            }
        )

    config.out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    if config.output_format == "jsonl":
        df.to_json(config.out_path, orient="records", lines=True, force_ascii=False)
    else:
        for col in ("evidence_snippets", "evidence_urls"):
            df[col] = df[col].apply(lambda val: json.dumps(val, ensure_ascii=False))
        df.to_csv(config.out_path, index=False)
    print(f"Wrote hiring signals: {config.out_path} ({len(rows)} rows)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LLM-assisted hiring signal scan (Ollama).")
    parser.add_argument("--master", default="out/master_places.xlsx", help="Master file (xlsx/csv/parquet).")
    parser.add_argument("--sheet", default="Shortlist", help="Sheet name when using xlsx.")
    parser.add_argument("--domains", default="domains.csv", help="Domain mapping CSV.")
    parser.add_argument("--station", default="Lahti", help="Nearest station filter.")
    parser.add_argument("--max-distance-km", type=float, default=1.0, help="Distance threshold in km.")
    parser.add_argument("--limit", type=int, default=10, help="Max companies to process.")
    parser.add_argument("--max-urls", type=int, default=2, help="Max URLs to check per company.")
    parser.add_argument("--sleep-s", type=float, default=1.0, help="Sleep between HTTP fetches.")
    parser.add_argument("--out", default="out/hiring_signal_lahti.csv", help="Output file.")
    parser.add_argument("--format", default="csv", choices=["csv", "jsonl"], help="Output format.")
    parser.add_argument(
        "--robots-mode",
        default="strict",
        choices=["strict", "allowlist", "off"],
        help="Robots handling (strict/allowlist/off).",
    )
    parser.add_argument("--robots-allowlist", default="", help="Optional allowlist file for robots override.")
    parser.add_argument("--env-file", default="", help="Optional .env path (defaults to repo .env).")
    parser.add_argument("--ollama-host", default="", help="Ollama host (override).")
    parser.add_argument("--ollama-model", default="", help="Ollama model (override).")
    parser.add_argument("--ollama-options", default="", help="JSON options for Ollama (override).")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM and use heuristics only.")
    parser.add_argument("--deterministic", action="store_true", help="Set deterministic LLM options (temp=0).")
    parser.add_argument("--run-id", default="", help="Optional run identifier for outputs.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    config = build_config(args)
    return run_scan(config)
