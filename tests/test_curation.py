import pandas as pd

from apprscan.curation import apply_curation, update_curation_from_edits
from apprscan.curation import normalize_tags, validate_master
import pandas as pd


def test_apply_curation_overrides_and_tags():
    master = pd.DataFrame(
        [
            {
                "business_id": "1",
                "name": "A Oy",
                "industry": "it",
                "tags": ["data"],
                "score": 10,
            },
            {
                "business_id": "2",
                "name": "B Oy",
                "industry": "other",
                "tags": [],
                "score": 5,
            },
        ]
    )
    curation = pd.DataFrame(
        [
            {
                "business_id": "1",
                "status": "shortlist",
                "hide_flag": False,
                "note": "keep",
                "industry_override": "analytics",
                "tags_add": "ai,ml",
                "tags_remove": "data",
            }
        ]
    )

    applied = apply_curation(master, curation)
    df = applied.view
    row1 = df[df["business_id"] == "1"].iloc[0]
    assert row1["industry_effective"] == "analytics"
    assert row1["status"] == "shortlist"
    assert sorted(row1["tags_effective"]) == ["ai", "ml"]

    row2 = df[df["business_id"] == "2"].iloc[0]
    assert row2["industry_effective"] == "other"
    assert row2["tags_effective"] == []


def test_update_curation_from_edits_creates_and_updates():
    base = pd.DataFrame(
        [
            {
                "business_id": "1",
                "status": "neutral",
                "hide_flag": False,
                "note": "",
                "industry_override": "",
                "tags_add": "",
                "tags_remove": "",
                "updated_at": "",
                "updated_by": "",
                "source_master": "master_old",
            }
        ]
    )
    edits = [
        {"business_id": "1", "status": "shortlist", "note": "good"},
        {"business_id": "2", "status": "excluded", "hide_flag": True},
    ]
    updated = update_curation_from_edits(edits, base, source_master="master_new", updated_by="ui")
    as_dict = updated.set_index("business_id").to_dict(orient="index")
    assert as_dict["1"]["status"] == "shortlist"
    assert as_dict["1"]["note"] == "good"
    assert as_dict["1"]["source_master"] == "master_new"
    assert as_dict["2"]["status"] == "excluded"
    assert as_dict["2"]["hide_flag"] is True


def test_normalize_tags_dedup_and_lower():
    assert normalize_tags(" IT;it , Data;; ") == ["it", "data"]
    assert normalize_tags(None) == []


def test_validate_master_blocks_duplicates():
    df = pd.DataFrame([{"business_id": "1"}, {"business_id": "1"}])
    try:
        validate_master(df)
    except ValueError as exc:
        assert "duplicate" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError for duplicates")
