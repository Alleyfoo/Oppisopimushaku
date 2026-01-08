from pathlib import Path

from apprscan.artifacts import find_latest_master, find_latest_diff


def test_find_latest_master_prefers_dated(tmp_path: Path):
    (tmp_path / "master.xlsx").write_text("legacy")
    newer = tmp_path / "master_20260101.xlsx"
    newer.write_text("new")
    latest = find_latest_master(tmp_path)
    assert latest == newer


def test_find_latest_diff_prefers_run(tmp_path: Path):
    legacy_dir = tmp_path / "jobs"
    legacy_dir.mkdir()
    legacy = legacy_dir / "diff.xlsx"
    legacy.write_text("legacy")
    run_dir = tmp_path / "run_20260101" / "jobs"
    run_dir.mkdir(parents=True)
    newer = run_dir / "diff.xlsx"
    newer.write_text("new")
    latest = find_latest_diff(tmp_path)
    assert latest == newer
