# Next Plan (Places -> domains -> Ollama hiring signals)

Goal: build a station-focused hiring signal list with lightweight page checks.

1) Build master from Places CSVs
- Inputs: `out/places_lahti.csv` (and other station exports as needed)
- Command:
  `python scripts/places_to_master.py --station "Lahti,60.9836,25.6577,out/places_lahti.csv" --out out/master_places.xlsx`

2) Optional curation
- Open Streamlit: `streamlit run curate_app.py`
- Hide housing-like names, add notes/tags, shortlist

3) Domain mapping
- Extract domains from Places websites:
  `python -m apprscan domains --companies out/master_places.xlsx --out domains.csv`

4) Hiring signal scan (local Ollama)
- Start with Lahti station, 1 km radius, 50 companies:
  `python -m apprscan scan --station Lahti --max-distance-km 1.0 --limit 50 --out out/hiring_signal_lahti_50.csv`

Notes
- The scan checks 1-2 URLs per company and classifies `yes/no/unclear`.
- Full jobs crawl is still possible but slower; use only if needed.
- Configure Ollama via environment variables or repo `.env` (see `.env.example`).
- Run `python -m apprscan check` before sharing outputs.
