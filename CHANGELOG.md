# Changelog

## v0.7.0 (2026-01-09)
- Jobs view: selected company dropdown + open in Inspector.
- Inspector: next/prev navigation and "opened from jobs" badge.
- Focus mode: one-company view with banner + sidebar clear button.
- Sidebar status line shows focus + view context + pending count.
- Hiring scan: `apprscan scan` CLI for Ollama-based hiring signal checks.
- Portability: repo-local `.env` support and `.env.example`.
- Scan outputs now include run provenance (run_id, git_sha, tool_version, crawl_ts).
- Robots handling now fails closed when robots.txt is unavailable.
- Added heuristic evaluation harness for hiring-signal fixtures.
- Added output contract schema + validation tests for hiring-signal outputs.
- CI now runs the fixture evaluator and version consistency check.
- Hiring scan downgrades decisions without evidence snippets + URLs to "unclear".
- CI enforces minimum precision/recall and max-uncertain thresholds for the hiring fixtures.
- Added `deterministic` flag to outputs and documented the output contract.
- Added optional companion service (`apprscan serve`) with URL-only Maps ingest and company package schema.

Migration notes:
- Hiring scan outputs include evidence arrays, provenance fields, and optional `deterministic`.
- CSV stores evidence arrays as JSON strings; update downstream parsers accordingly.

## v0.5.0
- Streamlit editor: presets, safe commit/undo, outreach export with meta sheet.
- One “effective view” for UI/CLI so map/watch use the same filters.
- City filters in Streamlit and CLI, with Mäntsälä/Mantsala normalization.
- CLI encoding cleaned, added .editorconfig to keep UTF-8 + spaces.
- Housing filtering unified via `is_housing_company` (domains, map, filters).
- `run --skip-geocode` now keeps lat/lon columns and reports omitted rows.
- Map markers: radius scaling and size controls; housing skipped via shared helper.
- Added CLI smoke tests for help/map/watch to catch regressions early.
