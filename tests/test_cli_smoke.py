import subprocess
import sys
from pathlib import Path

import pandas as pd


def run_cli(args, cwd):
    cmd = [sys.executable, "-m", "apprscan"] + args
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def test_cli_help(tmp_path):
    res = run_cli(["--help"], cwd=Path(__file__).resolve().parent.parent)
    assert res.returncode == 0
    assert "apprscan" in res.stdout


def test_cli_map_smoke(tmp_path):
    cwd = Path(__file__).resolve().parent.parent
    master_path = tmp_path / "master.xlsx"
    shortlist = pd.DataFrame(
        [
            {
                "business_id": "1",
                "name": "Test Oy",
                "lat": 60.1,
                "lon": 24.9,
                "status": "shortlist",
                "score": 10,
                "city": "Mäntsälä",
            },
        ]
    )
    with pd.ExcelWriter(master_path) as writer:
        shortlist.to_excel(writer, index=False, sheet_name="Shortlist")
    out_html = tmp_path / "map.html"
    res = run_cli(
        [
            "map",
            "--master",
            str(master_path),
            "--out",
            str(out_html),
            "--cities",
            "Mantsala",
            "--pin-scale",
            "log",
        ],
        cwd=cwd,
    )
    assert res.returncode == 0, res.stderr
    assert out_html.exists()


def test_cli_watch_smoke(tmp_path):
    cwd = Path(__file__).resolve().parent.parent
    master_path = tmp_path / "master.xlsx"
    shortlist = pd.DataFrame(
        [
            {
                "business_id": "1",
                "name": "Test Oy",
                "lat": 60.1,
                "lon": 24.9,
                "status": "shortlist",
                "score": 10,
                "city": "Mäntsälä",
            },
        ]
    )
    diff_path = tmp_path / "diff.xlsx"
    diff_df = pd.DataFrame(
        [
            {"company_business_id": "1", "job_title": "Dev", "job_url": "https://example.com/job"},
        ]
    )
    with pd.ExcelWriter(master_path) as writer:
        shortlist.to_excel(writer, index=False, sheet_name="Shortlist")
    diff_df.to_excel(diff_path, index=False)
    out_report = tmp_path / "watch.txt"
    res = run_cli(
        [
            "watch",
            "--run-xlsx",
            str(master_path),
            "--jobs-diff",
            str(diff_path),
            "--cities",
            "Mantsala",
            "--out",
            str(out_report),
        ],
        cwd=cwd,
    )
    assert res.returncode == 0, res.stderr
    assert out_report.exists()
