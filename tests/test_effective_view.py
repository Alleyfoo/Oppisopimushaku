from pathlib import Path

import pandas as pd

from apprscan.effective_view import ArtifactPaths, build_effective_view
from apprscan.filters_view import FilterOptions
from apprscan.curation import write_curation_with_backup  # reuse writer for temp file


def test_build_effective_view_filters_and_meta(tmp_path: Path, monkeypatch):
    master_path = tmp_path / "master_20260108.xlsx"
    df = pd.DataFrame(
        [
            {"business_id": "1", "name": "A Oy", "industry": "it", "status": "shortlist", "lat": 1, "lon": 1},
            {"business_id": "2", "name": "B Oy", "industry": "other", "status": "neutral", "lat": 2, "lon": 2, "city": "Lahti"},
        ]
    )
    df.to_excel(master_path, index=False, sheet_name="Shortlist")
    paths = ArtifactPaths(master=master_path)
    filters = FilterOptions(industries=["it"])
    res = build_effective_view(paths, filters)
    assert len(res.filtered_df) == 1
    assert res.meta["rows_master"] == 2
    assert res.meta["date_master"] == "20260108"
