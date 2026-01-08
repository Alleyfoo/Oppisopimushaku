import pandas as pd

from apprscan.filters_view import FilterOptions, filter_data


def build_df():
    return pd.DataFrame(
        [
            {
                "business_id": "1",
                "name": "Asunto Oy Testi",
                "industry_effective": "it",
                "city": "Helsinki",
                "score": 8,
                "distance_km": 0.5,
                "nearest_station": "Pasila",
                "recruiting_active": True,
                "tags_effective": ["data"],
            },
            {
                "business_id": "2",
                "name": "Tech Oy",
                "industry_effective": "it",
                "city": "Lahti",
                "score": 4,
                "distance_km": 3.0,
                "nearest_station": "Lahti",
                "recruiting_active": False,
                "tags_effective": ["it-support"],
            },
        ]
    )


def test_filters_exclude_housing_and_distance():
    df = build_df()
    opts = FilterOptions(max_distance_km=1.0)
    filtered = filter_data(df, opts)
    # Housing name filtered out, distance filters second row.
    assert filtered.empty


def test_filters_include_tags_and_recruiting():
    df = build_df()
    opts = FilterOptions(include_tags=["data"], only_recruiting=True, include_housing=True)
    filtered = filter_data(df, opts)
    assert len(filtered) == 1
    assert filtered.iloc[0]["business_id"] == "1"


def test_filters_city():
    df = build_df()
    opts = FilterOptions(cities=["Lahti"], include_housing=True)
    filtered = filter_data(df, opts)
    assert len(filtered) == 1
    assert filtered.iloc[0]["business_id"] == "2"
