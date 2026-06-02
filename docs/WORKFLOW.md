# Workflow (quick guide)

## Overview
Places CSV -> master list -> domain map -> Ollama hiring signal scan.
The goal is to identify companies near a station that show recruiting signals
on their websites without running a full crawl.

## A) Build the master list
- Generate master from Places CSV exports:
  - `python scripts/places_to_master.py --station "Lahti,60.9836,25.6577,out/places_lahti.csv" --out out/master_places.xlsx`

## B) Optional: curate
- Open Streamlit editor to hide housing-like names and add notes/tags:
  - `streamlit run curate_app.py`

## C) Build domains
- Extract website domains from Places data:
  - `python -m apprscan domains --companies out/master_places.xlsx --out domains.csv`
- Optional: refresh missing website URLs via Places (requires API key):
  - `python scripts/places_details.py --master out/master_places.xlsx --out out/places_websites.csv --update-domains domains.csv`

## D) Hiring signal scan (Ollama)
- Scan companies near a station (example: Lahti, 1 km, 50 companies):
  - `python -m apprscan scan --station Lahti --max-distance-km 1.0 --limit 50 --out out/hiring_signal_lahti_50.csv`

## Outputs
- `out/master_places.xlsx` (Shortlist + Excluded)
- `domains.csv` (business_id, name, domain)
- `out/hiring_signal_lahti.csv` / `out/hiring_signal_lahti_50.csv`

## Quality gate
- Run `python -m apprscan check` to validate tests, fixtures, schema, and Ollama sanity.

## Notes
- The scan checks 1-2 URLs per company (homepage + careers hint if found).
- Results are `yes`, `no`, or `unclear` with confidence and evidence text.
- Configure Ollama via environment variables or repo `.env` (see `.env.example`).
- Full jobs crawl is still possible but slower.
