# Tyopaikka-tutka — hiring signal scanner

This repo finds hiring signals from company websites near Finnish railway stations.
The data backbone is the PRH business registry (open data, permanent), enriched with
Photon geocoding and optionally Google Places. Companies are classified by industry
using Finnish TOI (NACE Rev2) codes.

## Covered areas
Lahti, Kerava, Savio, Pasila — ~1.5 km radius from each railway station.

## Pipeline

### 1. Street discovery (one-time, cached)
Fetches named roads within the station radius from OpenStreetMap via Overpass API.
```
python scripts/discover_streets.py
```
Output: `data/area_streets.json`

### 2. PRH registry fetch
Downloads all active companies from the PRH open-data API filtered by station area streets.
Passive shell companies (Asunto Oy, Kiinteistö Oy, TOI 6820x) are excluded automatically.
```
python scripts/fetch_prh_area.py --areas Lahti Kerava Savio Pasila --out data/prh_registry.parquet
```
Output: `data/prh_registry.parquet` (~13,600 raw companies)

### 3. Geocode & filter
Resolves company postcodes to coordinates via Photon (no API key needed), filters by
distance to station, and writes the enriched dataset. Use `--no-filter-passive` to keep
housing companies.
```
python scripts/enrich_google.py --max-distance-km 1.5
```
Output: `out/companies.csv` (~8,050 companies with industry labels and coordinates)

### 4. Analysis
```
python scripts/analyze_companies.py
```

### 5. Hiring-signal scan (Ollama)
Scans company websites for active hiring signals using a local LLM.
```
python -m apprscan scan --station Lahti --max-distance-km 1.0 --limit 50 --out out/hiring_signal_lahti_50.csv
```

## Key output: `out/companies.csv`
Columns: `name`, `business_id`, `industry`, `toi_code`, `toi_description`, `nearest_station`,
`distance_km`, `address`, `website`, `status`, `registered`, `lat`, `lon`

Industry groups: `it`, `construction`, `wholesale`, `marketing`, `health`, `manufacturing`,
`logistics`, `finance`, `retail`, `hospitality`, `education`, `engineering`, `staffing`,
`real_estate`, `other`

## Legacy flow (Google Places based)
1) Build a master from Places CSVs
   - `python scripts/places_to_master.py --station "Lahti,60.9836,25.6577,out/places_lahti.csv" --out out/master_places.xlsx`
2) Optional: curate in Streamlit
   - `streamlit run streamlit_app.py`
3) Build domains from Places websites
   - `python -m apprscan domains --companies out/master_places.xlsx --out domains.csv`

## Quality gate
- Run the one-button check before shipping or sharing outputs:
  - `python -m apprscan check`

## What the Ollama scan does
- Filters companies by nearest station and distance.
- Picks 1-2 candidate URLs (homepage + careers hint if found).
- Fetches those pages and uses heuristics with LLM fallback to classify: `yes`, `no`, or `unclear`.
- Requires 2-6 evidence snippets + URLs for `yes`/`no` or downgrades to `unclear`.
- Writes a CSV with signals, confidence, evidence, and any HTTP errors.

## Outputs
- `out/master_places.xlsx` (Shortlist + Excluded)
- `domains.csv` (business_id, name, domain)
- `out/hiring_signal_lahti.csv` / `out/hiring_signal_lahti_50.csv`
- Output schema: `schemas/hiring_signal_output.schema.json`

## Results (latest run)
- Lahti, 1 km radius, 50 companies: yes=9, no=14, unclear=27
- Output file: `out/hiring_signal_lahti_50.csv`

## Evaluation harness
- Run heuristic checks against stored HTML fixtures:
  - `python -m apprscan.evaluate_hiring_signal`

## Deterministic mode
- Use `--deterministic` to set temperature to 0 for more reproducible LLM output.
- Output provenance includes `ollama_model`, `ollama_temperature`, `prompt_version`, and `tool_version`.

## Companion service (optional)
- Install server dependencies:
  - `pip install -e .[server]`
- Run the local service (localhost-only by default):
  - `apprscan serve --host 127.0.0.1 --port 8787`
- The service prints `APPRSCAN token: ...` which must be sent as `X-APPRSCAN-TOKEN`.
- Optional env controls:
  - `APPRSCAN_CORS_ORIGINS` (comma-separated allowed origins)
  - `APPRSCAN_RATE_LIMIT_MAX` (per-token requests / window, default 10)
  - `APPRSCAN_RATE_LIMIT_WINDOW_S` (seconds, default 60)
  - `APPRSCAN_MAX_BODY_BYTES` (default 10240)
  - `APPRSCAN_RETENTION_DAYS` (default 30)
- Endpoints:
  - `POST /ingest/maps` with `{ "maps_url": "https://www.google.com/maps/..." }`
  - `GET /result/{run_id}`
- Company package schema: `src/apprscan/schemas/company_package.schema.json`
- Output files per run: `out/runs/<run_id>/company_package.json` and `company_package.md`
- Status mapping:
  - `ok`: website resolved, scan completed.
  - `degraded`: expected limitation (missing website, cookie wall, robots/JS-only).
  - `error`: invalid request or upstream failure.

## Requirements
- Python environment (see install below)
- Local Ollama running
- Configure Ollama via environment variables or repo `.env` (see `.env.example`)

## Install
```
python -m venv .venv && .\.venv\Scripts\activate
pip install -e .[dev]
```

## Optional (heavy): full jobs crawl
If you want actual job listings, the jobs crawler is still available, but it is slower.
```
python -m apprscan jobs --companies out/master_places.xlsx --domains domains.csv --out out/jobs_places --max-domains 50 --max-pages-per-domain 5
```

## Config and docs
- Industry groups: `config/industry_groups.yaml`
- Profiles: `config/profiles.yaml`
- Workflow notes: `docs/WORKFLOW.md`
- Output contract: `docs/OUTPUT_CONTRACT.md`
