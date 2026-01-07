from types import SimpleNamespace
from pathlib import Path

import pandas as pd

from apprscan.cli import domains_command


def test_domains_command_filters_housing(tmp_path):
    companies_path = tmp_path / "companies.xlsx"
    data = pd.DataFrame(
        {
            "business_id": ["123", "456"],
            "name": ["Asunto Oy Testi", "Veho Oy Ab"],
        }
    )
    data.to_excel(companies_path, index=False)

    args = SimpleNamespace(companies=str(companies_path), out=str(tmp_path / "domains.csv"), only_shortlist=False)
    domains_command(args)

    out_df = pd.read_csv(args.out)
    assert len(out_df) == 1
    assert str(out_df.iloc[0]["business_id"]) == "456"
