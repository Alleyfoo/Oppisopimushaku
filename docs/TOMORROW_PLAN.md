# Tomorrow Plan (Places data -> websites -> crawl)

Goal: use the Places CSV data (stations radius) as the base list, then
discover websites/domains and only then run the jobs crawler.

1) Build the base master from Places CSVs
- Inputs: `out/places_mantsala.csv`, `out/places_lahti.csv`,
  `out/places_kerava.csv`, `out/places_vantaa.csv`
- Command:
  `python scripts/places_to_master.py --station "Mantsala,60.6333,25.3170,out/places_mantsala.csv" --station "Lahti,60.98364725866405,25.65771119411973,out/places_lahti.csv" --station "Kerava,60.4047852003956,25.105777725204135,out/places_kerava.csv" --station "Vantaa,60.29367419335387,25.04404028300421,out/places_vantaa.csv" --out out/master_places.xlsx`

2) Review and curate the list
- Open Streamlit with `out/master_places.xlsx`
- Hide housing-like names, add notes/tags
- Commit changes (curation overlay, no direct edits to master)

3) Website/domain discovery (next coding step)
- Use `website` from Places if available
- For missing websites, run a lightweight domain discovery
  (reuse `domains_discovery.py` or add a small helper)
- Produce `domains.csv` with `business_id,name,domain`

4) Jobs crawl (optional after websites exist)
- Run `apprscan jobs --companies out/master_places.xlsx --domains domains.csv`
- Focus on shortlist/curated rows only

Notes
- Places data is limited but good enough for outreach + website discovery.
- Keep analysis simple: distance from station + website presence + tags/notes.
