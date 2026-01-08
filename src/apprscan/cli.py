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
    jobs_parser.add_argument(
        "--suggested",
        type=str,
        default=None,
        help="domains_suggested.csv fallback; käytetään jos varsinaisesta domain-mapista puuttuu.",
    )
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

    domains_parser = subparsers.add_parser(
        "domains",
        help="Luo domain-mapping -pohja companies tiedostosta.",
        description="Lue companies (xlsx/csv/parquet) ja kirjoita CSV (business_id,name,domain) täytettäväksi.",
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
        help="Yritä löytää urasivudomainit automaattisesti (kirjoittaa domains_suggested.csv).",
    )
    domains_parser.add_argument("--max-companies", type=int, default=200, help="Maksimi yrityksiä discoveryyn.")
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

    watch_parser = subparsers.add_parser(
        "watch",
        help="Tuota tekstiraportti uusista työpaikoista (diff).",
        description="Lue master.xlsx ja jobs diff, tuota watch_report.txt listaten uudet työpaikat.",
    )
    watch_parser.add_argument(
        "--run-xlsx",
        type=str,
        default=None,
        help="Master-työkirja, josta luetaan Shortlist (score/distance).",
    )
    watch_parser.add_argument(
        "--jobs-diff",
        type=str,
        default=None,
        help="Jobs diff -tiedosto (uudet paikat). Oletus: uusin out/run_*/jobs/diff.xlsx.",
    )
    watch_parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Profiilin nimi (config/profiles.yaml) watch-filttereille.",
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

    analytics_parser = subparsers.add_parser(
        "analytics",
        help="Tuota analytics.xlsx olemassa olevista artefakteista.",
        description="Laskee KPI:t, asema- ja tagiyhteenvedot master/jobs/diff -tiedostoista.",
    )
    analytics_parser.add_argument("--master-xlsx", type=str, required=True, help="Polku master.xlsx:ään (Shortlist).")
    analytics_parser.add_argument(
        "--jobs-xlsx", type=str, required=True, help="Polku jobs.xlsx/jsonl (kaikki työpaikat)."
    )
    analytics_parser.add_argument("--jobs-diff", type=str, required=True, help="Polku diff-tiedostoon (uudet työpaikat).")
    analytics_parser.add_argument("--out", type=str, default="out/analytics.xlsx", help="Output tiedosto (xlsx).")
    analytics_parser.set_defaults(func=analytics_command)

    map_parser = subparsers.add_parser(
        "map",
        help="Render?i jobs_map.html Shortlistista ja diffist?.",
        description="Tekee interaktiivisen kartan ilman uutta crawlia.",
    )
    map_parser.add_argument("--master-xlsx", type=str, required=False, default=None, help="Polku master.xlsx:??n (Shortlist).")
    map_parser.add_argument("--jobs-diff", type=str, required=False, help="Polku diff-tiedostoon (uudet ty?paikat).")
    map_parser.add_argument("--out", type=str, default="out/jobs_map.html", help="Output HTML -kartta.")
    map_parser.add_argument("--mode", type=str, default="jobs", choices=["jobs", "companies"], help="Karttatila: jobs=diff + shortlist, companies=yritykset.")
    map_parser.add_argument("--sheet", type=str, default="Shortlist", help="Sheet masterista (Shortlist/Excluded/all).")
    map_parser.add_argument("--nace-prefix", type=str, default="", help="Pilkutetut TOL/NACE-prefixit (esim. 62,63).")
    map_parser.add_argument("--only-recruiting", action="store_true", help="N?yt? vain recruiting_active=TRUE.")
    map_parser.add_argument("--min-score", type=float, default=None, help="V?himm?isscore kartalle.")
    map_parser.add_argument("--max-distance-km", type=float, default=None, help="Maksimiet?isyys km kartalle.")
    map_parser.set_defaults(func=map_command)

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
        "--industry-config",
        type=str,
        default="config/industry_groups.yaml",
        help="Industry groups YAML (prefix-listat). Puuttuu -> industry=other.",
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
    from .industry import load_industry_groups

    groups = load_industry_groups(args.industry_config)
    df = normalize_companies(all_rows, industry_groups=groups)
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
        dom_path = Path(args.domains)
        if dom_path.exists():
            dom_df = pd.read_csv(dom_path)
            for _, r in dom_df.iterrows():
                bid = str(r.get("business_id") or r.get("businessId") or "").strip()
                dom = str(r.get("domain") or "").strip()
                if bid and dom:
                    domain_map[bid] = dom
        else:
            print(f"Domain mapping file not found: {dom_path} (continuing without domains)")
    suggested_map = {}
    if getattr(args, "suggested", None):
        sug_path = Path(args.suggested)
        if sug_path.exists():
            sug_df = pd.read_csv(sug_path)
            for _, r in sug_df.iterrows():
                bid = str(r.get("business_id") or "").strip()
                dom = str(r.get("suggested_base_url") or r.get("domain") or "").strip()
                if bid and dom:
                    suggested_map[bid] = dom

    try:
        companies_df = pipeline.load_companies(companies_path, only_shortlist=args.only_shortlist)
    except ValueError as exc:
        print(str(exc))
        return 1

    raw_dir = Path(args.out) / "raw" if args.debug_html else None
    jobs_df, stats_df, activity_df = pipeline.crawl_jobs_pipeline(
        companies_df,
        domain_map,
        max_domains=args.max_domains,
        max_pages_per_domain=args.max_pages_per_domain,
        req_per_second=args.rate_limit,
        debug_html=args.debug_html,
        out_raw_dir=raw_dir,
        suggested_map=suggested_map or None,
    )

    known_path = Path(args.known_jobs)
    jobs_df, new_jobs = pipeline.apply_diff(jobs_df, known_path)
    write_jobs_outputs(jobs_df, stats_df, args.out)

    # Write diff
    diff_path = Path(args.out) / "diff.xlsx"
    new_jobs.to_excel(diff_path, index=False)

    # Company activity
    activity_path = Path(args.out) / "company_activity.xlsx"
    activity_df.to_excel(activity_path, index=False)

    print(
        f"Jobs found: {len(jobs_df)} (new: {len(new_jobs)}); "
        f"domains: {len(stats_df)}; output: {args.out}"
    )
    return 0


def watch_command(args: argparse.Namespace) -> int:
    from .watch import generate_watch_report
    from .profiles import load_profiles, apply_profile
    from .artifacts import find_latest_master, find_latest_diff

    run_path = Path(args.run_xlsx) if args.run_xlsx else find_latest_master("out")
    diff_path = Path(args.jobs_diff) if args.jobs_diff else find_latest_diff("out")
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

    shortlist_df = None
    if run_path.exists():
        try:
            shortlist_df = pd.read_excel(run_path, sheet_name="Shortlist")
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"Shortlist reading failed: {exc}")

    kwargs = {
        "include_tags": (profile_args.get("include_tags") or args.include_tags or "").split(",")
        if (profile_args.get("include_tags") or args.include_tags)
        else [],
        "exclude_keywords": (profile_args.get("exclude_tags") or args.exclude_tags or "").split(",")
        if (profile_args.get("exclude_tags") or args.exclude_tags)
        else [],
        "max_items": int(profile_args.get("max_items") or args.max_items or 0),
        "min_score": float(profile_args["min_score"]) if profile_args.get("min_score") is not None else args.min_score,
        "max_distance_km": float(profile_args["max_distance_km"])
        if profile_args.get("max_distance_km") is not None
        else args.max_distance_km,
        "stations": (profile_args.get("stations") or args.stations or "").split(",")
        if (profile_args.get("stations") or args.stations)
        else [],
    }
    jobs_diff = pd.read_excel(diff_path)
    stats_df = None
    try:
        stats_df = pd.read_excel(run_path, sheet_name="Crawl_Stats")
    except Exception:
        stats_df = None
    generate_watch_report(shortlist_df, jobs_diff, Path(args.out), stats=stats_df, **kwargs)
    print(f"Watch report written to {args.out}")
    return 0


def analytics_command(args: argparse.Namespace) -> int:
    from .analytics import (
        load_master_shortlist,
        load_jobs_file,
        load_jobs_diff,
        load_stats_sheet,
        summarize_kpi,
        summarize_stations,
        summarize_tags,
        write_analytics,
    )

    master_path = Path(args.master_xlsx)
    jobs_path = Path(args.jobs_xlsx)
    diff_path = Path(args.jobs_diff)
    if not master_path.exists():
        print(f"master.xlsx not found: {master_path}")
        return 1
    if not jobs_path.exists():
        print(f"jobs file not found: {jobs_path}")
        return 1
    if not diff_path.exists():
        print(f"diff file not found: {diff_path}")
        return 1

    shortlist = load_master_shortlist(master_path)
    jobs_df = load_jobs_file(jobs_path)
    diff_df = load_jobs_diff(diff_path)
    stats_df = load_stats_sheet(master_path)

    stations_df = summarize_stations(shortlist, diff_df)
    tags_new_df = summarize_tags(diff_df, shortlist)
    tags_all_df = summarize_tags(jobs_df, shortlist) if jobs_df is not None else None
    kpi_df = summarize_kpi(diff_df, shortlist, stats_df)
    from .analytics.summarize import summarize_top_companies, summarize_industry

    top_companies_df = summarize_top_companies(shortlist, diff_df, jobs_df)
    industry_df = summarize_industry(shortlist, diff_df)

    write_analytics(
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

    master_path = Path(args.master_xlsx) if args.master_xlsx else find_latest_master("out")
    diff_path = Path(args.jobs_diff) if args.jobs_diff else find_latest_diff("out")
    if master_path is None or not master_path.exists():
        print("master.xlsx not found. Etsi uusin: out/master_*.xlsx tai anna --master-xlsx.")
        return 1
    sheet_name = args.sheet if args.sheet.lower() != "all" else None
    shortlist = pd.read_excel(master_path, sheet_name=sheet_name or None)
    if args.sheet.lower() == "all" and isinstance(shortlist, dict):
        shortlist_df = shortlist.get("Shortlist", pd.DataFrame())
        excluded_df = shortlist.get("Excluded", pd.DataFrame())
        if not excluded_df.empty:
            excluded_df["excluded_flag"] = True
        if not shortlist_df.empty:
            shortlist_df["excluded_flag"] = False
        shortlist = pd.concat([shortlist_df, excluded_df], ignore_index=True)
    diff_df = None
    if diff_path and diff_path.exists():
        if diff_path.suffix.lower() in {".xlsx", ".xls"}:
            diff_df = pd.read_excel(diff_path)
        elif diff_path.suffix.lower() == ".jsonl":
            diff_df = pd.read_json(diff_path, lines=True)
    industries = [s.strip() for s in args.nace_prefix.split(",") if s.strip()] if args.nace_prefix else []
    render_jobs_map(
        shortlist,
        diff_df,
        args.out,
        mode=args.mode,
        nace_prefix=industries,
        sheet=args.sheet,
        only_recruiting=args.only_recruiting,
        min_score=args.min_score,
        max_distance_km=args.max_distance_km,
    )
    print(f"Jobs map written to {args.out}")
    return 0


def domains_command(args: argparse.Namespace) -> int:
    from .domains_discovery import suggest_domains, validate_domains

    companies_path = Path(args.companies)
    if not companies_path.exists():
        print(f"Companies file not found: {companies_path}")
        return 1
    if companies_path.suffix.lower() in [".xlsx", ".xls"]:
        sheet = "Shortlist" if args.only_shortlist else 0
        df = pd.read_excel(companies_path, sheet_name=sheet)
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

    names = []
    import ast

    for _, row in df.iterrows():
        if "name" in df.columns and pd.notna(row.get("name")):
            names.append(row["name"])
            continue
        if "names.0.name" in df.columns and pd.notna(row.get("names.0.name")):
            names.append(row["names.0.name"])
            continue
        raw = row.get("names")
        if isinstance(raw, str) and raw.startswith("["):
            try:
                parsed = ast.literal_eval(raw)
                if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                    names.append(parsed[0].get("name", ""))
                    continue
            except Exception:
                pass
        names.append("")

    if "name" not in df.columns:
        df["name"] = names

    filtered = []
    for _, row in df.iterrows():
        name = str(row.get("name") or "").lower()
        if "asunto" in name:
            continue  # drop housing companies from domain template
        filtered.append({"business_id": row.get("business_id"), "name": row.get("name"), "domain": ""})

    out_df = pd.DataFrame(filtered)
    out_path = Path(args.out)
    out_df.to_csv(out_path, index=False)
    print(f"Domain template written: {out_path} ({len(out_df)} rows, housing names filtered out)")
    # coverage summary
    covered = out_df[out_df["domain"].astype(str).str.strip() != ""]
    print(f"Coverage: input {len(out_df)}, have_domain {len(covered)}")

    if getattr(args, "suggest", False):
        suggestions = suggest_domains(out_df, max_companies=args.max_companies)
        sug_path = out_path.with_name(out_path.stem + "_suggested.csv")
        suggestions.to_csv(sug_path, index=False)
        high = (suggestions["confidence"] == "high").sum() if not suggestions.empty else 0
        med = (suggestions["confidence"] == "med").sum() if not suggestions.empty else 0
        low = (suggestions["confidence"] == "low").sum() if not suggestions.empty else 0
        print(
            f"Suggested domains written: {sug_path} ({len(suggestions)} rows; high={high}, med={med}, low={low})"
        )

    if getattr(args, "validate", False):
        validate_src = Path(args.domains or out_path)
        if not validate_src.exists():
            print(f"Domains file for validation not found: {validate_src}")
            return 1
        dom_df = pd.read_csv(validate_src)
        validated = validate_domains(dom_df)
        val_path = validate_src.with_name(validate_src.stem + "_validated.csv")
        validated.to_csv(val_path, index=False)
        print(f"Validated domains written: {val_path} ({len(validated)} rows)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)
