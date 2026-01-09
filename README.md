# Hiring signal scanner (Places -> domains -> Ollama)

This repo focuses on finding hiring signals from company websites near a station.
We start from Google Places CSV exports, build a master list, map domains, and
run a lightweight Ollama scan that checks a couple of pages per company.

## Recap
We simplified a complex data-cleaning pipeline by using local agents to classify hiring signals,
and delivered a working scan in a short turnaround from the git baseline.

## Current flow (Lahti example)
1) Build a master from Places CSVs
   - `python scripts/places_to_master.py --station "Lahti,60.9836,25.6577,out/places_lahti.csv" --out out/master_places.xlsx`
2) Optional: curate in Streamlit (hide housing-like names, add tags)
   - `streamlit run streamlit_app.py`
3) Build domains from Places websites
   - `python -m apprscan domains --companies out/master_places.xlsx --out domains.csv`
4) Ollama hiring-signal scan (1 km radius, 10-50 companies)
   - `python -m apprscan scan --station Lahti --max-distance-km 1.0 --limit 50 --out out/hiring_signal_lahti_50.csv`

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
