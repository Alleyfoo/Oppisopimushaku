# -*- coding: utf-8 -*-
"""Command-line interface for apprscan."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

import pandas as pd

from . import __version__
from .distance import nearest_station_from_df
from .geocode import geocode_address
from . import normalize
from .normalize import normalize_companies
from .prh_client import fetch_companies
from .report import export_reports
from .stations import load_stations


def parse_csv_list(val: str) -> list[str]:
    return [x.strip() for x in val.split(",") if x.strip()] if val else []


def merge_cities(cities_csv: str, cities_repeat: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in parse_csv_list(cities_csv) + [c.strip() for c in (cities_repeat or []) if c and c.strip()]:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def add_watch_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "watch",
        help="Generate watch report from artifacts (no crawl).",
        description="Reads master + diff and writes a text report using the same filters as Streamlit.",
    )
    p.add_argument("--run-xlsx", "--master", dest="run_xlsx", type=str, default=None, help="Master workbook (auto-resolve if omitted).")
    p.add_argument("--jobs-diff", "--diff", dest="jobs_diff", type=str, default=None, help="diff.xlsx (auto-resolve if omitted).")
    p.add_argument("--profile", type=str, default=None, help="Profile name (config/profiles.yaml).")
    p.add_argument("--include-tags", type=str, default="", help="Comma-separated required tags.")
    p.add_argument("--exclude-tags", type=str, default="", help="Comma-separated banned keywords.")
    p.add_argument("--max-items", type=int, default=0, help="Max rows in report (0=all).")
    p.add_argument("--min-score", type=float, default=None, help="Minimum score.")
    p.add_argument("--max-distance-km", type=float, default=None, help="Maximum distance in km.")
    p.add_argument("--stations", type=str, default="", help="Comma-separated stations.")
    p.add_argument("--cities", type=str, default="", help="Comma-separated cities (city/_source_city).")
    p.add_argument("--city", action="append", default=[], help="Repeatable city filter.")
    p.add_argument("--only-recruiting", action="store_true", help="Only recruiting_active.")
    p.add_argument("--include-hidden", action="store_true", help="Include hidden rows.")
    p.add_argument("--include-excluded", action="store_true", help="Include excluded rows.")
    p.add_argument("--search", type=str, default="", help="Free-text search.")
    p.add_argument("--out", type=str, default="out/watch_report.txt", help="Output file.")
    p.set_defaults(func=watch_command)
    return p


def add_map_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "map",
        help="Render jobs_map.html from artifacts (no crawl).",
        description="Interactive HTML map using the same effective view as Streamlit.",
    )
    p.add_argument("--master", type=str, default=None, help="Master workbook (auto-resolve if omitted).")
    p.add_argument("--curation", type=str, default=None, help="Curation CSV (optional).")
    p.add_argument("--jobs-diff", "--diff", dest="jobs_diff", type=str, default=None, help="diff.xlsx (auto-resolve if omitted).")
    p.add_argument("--out", type=str, default="out/jobs_map.html", help="Output HTML map.")
    p.add_argument("--mode", type=str, default="jobs", choices=["jobs", "companies"], help="Map mode.")
    p.add_argument("--sheet", type=str, default="Shortlist", help="Sheet masterista (Shortlist/Excluded/all).")
    p.add_argument("--nace-prefix", type=str, default="", help="Comma-separated TOL/NACE prefixes (e.g. 62,63).")
    p.add_argument("--cities", type=str, default="", help="Comma-separated cities (city/_source_city).")
    p.add_argument("--city", action="append", default=[], help="Repeatable city filter.")
    p.add_argument("--only-recruiting", action="store_true", help="Only recruiting_active.")
    p.add_argument("--min-score", type=float, default=None, help="Minimum score.")
    p.add_argument("--max-distance-km", type=float, default=None, help="Maximum distance km.")
    p.add_argument("--out-dir", type=str, default="out", help="Artifacts root (default out).")
    p.add_argument("--run-id", type=str, default=None, help="Run-id (YYYYMMDD) master/diff-valintaan.")
    p.add_argument("--industries", type=str, default="", help="Comma-separated industry groups (yaml names).")
    p.add_argument("--include-housing", action="store_true", help="Include housing-like companies.")
    p.add_argument("--pin-scale", type=str, choices=["log", "linear"], default="log", help="Pin radius scaling.")
    p.add_argument("--pin-size", type=float, default=1.0, help="Pin size multiplier (e.g. 0.5-3.0 recommended).")
    p.set_defaults(func=map_command)
    return p


def add_scan_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "scan",
        help="LLM-assisted hiring signal scan (Ollama).",
        description="Scan company websites for hiring signals using local Ollama.",
    )
    p.add_argument("--master", type=str, default="out/master_places.xlsx", help="Master file (xlsx/csv/parquet).")
    p.add_argument("--sheet", type=str, default="Shortlist", help="Sheet name when using xlsx.")
    p.add_argument("--domains", type=str, default="domains.csv", help="Domain mapping CSV.")
    p.add_argument("--station", type=str, default="Lahti", help="Nearest station filter.")
    p.add_argument("--max-distance-km", type=float, default=1.0, help="Distance threshold in km.")
    p.add_argument("--limit", type=int, default=10, help="Max companies to process.")
    p.add_argument("--max-urls", type=int, default=2, help="Max URLs to check per company.")
    p.add_argument("--sleep-s", type=float, default=1.0, help="Sleep between HTTP fetches.")
    p.add_argument("--out", type=str, default="out/hiring_signal_lahti.csv", help="Output file.")
    p.add_argument("--format", type=str, default="csv", choices=["csv", "jsonl"], help="Output format.")
    p.add_argument(
        "--robots-mode",
        type=str,
        default="strict",
        choices=["strict", "allowlist", "off"],
        help="Robots handling (strict/allowlist/off).",
    )
    p.add_argument("--robots-allowlist", type=str, default="", help="Optional allowlist file for robots override.")
    p.add_argument("--env-file", type=str, default="", help="Optional .env path (defaults to repo .env).")
    p.add_argument("--ollama-host", type=str, default="", help="Ollama host (override).")
    p.add_argument("--ollama-model", type=str, default="", help="Ollama model (override).")
    p.add_argument("--ollama-options", type=str, default="", help="JSON options for Ollama (override).")
    p.add_argument("--no-llm", action="store_true", help="Skip LLM and use heuristics only.")
    p.add_argument("--deterministic", action="store_true", help="Set deterministic LLM options (temp=0).")
    p.add_argument("--run-id", type=str, default="", help="Optional run identifier for outputs.")
    p.set_defaults(func=scan_command)
    return p


def add_check_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "check",
        help="Run repo health checks (tests, fixtures, schema, env).",
        description="Gate command to validate tests, fixtures, schema, and Ollama sanity.",
    )
    p.add_argument("--env-file", type=str, default="", help="Optional .env path (defaults to repo .env).")
    p.set_defaults(func=check_command)
    return p


def add_serve_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "serve",
        help="Run companion service for Maps ingest (localhost only).",
        description="Starts a local FastAPI server for URL-only ingest from Google Maps.",
    )
    p.add_argument("--host", type=str, default="127.0.0.1", help="Bind host (default 127.0.0.1).")
    p.add_argument("--port", type=int, default=8787, help="Bind port (default 8787).")
    p.add_argument("--token", type=str, default="", help="Optional API token (else random).")
    p.set_defaults(func=serve_command)
    return p


def _load_domain_map(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    df = pd.read_csv(path)
    if "business_id" not in df.columns or "domain" not in df.columns:
        return {}
    dom_map = {}
    for _, row in df.iterrows():
        bid = str(row.get("business_id") or "").strip()
        domain = str(row.get("domain") or "").strip()
        if bid and domain and domain.lower() not in {"nan", "none", "null"}:
            dom_map[bid] = domain
    return dom_map


def _clean_domain(val: object) -> str:
    raw = str(val or "").strip()
    if not raw or raw.lower() in {"nan", "none", "null"}:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = parsed.netloc or parsed.path
    host = host.split("/")[0].strip()
    return host


def _extract_domain_from_row(row: pd.Series) -> str:
    for key in ("domain", "company_domain", "website.url", "website"):
        if key in row and row.get(key):
            domain = _clean_domain(row.get(key))
            if domain:
                return domain
    return ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apprscan",
        description="Local hiring signal scanner (Places -> domains -> Ollama), with optional PRH/jobs tooling.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=False)

    # Jobs subcommand
    jobs_parser = subparsers.add_parser(
        "jobs",
        help="Hae tyopaikat yritysten urasivuilta.",
        description="Crawlaa urasivuja (domain mapping + heuristiikat) ja normalisoi JobPosting-rivit.",
    )
    jobs_parser.add_argument("--companies", type=str, required=True, help="Yritystiedosto (xlsx/csv/parquet).")
    jobs_parser.add_argument("--domains", type=str, default=None, help="Domain mapping CSV (business_id,domain).")
    jobs_parser.add_argument(
        "--suggested",
        type=str,
        default=None,
        help="domains_suggested.csv fallback; kaytetaan jos varsinaisesta domain-mapista puuttuu.",
    )
    jobs_parser.add_argument("--out", type=str, default="out/jobs", help="Output-hakemisto.")
    jobs_parser.add_argument("--max-domains", type=int, default=300, help="Maksimi domainit per ajo.")
    jobs_parser.add_argument(
        "--max-pages-per-domain", type=int, default=30, help="Maksimi sivut per domain (guardrail)."
    )
    jobs_parser.add_argument("--rate-limit", type=float, default=1.0, help="Pyyntoja per sekunti / domain.")
    jobs_parser.add_argument("--debug-html", action="store_true", help="Tallenna raaka HTML out/jobs/raw/.")
    jobs_parser.add_argument(
        "--only-shortlist",
        action="store_true",
        default=True,
        help="Lue vain Shortlist-valilehti companies-tiedostosta (xlsx).",
    )
    jobs_parser.add_argument(
        "--known-jobs",
        type=str,
        default="out/jobs/known_jobs.parquet",
        help="Polku aikaisempiin job_url-arvoihin diffia varten.",
    )
    jobs_parser.set_defaults(func=jobs_command)

    domains_parser = subparsers.add_parser(
        "domains",
        help="Luo domain-mapping -pohja companies tiedostosta.",
        description="Lue companies (xlsx/csv/parquet) ja kirjoita CSV (business_id,name,domain) taytettavaksi.",
    )
    domains_parser.add_argument("--companies", type=str, required=True, help="Yritystiedosto (xlsx/csv/parquet).")
    domains_parser.add_argument("--out", type=str, default="domains.csv", help="Output CSV polku.")
    domains_parser.add_argument(
        "--only-shortlist",
        action="store_true",
        default=True,
        help="Lue vain Shortlist sheet xlsx-tiedostosta.",
    )
    domains_parser.add_argument(
        "--suggest",
        action="store_true",
        help="Yrita loytaa urasivudomainit automaattisesti (kirjoittaa domains_suggested.csv).",
    )
    domains_parser.add_argument("--max-companies", type=int, default=200, help="Maksimi yrityksia discoveryyn.")
    domains_parser.add_argument(
        "--validate",
        action="store_true",
        help="Validoi olemassa oleva domains CSV (HTTP-status, redirect, consent) ja kirjoita domains_validated.csv.",
    )
    domains_parser.add_argument(
        "--domains",
        type=str,
        default=None,
        help="Olemassa oleva domains CSV validointia varten (business_id,domain). Oletus: --out tiedosto.",
    )
    domains_parser.set_defaults(func=domains_command)

    add_watch_parser(subparsers)
    add_scan_parser(subparsers)
    add_check_parser(subparsers)
    add_serve_parser(subparsers)

    analytics_parser = subparsers.add_parser(
        "analytics",
        help="Tuota analytics.xlsx olemassa olevista artefakteista.",
        description="Laskee KPI:t, asema- ja tagiyhteenvedot master/jobs/diff -tiedostoista.",
    )
    analytics_parser.add_argument("--master-xlsx", type=str, required=True, help="Polku master.xlsx:aan (Shortlist).")
    analytics_parser.add_argument(
        "--jobs-xlsx", type=str, required=True, help="Polku jobs.xlsx/jsonl (kaikki tyopaikat)."
    )
    analytics_parser.add_argument("--jobs-diff", type=str, required=True, help="Polku diff-tiedostoon (uudet tyopaikat).")
    analytics_parser.add_argument("--out", type=str, default="out/analytics.xlsx", help="Output tiedosto (xlsx).")
    analytics_parser.set_defaults(func=analytics_command)

    add_map_parser(subparsers)

    run_parser = subparsers.add_parser(
        "run",
        help="Legacy PRH/YTJ run (optional).",
        description=(
            "Legacy: fetch PRH/YTJ companies, geocode addresses, and produce reports (Excel/GeoJSON/HTML)."
        ),
    )
    run_parser.add_argument(
        "--cities",
        type=str,
        help="Pilkuilla erotettu kaupunkilista (esim. Helsinki,Espoo,Vantaa,Lahti).",
    )
    run_parser.add_argument(
        "--radius-km",
        type=float,
        default=1.0,
        help="Suurin etaisyys (km) lahimmalle asemalle.",
    )
    run_parser.add_argument(
        "--main-business-line",
        type=str,
        default="",
        help="PRH mainBusinessLine -suodatin.",
    )
    run_parser.add_argument("--reg-start", type=str, default="", help="registrationDateStart (YYYY-MM-DD).")
    run_parser.add_argument("--reg-end", type=str, default="", help="registrationDateEnd (YYYY-MM-DD).")
    run_parser.add_argument("--max-pages", type=int, default=0, help="Maksimi sivut per kaupunki (0 = kaikki).")
    run_parser.add_argument(
        "--stations-file",
        type=str,
        default=None,
        help="Paikallinen asemadata CSV (station_name,lat,lon). Oletus: data/stations_fi.csv jos loytyy.",
    )
    run_parser.add_argument("--skip-geocode", action="store_true", help="Ohita geokoodaus (debug / nopea ajo).")
    run_parser.add_argument("--out", type=str, default="out", help="Output-hakemisto raporteille.")
    run_parser.add_argument("--limit", type=int, default=0, help="Kasittele vain N ensimmaista rivia (debug).")
    run_parser.add_argument(
        "--geocode-cache",
        type=str,
        default="data/geocode_cache.sqlite",
        help="SQLite-valimuisti geokoodaukselle.",
    )
    run_parser.add_argument(
        "--whitelist",
        type=str,
        default="",
        help="Pilkuilla eroteltu toimiala-whitelist (mainBusinessLine substring).",
    )
    run_parser.add_argument(
        "--blacklist",
        type=str,
        default="",
        help="Pilkuilla eroteltu toimiala-blacklist (hard fail).",
    )
    run_parser.add_argument(
        "--include-excluded",
        action="store_true",
        help="Sisallyta poissuljetut rivit Exceliin (Excluded-valilehti).",
    )
    run_parser.add_argument(
        "--employee-csv",
        type=str,
        default=None,
        help="Tyontekijamaara-enrichment CSV (business_id, employee_count/employee_band).",
    )
    run_parser.add_argument(
        "--activity-file",
        type=str,
        default=None,
        help="Yritysten rekryaktiivisuus (company_activity.xlsx) jobs-ajosta.",
    )
    run_parser.add_argument(
        "--master-xlsx",
        type=str,
        default=None,
        help="Kirjoita lopullinen master-tyokirja (Shortlist, Excluded, Jobs_All, Jobs_New, Crawl_Stats, Activity).",
    )
    run_parser.add_argument(
        "--industry-config",
        type=str,
        default="config/industry_groups.yaml",
        help="Industry-ryhmakonfiguraatio (yaml).",
    )
    run_parser.add_argument(
        "--stations",
        type=str,
        default="",
        help="Pilkutetut asemat (filtteri raporttiin, ei hakua varten).",
    )
    run_parser.add_argument("--profile", type=str, default=None, help="Profiili (config/profiles.yaml).")
    run_parser.set_defaults(func=run_command)

    return parser


def jobs_command(args: argparse.Namespace) -> int:
    from .jobs import pipeline

    companies_path = Path(args.companies)
    if not companies_path.exists():
        print(f"Companies file not found: {companies_path}")
        return 1

    companies_df = pipeline.load_companies(companies_path, only_shortlist=args.only_shortlist)
    domain_map = _load_domain_map(Path(args.domains)) if args.domains else {}
    suggested_map = _load_domain_map(Path(args.suggested)) if args.suggested else None

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw" if args.debug_html else None

    jobs_df, stats_df, activity_df = pipeline.crawl_jobs_pipeline(
        companies_df,
        domain_map,
        suggested_map=suggested_map,
        max_domains=args.max_domains,
        max_pages_per_domain=args.max_pages_per_domain,
        req_per_second=args.rate_limit,
        debug_html=args.debug_html,
        out_raw_dir=raw_dir,
    )

    known_path = Path(args.known_jobs) if args.known_jobs else out_dir / "known_jobs.parquet"
    jobs_df, new_jobs = pipeline.apply_diff(jobs_df, known_path)

    jobs_out = out_dir / "jobs.xlsx"
    diff_out = out_dir / "diff.xlsx"
    stats_out = out_dir / "stats.xlsx"
    activity_out = out_dir / "company_activity.xlsx"

    jobs_df.to_excel(jobs_out, index=False)
    new_jobs.to_excel(diff_out, index=False)
    stats_df.to_excel(stats_out, index=False)
    activity_df.to_excel(activity_out, index=False)

    print(f"Jobs found: {len(jobs_df)} (new: {len(new_jobs)}); domains: {len(domain_map) or 0}; output: {out_dir}")
    return 0


def domains_command(args: argparse.Namespace) -> int:
    from .jobs import pipeline

    companies_path = Path(args.companies)
    if not companies_path.exists():
        print(f"Companies file not found: {companies_path}")
        return 1
    if companies_path.suffix.lower() in [".xlsx", ".xls"]:
        only_shortlist = getattr(args, "only_shortlist", True)
        sheet = "Shortlist" if only_shortlist else 0
        try:
            df = pd.read_excel(companies_path, sheet_name=sheet)
        except ValueError:
            df = pd.read_excel(companies_path, sheet_name=0)
    elif companies_path.suffix.lower() == ".csv":
        df = pd.read_csv(companies_path)
    elif companies_path.suffix.lower() == ".parquet":
        df = pd.read_parquet(companies_path)
    else:
        print("Unsupported companies file format (use xlsx/csv/parquet).")
        return 1
    if "business_id" not in df.columns and "businessId" in df.columns:
        df = df.rename(columns={"businessId": "business_id"})
    if "name" not in df.columns and "company_name" in df.columns:
        df = df.rename(columns={"company_name": "name"})
    if "name" not in df.columns:
        df["name"] = ""
    from .filters import is_housing_company

    filtered = []
    for _, row in df.iterrows():
        name = str(row.get("name") or "")
        if is_housing_company(name):
            continue
        domain = _extract_domain_from_row(row)
        filtered.append({"business_id": row.get("business_id"), "name": row.get("name"), "domain": domain})
    out_path = Path(args.out)
    out_df = pd.DataFrame(filtered)
    out_df.to_csv(out_path, index=False)
    print(f"Domain template written: {out_path} ({len(out_df)} rows, housing names filtered out)")

    if getattr(args, "suggest", False):
        from .domains_discovery import suggest_domains

        max_companies = int(getattr(args, "max_companies", 200) or 200)
        suggestions_df = suggest_domains(out_df, max_companies=max_companies)
        suggested_path = out_path.with_name("domains_suggested.csv")
        suggestions_df.to_csv(suggested_path, index=False)
        print(f"Domain suggestions written: {suggested_path} ({len(suggestions_df)} rows)")

    if getattr(args, "validate", False):
        from .domains_discovery import validate_domains

        domains_path = Path(getattr(args, "domains", "") or out_path)
        if domains_path.exists():
            domains_df = pd.read_csv(domains_path)
        else:
            domains_df = out_df
        validated_df = validate_domains(domains_df)
        validated_path = out_path.with_name("domains_validated.csv")
        validated_df.to_csv(validated_path, index=False)
        print(f"Domain validation written: {validated_path} ({len(validated_df)} rows)")

    return 0


def analytics_command(args: argparse.Namespace) -> int:
    from .analytics import io as a_io
    from .analytics import summarize, writer

    shortlist = a_io.load_master_shortlist(args.master_xlsx)
    jobs_all = a_io.load_jobs_file(args.jobs_xlsx)
    diff_jobs = a_io.load_jobs_diff(args.jobs_diff)
    stats_df = a_io.load_stats_sheet(args.master_xlsx)

    kpi_df = summarize.summarize_kpi(diff_jobs, shortlist, stats_df)
    stations_df = summarize.summarize_stations(shortlist, diff_jobs)
    tags_new_df = summarize.summarize_tags(diff_jobs, shortlist)
    tags_all_df = summarize.summarize_tags(jobs_all, shortlist)
    top_companies_df = summarize.summarize_top_companies(shortlist, diff_jobs, jobs_all)
    industry_df = summarize.summarize_industry(shortlist, diff_jobs)

    writer.write_analytics(
        args.out,
        kpi_df=kpi_df,
        stations_df=stations_df,
        tags_new_df=tags_new_df,
        tags_all_df=tags_all_df,
        top_companies_df=top_companies_df,
        industry_df=industry_df,
    )
    print(f"Analytics written to {args.out}")
    return 0


def map_command(args: argparse.Namespace) -> int:
    from .map import render_jobs_map
    from .artifacts import find_latest_master, find_latest_diff
    from .effective_view import ArtifactPaths, build_effective_view
    from .filters_view import FilterOptions

    master_path = Path(args.master) if args.master else find_latest_master("out")
    diff_path = Path(args.jobs_diff) if args.jobs_diff else find_latest_diff("out")
    curation_path = Path(args.curation) if args.curation else Path("out/curation/master_curation.csv")
    if master_path is None or not master_path.exists():
        print("master.xlsx not found. Etsi uusin: out/master_*.xlsx tai anna --master.")
        return 1

    industries = parse_csv_list(args.industries)
    nace_prefix = parse_csv_list(args.nace_prefix)
    cities = merge_cities(args.cities, getattr(args, "city", []))

    filters = FilterOptions(
        industries=industries,
        cities=cities,
        include_housing=args.include_housing,
        only_recruiting=args.only_recruiting,
        min_score=args.min_score,
        max_distance_km=args.max_distance_km,
        include_excluded=args.sheet.lower() == "all",
    )
    ev = build_effective_view(ArtifactPaths(master=master_path, curation=curation_path, diff=diff_path), filters)

    diff_df = None
    if diff_path and diff_path.exists():
        if diff_path.suffix.lower() in {".xlsx", ".xls"}:
            diff_df = pd.read_excel(diff_path)
        elif diff_path.suffix.lower() == ".jsonl":
            diff_df = pd.read_json(diff_path, lines=True)

    print(
        f"Using master: {ev.meta['master']} (date {ev.meta.get('date_master')}), "
        f"diff: {ev.meta.get('diff')} (date {ev.meta.get('date_diff')}), "
        f"rows: {ev.meta.get('rows_master')} -> {ev.meta.get('rows_filtered')}"
    )
    if ev.meta.get("mismatch"):
        print("Warning: master and diff dates differ.")
    print("Active filters:", "; ".join(ev.meta.get("active_filters", [])))

    render_jobs_map(
        ev.filtered_df,
        diff_df,
        args.out,
        mode=args.mode,
        nace_prefix=nace_prefix,
        sheet=args.sheet,
        only_recruiting=args.only_recruiting,
        min_score=args.min_score,
        max_distance_km=args.max_distance_km,
        industries=industries,
        skip_housing=not args.include_housing,
        pin_scale=args.pin_scale,
        pin_size=args.pin_size,
    )
    print(f"Jobs map written to {args.out}")
    return 0


def watch_command(args: argparse.Namespace) -> int:
    from .watch import generate_watch_report
    from .profiles import load_profiles, apply_profile
    from .artifacts import find_latest_master, find_latest_diff
    from .effective_view import ArtifactPaths, build_effective_view
    from .filters_view import FilterOptions

    run_path = Path(args.run_xlsx) if args.run_xlsx else find_latest_master("out")
    diff_path = Path(args.jobs_diff) if args.jobs_diff else find_latest_diff("out")
    curation_path = Path("out/curation/master_curation.csv")
    if diff_path is None or not diff_path.exists():
        print("Jobs diff not found. Etsi uusin: out/run_*/jobs/diff.xlsx tai anna --jobs-diff.")
        return 1
    if run_path is None or not run_path.exists():
        print("Master.xlsx not found. Etsi uusin: out/master_*.xlsx tai anna --run-xlsx.")
        return 1

    profile_args = {}
    if args.profile:
        profiles = load_profiles()
        profile_args = apply_profile(args.profile, profiles, {})
        if not profile_args:
            print(f"Profile '{args.profile}' not found; continuing without profile.")

    include_tags = parse_csv_list(profile_args.get("include_tags") or args.include_tags)
    exclude_keywords = parse_csv_list(profile_args.get("exclude_tags") or args.exclude_tags)
    stations_list = parse_csv_list(profile_args.get("stations") or args.stations)
    cities = merge_cities(args.cities, getattr(args, "city", []))

    filters = FilterOptions(
        industries=parse_csv_list(profile_args.get("industries") or ""),
        cities=cities,
        include_hidden=getattr(args, "include_hidden", False),
        include_excluded=getattr(args, "include_excluded", False),
        include_housing=False,
        statuses=[],
        min_score=float(profile_args["min_score"]) if profile_args.get("min_score") is not None else args.min_score,
        max_distance_km=float(profile_args["max_distance_km"]) if profile_args.get("max_distance_km") is not None else args.max_distance_km,
        stations=stations_list,
        include_tags=include_tags,
        search=args.search or "",
    )
    ev = build_effective_view(ArtifactPaths(master=run_path, curation=curation_path, diff=diff_path), filters)

    jobs_diff = pd.read_excel(diff_path)
    stats_df = None
    try:
        stats_df = pd.read_excel(run_path, sheet_name="Crawl_Stats")
    except Exception:
        stats_df = None

    generate_watch_report(ev.filtered_df, jobs_diff, Path(args.out), stats=stats_df, exclude_keywords=exclude_keywords, max_items=int(profile_args.get("max_items") or args.max_items or 0))
    print(
        f"Using master: {ev.meta['master']} (date {ev.meta.get('date_master')}), diff: {ev.meta.get('diff')} (date {ev.meta.get('date_diff')}), rows: {ev.meta.get('rows_master')} -> {ev.meta.get('rows_filtered')}"
    )
    if ev.meta.get("mismatch"):
        print("Warning: master and diff dates differ.")
    print("Active filters:", "; ".join(ev.meta.get("active_filters", [])))
    print(f"Watch report written to {args.out}")
    return 0


def scan_command(args: argparse.Namespace) -> int:
    from .hiring_scan import build_config, run_scan

    config = build_config(args)
    return run_scan(config)


def check_command(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .checks import run_checks

    env_file = Path(args.env_file) if args.env_file else None
    return run_checks(env_file)


def serve_command(args: argparse.Namespace) -> int:
    try:
        from .server.app import create_app
    except Exception:
        print("Companion service requires server extras: pip install .[server]")
        return 2
    try:
        import uvicorn
    except Exception:
        print("uvicorn not available. Install with: pip install .[server]")
        return 2

    token = args.token or os.getenv("APPRSCAN_TOKEN") or ""
    app = create_app(token=token if token else None)
    print(f"APPRSCAN token: {app.state.token}")
    uvicorn.run(app, host=args.host, port=int(args.port))
    return 0


def run_command(args: argparse.Namespace) -> int:
    cities = args.cities.split(",") if args.cities else None
    cities = [c.strip() for c in cities] if cities else None
    main_business_line = args.main_business_line or None
    reg_start = args.reg_start or None
    reg_end = args.reg_end or None
    whitelist = [w.strip() for w in args.whitelist.split(",") if w.strip()] if args.whitelist else None
    blacklist = [b.strip() for b in args.blacklist.split(",") if b.strip()] if args.blacklist else None
    industries_whitelist = whitelist
    industries_blacklist = blacklist

    stations_df = load_stations(args.stations_file)

    pages_per_city = []
    all_rows = []
    for city in (cities or []):
        fetched = fetch_companies(
            city=city,
            main_business_line=main_business_line,
            registration_date_start=reg_start,
            registration_date_end=reg_end,
            max_pages=args.max_pages or None,
        )
        all_rows.extend(fetched)
        pages_per_city.append(len(fetched))
    if args.limit:
        all_rows = all_rows[: args.limit]

    df = normalize_companies(all_rows)
    df = normalize.deduplicate_companies(df)
    for col in ["lat", "lon"]:
        if col not in df.columns:
            df[col] = None

    # build full address
    df["full_address"] = df["full_address"].fillna("")

    # geocode if needed
    if not args.skip_geocode:
        geocode_cache = args.geocode_cache or None
        from .geocode import geocode_with_cache

        df = geocode_with_cache(df, geocode_cache)
    else:
        missing_coords = len(df[df["lat"].isna() | df["lon"].isna()])
        print(f"Skip geocode enabled: {missing_coords} rows without lat/lon (map will omit those).")

    # nearest station and distance
    if {"lat", "lon"}.issubset(df.columns) and not df[["lat", "lon"]].isna().all().all():
        def _nearest(row):
            try:
                return nearest_station_from_df(float(row.get("lat")), float(row.get("lon")), stations_df)
            except Exception:
                return ("", float("nan"))
        df[["nearest_station", "distance_km"]] = df.apply(_nearest, axis=1, result_type="expand")
    else:
        df["nearest_station"] = None
        df["distance_km"] = None

    # filtering by whitelist/blacklist (simple substring filter if provided)
    df_filtered = df
    main_bl = df_filtered.get("main_business_line")
    if main_bl is None:
        main_bl = pd.Series("", index=df_filtered.index)
    if industries_whitelist:
        wl = [w.lower() for w in industries_whitelist]
        mask = main_bl.astype(str).str.lower().apply(lambda val: any(w in val for w in wl))
        df_filtered = df_filtered[mask]
    if industries_blacklist:
        bl = [b.lower() for b in industries_blacklist]
        mask_bad = main_bl.astype(str).str.lower().apply(lambda val: any(b in val for b in bl))
        df_filtered = df_filtered[~mask_bad]

    # export
    out_dir = Path(args.out or "out")
    out_dir.mkdir(parents=True, exist_ok=True)

    export_reports(df_filtered, out_dir)
    print(f"Haettu riveja: {len(df_filtered)}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
