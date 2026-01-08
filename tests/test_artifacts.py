from pathlib import Path

from apprscan.artifacts import find_latest_master, find_latest_diff, artifact_date


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


def test_find_latest_master_prefers_date_over_mtime(tmp_path: Path, monkeypatch):
    dated = tmp_path / "master_20260102.xlsx"
    dated.write_text("dated")
    legacy = tmp_path / "master.xlsx"
    legacy.write_text("legacy")
    # make legacy newer mtime
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    import time
    time.sleep(0.1)
    legacy.write_text("legacy2")
    latest = find_latest_master(tmp_path)
    assert latest == dated


def test_artifact_date_from_name_and_parent(tmp_path: Path):
    p1 = tmp_path / "master_20260108.xlsx"
    p1.write_text("x")
    assert artifact_date(p1) == "20260108"
    p2 = tmp_path / "run_20260105" / "jobs" / "diff.xlsx"
    p2.parent.mkdir(parents=True, exist_ok=True)
    p2.write_text("y")
    assert artifact_date(p2) == "20260105"
