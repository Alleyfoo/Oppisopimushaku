"""Convenience pipeline runner: run -> jobs -> run with activity -> master -> watch."""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path


def run_cmd(cmd: list[str]) -> None:
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


def build_common_run_args(args: argparse.Namespace) -> list[str]:
    cmd = [
        "python",
        "-m",
        "apprscan",
        "run",
        "--cities",
        args.cities,
        "--radius-km",
        str(args.radius_km),
        "--max-pages",
        str(args.max_pages),
    ]
    if args.main_business_line:
        cmd += ["--main-business-line", args.main_business_line]
    if args.reg_start:
        cmd += ["--reg-start", args.reg_start]
    if args.reg_end:
        cmd += ["--reg-end", args.reg_end]
    if args.whitelist:
        cmd += ["--whitelist", args.whitelist]
    if args.blacklist:
        cmd += ["--blacklist", args.blacklist]
    if args.include_excluded:
        cmd += ["--include-excluded"]
    if args.stations_file:
        cmd += ["--stations-file", args.stations_file]
    if args.employee_csv:
        cmd += ["--employee-csv", args.employee_csv]
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full pipeline: run -> jobs -> run with activity -> master -> watch.")
    parser.add_argument("--cities", required=True, help="Cities list, comma-separated.")
    parser.add_argument("--radius-km", type=float, default=1.0)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--main-business-line", type=str, default="")
    parser.add_argument("--reg-start", type=str, default="")
    parser.add_argument("--reg-end", type=str, default="")
    parser.add_argument("--whitelist", type=str, default="")
    parser.add_argument("--blacklist", type=str, default="")
    parser.add_argument("--stations-file", type=str, default=None)
    parser.add_argument("--employee-csv", type=str, default=None)
    parser.add_argument("--domains", type=str, default=None, help="Domain mapping CSV for jobs step.")
    parser.add_argument("--known-jobs", type=str, default="out/known_jobs.parquet")
    parser.add_argument("--run-out", type=str, default=None, help="Run output dir (default out/run_<date>).")
    parser.add_argument("--jobs-out", type=str, default=None, help="Jobs output dir (default <run_out>/jobs).")
    parser.add_argument("--master-xlsx", type=str, default=None, help="Master workbook path (default out/master_<date>.xlsx).")
    parser.add_argument("--watch-out", type=str, default=None, help="Watch report path (default out/watch_report_<date>.txt).")
    parser.add_argument("--include-excluded", action="store_true", help="Include excluded in final master.")
    args = parser.parse_args()

    ts = datetime.utcnow().strftime("%Y%m%d")
    run_out = Path(args.run_out or f"out/run_{ts}")
    jobs_out = Path(args.jobs_out or run_out / "jobs")
    master_path = Path(args.master_xlsx or f"out/master_{ts}.xlsx")
    watch_path = Path(args.watch_out or f"out/watch_report_{ts}.txt")
    known_jobs = Path(args.known_jobs)

    # Step 1: run (initial)
    run_cmd(build_common_run_args(args) + ["--out", str(run_out)])

    # Step 2: jobs
    jobs_cmd = [
        "python",
        "-m",
        "apprscan",
        "jobs",
        "--companies",
        str(run_out / "companies.xlsx"),
        "--out",
        str(jobs_out),
        "--known-jobs",
        str(known_jobs),
    ]
    if args.domains:
        jobs_cmd += ["--domains", args.domains]
    run_cmd(jobs_cmd)

    # Step 3: run with activity + master
    run_cmd(
        build_common_run_args(args)
        + [
            "--activity-file",
            str(jobs_out / "company_activity.xlsx"),
            "--master-xlsx",
            str(master_path),
            "--out",
            str(run_out),
        ]
    )

    # Step 4: watch report
    run_cmd(
        [
            "python",
            "-m",
            "apprscan",
            "watch",
            "--run-xlsx",
            str(master_path),
            "--jobs-diff",
            str(jobs_out / "diff.xlsx"),
            "--out",
            str(watch_path),
        ]
    )

    print(f"Pipeline finished. Master: {master_path} Watch: {watch_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
