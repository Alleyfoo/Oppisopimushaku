"""Quick analysis of out/companies.csv."""

import pandas as pd

df = pd.read_csv("out/companies.csv", encoding="utf-8-sig")

print("=== OVERVIEW ===")
print(f"Total companies: {len(df)}")
print(f"Areas: {df['nearest_station'].value_counts().to_dict()}")
print()

print("=== INDUSTRY BREAKDOWN (all areas) ===")
print(df["industry"].value_counts().to_string())
print()

print("=== INDUSTRY BY AREA ===")
pivot = df.groupby(["nearest_station", "industry"]).size().unstack(fill_value=0)
print(pivot.to_string())
print()

print("=== DISTANCE DISTRIBUTION ===")
print(df.groupby("nearest_station")["distance_km"].describe().round(2).to_string())
print()

print("=== WEBSITE COVERAGE ===")
has_web = df.dropna(subset=["website"])
by_area = has_web.groupby("nearest_station").size().rename("with_website")
total_by_area = df.groupby("nearest_station").size().rename("total")
web_pct = pd.concat([total_by_area, by_area], axis=1).fillna(0)
web_pct["pct"] = (web_pct["with_website"] / web_pct["total"] * 100).round(1)
print(web_pct.to_string())
print(f"Overall: {len(has_web)} / {len(df)} ({100 * len(has_web) / len(df):.1f}%)")
print()

print("=== TOP 12 TOI DESCRIPTIONS ===")
print(df["toi_description"].value_counts().head(12).to_string())
print()

print("=== 'other' INDUSTRY — top TOI codes ===")
other = df[df["industry"] == "other"]
print(other["toi_code"].value_counts().head(15).to_string())
