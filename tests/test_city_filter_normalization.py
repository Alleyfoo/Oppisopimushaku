import pandas as pd

from apprscan.filters_view import FilterOptions, filter_data


def test_city_filter_handles_diacritics():
    df = pd.DataFrame(
        {
            "business_id": ["1", "2"],
            "name": ["A", "B"],
            "city": ["Mäntsälä", "Helsinki"],
        }
    )
    opts = FilterOptions(cities=["Mantsala"])
    out = filter_data(df, opts)
    assert out["business_id"].tolist() == ["1"]
