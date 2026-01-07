"""Command-line interface for apprscan."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import pandas as pd

from . import __version__
from .distance import nearest_station_from_df
from .geocode import geocode_address
from . import normalize
from .normalize import normalize_companies
from .prh_client import fetch_companies
from .report import export_reports
from .stations import load_stations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apprscan",
        description="Apprenticeship employer scanner (PRH/YTJ + geokoodaus + raportointi).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=False)

    # Jobs subcommand
    jobs_parser = subparsers.add_parser(
        "jobs",
        help="Hae työpaikat yritysten urasivuilta.",
        description="Crawlaa urasivuja (domain mapping + heuristiikat) ja normalisoi JobPosting-rivit.",
    )
    jobs_parser.add_argument("--companies", type=str, required=True, help="Yritystiedosto (xlsx/csv/parquet).")
    jobs_parser.add_argument("--domains", type=str, default=None, help="Domain mapping CSV (business_id,domain).")
    jobs_parser.add_argument("--out", type=str, default="out/jobs", help="Output-hakemisto.")
    jobs_parser.add_argument("--max-domains", type=int, default=300, help="Maksimi domainit per ajo.")
    jobs_parser.add_argument(
        "--max-pages-per-domain", type=int, default=30, help="Maksimi sivut per domain (guardrail)."
    )
    jobs_parser.add_argument("--rate-limit", type=float, default=1.0, help="Pyyntöä per sekunti / domain.")
    jobs_parser.add_argument("--debug-html", action="store_true", help="Tallenna raaka HTML out/jobs/raw/.")
    jobs_parser.add_argument(
        "--only-shortlist",
        action="store_true",
        default=True,
        help="Lue vain Shortlist-välilehti companies-tiedostosta (xlsx).",
    )
    jobs_parser.add_argument(
        "--known-jobs",
        type=str,
        default="out/jobs/known_jobs.parquet",
        help="Polku aikaisempiin job_url-arvoihin diffiä varten.",
    )
    jobs_parser.set_defaults(func=jobs_command)

    watch_parser = subparsers.add_parser(
        "watch",
        help="Tuota tekstiraportti uusista työpaikoista (diff).",
        description="Lue master.xlsx ja jobs diff, tuota watch_report.txt listaten uudet työpaikat.",
    )
    watch_parser.add_argument(
        "--run-xlsx",
        type=str,
        default="out/master.xlsx",
        help="Master-työkirja, josta luetaan Shortlist (score/distance).",
    )
    watch_parser.add_argument(
        "--jobs-diff",
        type=str,
        default="out/jobs/diff.xlsx",
        help="Jobs diff -tiedosto (uudet paikat).",
    )
    watch_parser.add_argument(
        "--include-tags",
        type=str,
        default="",
        help="Pilkuilla eroteltu tagilista, joita vaaditaan (esim. data,it_support,salesforce,oppisopimus).",
    )
    watch_parser.add_argument(
        "--exclude-tags",
        type=str,
        default="",
        help="Pilkuilla eroteltu avainsanojen lista, joita ei sallita title/snippetissä (esim. senior,lead,principal).",
    )
    watch_parser.add_argument("--max-items", type=int, default=0, help="Maksimi rivit raportissa (0=kaikki).")
    watch_parser.add_argument("--min-score", type=float, default=None, help="Vähimmäisscore shortlististä.")
    watch_parser.add_argument("--max-distance-km", type=float, default=None, help="Maksimietäisyys km shortlististä.")
    watch_parser.add_argument(
        "--stations",
        type=str,
        default="",
        help="Pilkuilla eroteltu asemalista; jos annettu, raportoi vain nämä asemat.",
    )
    watch_parser.add_argument(
        "--out",
        type=str,
        default="out/watch_report.txt",
        help="Tulostiedosto (tekstiraportti).",
    )
    watch_parser.set_defaults(func=watch_command)

    run_parser = subparsers.add_parser(
        "run",
        help="Suorita haku ja raportointi.",
        description=(
            "Hakee PRH/YTJ:stä yrityksiä, geokoodaa osoitteet ja tuottaa raportit "
            "(Excel/GeoJSON/HTML)."
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
        help="Suurin etäisyys (km) lähimmälle asemalle.",
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
        help="Paikallinen asemadata CSV (station_name,lat,lon). Oletus: data/stations_fi.csv jos löytyy.",
    )
    run_parser.add_argument("--skip-geocode", action="store_true", help="Ohita geokoodaus (debug / nopea ajo).")
    run_parser.add_argument("--limit", type=int, default=0, help="Käsittele vain N ensimmäistä riviä (debug).")
    run_parser.add_argument(
        "--geocode-cache",
        type=str,
        default="data/geocode_cache.sqlite",
        help="SQLite-välimuisti geokoodaukselle.",
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
        help="Sisällytä poissuljetut rivit Exceliin (Excluded-välilehti).",
    )
    run_parser.add_argument(
        "--employee-csv",
        type=str,
        default=None,
        help="Työntekijämäärä-enrichment CSV (business_id, employee_count/employee_band).",
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
        help="Kirjoita lopullinen master-työkirja (Shortlist, Excluded, Jobs_All, Jobs_New, Crawl_Stats, Activity).",
    )
    run_parser.add_argument(
        "--jobs-jsonl",
        type=str,
        default=None,
        help="Jobs JSONL polku master-työkirjaa varten (oletus: <out>/jobs/jobs.jsonl jos jätetty tyhjäksi).",
    )
    run_parser.add_argument(
        "--jobs-diff",
        type=str,
        default=None,
        help="Jobs diff XLSX polku master-työkirjaa varten (oletus: <out>/jobs/diff.xlsx jos jätetty tyhjäksi).",
    )
    run_parser.add_argument(
        "--jobs-stats",
        type=str,
        default=None,
        help="Jobs crawl_stats XLSX polku master-työkirjaa varten (oletus: <out>/jobs/crawl_stats.xlsx jos jätetty tyhjäksi).",
    )
    run_parser.add_argument(
        "--out",
        type=str,
        default="out",
        help="Tulosten hakemisto (Excel/GeoJSON/HTML).",
    )
    run_parser.set_defaults(func=run_command)

    return parser


def run_command(args: argparse.Namespace) -> int:
    cities = [c.strip() for c in (args.cities or "").split(",") if c.strip()]
    if not cities:
        print("Anna vähintään yksi kaupunki --cities parametrilla.")
        return 1

    all_rows = []
    for city in cities:
        rows = fetch_companies(
            location=city,
            main_business_line=args.main_business_line or None,
            reg_start=args.reg_start or None,
            reg_end=args.reg_end or None,
            max_pages=args.max_pages,
        )
        for r in rows:
            r["_source_city"] = city
        all_rows.extend(rows)

    if args.limit:
        all_rows = all_rows[: args.limit]

    print(f"Haettu rivejä: {len(all_rows)}")
    df = normalize_companies(all_rows)
    if df.empty:
        print("Ei rivejä käsiteltäväksi.")
        return 0

    built_addresses = int(df["full_address"].astype(bool).sum())
    print(f"Muodostetut osoitteet: {built_addresses} / {len(df)}")

    if args.skip_geocode:
        df["lat"] = None
        df["lon"] = None
        df["geocode_provider"] = None
        df["geocode_cache_hit"] = None
    else:
        lats = []
        lons = []
        providers = []
        cache_hits = []
        for addr in df["full_address"]:
            lat, lon, provider, cached = geocode_address(addr, cache_path=Path(args.geocode_cache))
            lats.append(lat)
            lons.append(lon)
            providers.append(provider)
            cache_hits.append(cached)
        df["lat"] = lats
        df["lon"] = lons
        df["geocode_provider"] = providers
        df["geocode_cache_hit"] = cache_hits

    df = normalize.deduplicate_companies(df)

    stations_df = None
    try:
        stations_df = load_stations(use_local=True, path=args.stations_file)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Asemadatan lataus epäonnistui: {exc}")

    nearest_names = []
    nearest_dists = []
    if stations_df is not None and not df[["lat", "lon"]].isna().all().all():
        for _, row in df.iterrows():
            if pd.isna(row.get("lat")) or pd.isna(row.get("lon")):
                nearest_names.append("")
                nearest_dists.append(None)
                continue
            name, dist = nearest_station_from_df(float(row["lat"]), float(row["lon"]), stations_df)
            nearest_names.append(name)
            nearest_dists.append(dist)
    else:
        nearest_names = [""] * len(df)
        nearest_dists = [None] * len(df)

    df["nearest_station"] = nearest_names
    df["distance_km"] = nearest_dists

    from .filters import exclude_company, industry_pass
    from .scoring import score_company
    from .storage import load_employee_enrichment

    excluded_flags = []
    excluded_reasons = []
    industry_whitelist_hit = []
    industry_blacklist_hit = []
    industry_reason_col = []

    wl = [s.strip() for s in (args.whitelist or "").split(",") if s.strip()]
    bl = [s.strip() for s in (args.blacklist or "").split(",") if s.strip()]

    for _, row in df.iterrows():
        excl, reason = exclude_company(row.to_dict())
        excluded_flags.append(excl)
        excluded_reasons.append(reason)
        ind_pass, ind_reason, hard_fail = industry_pass(row.to_dict(), wl, bl)
        industry_whitelist_hit.append(ind_reason and ind_reason.startswith("whitelist"))
        industry_blacklist_hit.append(ind_reason and ind_reason.startswith("blacklist"))
        if hard_fail and not excl and ind_reason:
            excl = True
            reason = ind_reason
            excluded_flags[-1] = excl
            excluded_reasons[-1] = reason
        industry_reason_col.append(ind_reason)

    df["excluded_reason"] = excluded_reasons

    # Employee enrichment
    enrichment = {}
    if args.employee_csv:
        try:
            enrichment = load_employee_enrichment(args.employee_csv)
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"Työntekijäenrichment epäonnistui: {exc}")

    employee_counts = []
    employee_bands = []
    employee_sources = []
    employee_gate = []
    for _, row in df.iterrows():
        bid = str(row.get("business_id") or "")
        if bid and bid in enrichment:
            enr = enrichment[bid]
            cnt = enr.get("employee_count")
            band = enr.get("employee_band")
            source = enr.get("employee_source", "csv")
            employee_counts.append(cnt if pd.notna(cnt) else None)
            employee_bands.append(band if pd.notna(band) else None)
            employee_sources.append(source)
            if cnt is not None and pd.notna(cnt):
                try:
                    gate = "pass" if float(cnt) >= 5 else "fail"
                except (TypeError, ValueError):
                    gate = "unknown"
            elif band:
                gate = "unknown"
            else:
                gate = "unknown"
        else:
            employee_counts.append(None)
            employee_bands.append(None)
            employee_sources.append(None)
            gate = "unknown"
        employee_gate.append(gate)
        if gate == "fail":
            reason = "employee_lt_5"
            excluded_reasons[df.index.get_loc(row.name)] = reason
            excluded_flags[df.index.get_loc(row.name)] = True

    df["employee_count"] = employee_counts
    df["employee_band"] = employee_bands
    df["employee_source"] = employee_sources
    df["employee_gate"] = employee_gate

    # Job activity enrichment
    job_activity = {}
    if args.activity_file:
        try:
            if str(args.activity_file).lower().endswith((".xlsx", ".xls")):
                act_df = pd.read_excel(args.activity_file)
            else:
                act_df = pd.read_csv(args.activity_file)
            for _, r in act_df.iterrows():
                bid = str(r.get("business_id") or "").strip()
                if bid:
                    job_activity[bid] = r
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"Aktiviteetin lataus epäonnistui: {exc}")

    job_count_total = []
    job_count_new = []
    tag_data = []
    tag_it = []
    tag_sf = []
    tag_ops = []
    recruiting_active = []
    for _, row in df.iterrows():
        bid = str(row.get("business_id") or "")
        act = job_activity.get(bid, {})
        job_count_total.append(act.get("job_count_total", 0) if isinstance(act, pd.Series) else act.get("job_count_total", 0))
        job_count_new.append(act.get("job_count_new_since_last", 0) if isinstance(act, pd.Series) else act.get("job_count_new_since_last", 0))
        tag_data.append(act.get("tag_count_data", 0) if isinstance(act, pd.Series) else act.get("tag_count_data", 0))
        tag_it.append(act.get("tag_count_it_support", 0) if isinstance(act, pd.Series) else act.get("tag_count_it_support", 0))
        tag_sf.append(act.get("tag_count_salesforce", 0) if isinstance(act, pd.Series) else act.get("tag_count_salesforce", 0))
        tag_ops.append(act.get("tag_count_oppisopimus", 0) if isinstance(act, pd.Series) else act.get("tag_count_oppisopimus", 0))
        recruiting_active.append(bool(act.get("recruiting_active")) if isinstance(act, pd.Series) else bool(act.get("recruiting_active")))

    df["job_count_total"] = job_count_total
    df["job_count_new_since_last"] = job_count_new
    df["tag_count_data"] = tag_data
    df["tag_count_it_support"] = tag_it
    df["tag_count_salesforce"] = tag_sf
    df["tag_count_oppisopimus"] = tag_ops
    df["recruiting_active"] = recruiting_active

    scores = []
    score_reasons = []
    for excl, row, wl_hit, bl_hit, r_active, new_jobs, t_data, t_it, t_sf, t_ops in zip(
        excluded_flags,
        df.iterrows(),
        industry_whitelist_hit,
        industry_blacklist_hit,
        recruiting_active,
        job_count_new,
        tag_data,
        tag_it,
        tag_sf,
        tag_ops,
    ):
        _, r = row
        s, reasons = score_company(
            r.to_dict(),
            radius_km=args.radius_km,
            industry_whitelist_hit=bool(wl_hit),
            industry_blacklist_hit=bool(bl_hit),
            excluded=bool(excl),
            recruiting_active=bool(r_active),
            new_jobs=int(new_jobs or 0),
            tag_counts={
                "data": int(t_data or 0),
                "it_support": int(t_it or 0),
                "salesforce": int(t_sf or 0),
                "oppisopimus": int(t_ops or 0),
            },
        )
        scores.append(s)
        score_reasons.append(reasons)
    df["score"] = scores
    df["score_reasons"] = score_reasons

    df["excluded_reason"] = excluded_reasons

    shortlist = df[df["excluded_reason"].isna()]
    shortlist = shortlist.sort_values(["score", "distance_km"], ascending=[False, True]).reset_index(drop=True)
    shortlist["rank"] = shortlist.index + 1

    excluded_df = None
    if args.include_excluded:
        excluded_df = df[df["excluded_reason"].notna()].copy()

    export_reports(shortlist, args.out, excluded=excluded_df)

    # Master workbook (optional)
    if args.master_xlsx:
        from .jobs.storage import write_master_workbook

        jobs_dir = Path(args.out) / "jobs"
        jobs_jsonl = Path(args.jobs_jsonl) if args.jobs_jsonl else jobs_dir / "jobs.jsonl"
        jobs_diff = Path(args.jobs_diff) if args.jobs_diff else jobs_dir / "diff.xlsx"
        jobs_stats = Path(args.jobs_stats) if args.jobs_stats else jobs_dir / "crawl_stats.xlsx"

        def read_optional_jsonl(path):
            if path.exists():
                return pd.read_json(path, lines=True)
            return pd.DataFrame()

        def read_optional_excel(path):
            if path.exists():
                return pd.read_excel(path)
            return pd.DataFrame()

        jobs_all = read_optional_jsonl(jobs_jsonl)
        jobs_new = read_optional_excel(jobs_diff)
        crawl_stats = read_optional_excel(jobs_stats)
        activity_df = None
        if args.activity_file and Path(args.activity_file).exists():
            activity_df = pd.read_excel(args.activity_file)

        master_path = Path(args.master_xlsx)
        write_master_workbook(
            master_path,
            shortlist=shortlist,
            excluded=excluded_df if args.include_excluded else None,
            jobs_all=jobs_all,
            jobs_new=jobs_new,
            crawl_stats=crawl_stats,
            activity=activity_df,
        )
        print(f"Master workbook kirjoitettu: {master_path}")

    print(f"Shortlist: {len(shortlist)}; excluded: {len(df) - len(shortlist)}; raportit: {args.out}")
    return 0


def jobs_command(args: argparse.Namespace) -> int:
    from .jobs import pipeline
    from .jobs.discovery import DiscoveryResult
    from .jobs.storage import write_jobs_outputs

    companies_path = Path(args.companies)
    if not companies_path.exists():
        print(f"Companies file not found: {companies_path}")
        return 1

    domain_map = {}
    if args.domains:
        dom_df = pd.read_csv(args.domains)
        for _, r in dom_df.iterrows():
            bid = str(r.get("business_id") or r.get("businessId") or "").strip()
            dom = str(r.get("domain") or "").strip()
            if bid and dom:
                domain_map[bid] = dom

    try:
        companies_df = pipeline.load_companies(companies_path, only_shortlist=args.only_shortlist)
    except ValueError as exc:
        print(str(exc))
        return 1

    raw_dir = Path(args.out) / "raw" if args.debug_html else None
    jobs_df, stats_df = pipeline.crawl_jobs_pipeline(
        companies_df,
        domain_map,
        max_domains=args.max_domains,
        max_pages_per_domain=args.max_pages_per_domain,
        req_per_second=args.rate_limit,
        debug_html=args.debug_html,
        out_raw_dir=raw_dir,
    )

    known_path = Path(args.known_jobs)
    jobs_df, new_jobs = pipeline.apply_diff(jobs_df, known_path)
    write_jobs_outputs(jobs_df, stats_df, args.out)

    # Write diff
    diff_path = Path(args.out) / "diff.xlsx"
    new_jobs.to_excel(diff_path, index=False)

    # Company activity
    activity_df = pipeline.summarize_activity(jobs_df)
    activity_path = Path(args.out) / "company_activity.xlsx"
    activity_df.to_excel(activity_path, index=False)

    print(
        f"Jobs found: {len(jobs_df)} (new: {len(new_jobs)}); "
        f"domains: {len(stats_df)}; output: {args.out}"
    )
    return 0


def watch_command(args: argparse.Namespace) -> int:
    from .watch import generate_watch_report

    run_path = Path(args.run_xlsx)
    diff_path = Path(args.jobs_diff)
    if not diff_path.exists():
        print(f"Jobs diff not found: {diff_path}")
        return 1

    shortlist_df = None
    if run_path.exists():
        try:
            shortlist_df = pd.read_excel(run_path, sheet_name="Shortlist")
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"Shortlist reading failed: {exc}")

    jobs_diff = pd.read_excel(diff_path)
    generate_watch_report(shortlist_df, jobs_diff, Path(args.out))
    print(f"Watch report written to {args.out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)
