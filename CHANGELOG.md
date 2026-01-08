# Changelog

## v0.5.0 (unreleased)
- Streamlit editor: presets, safe commit/undo, outreach export with meta sheet.
- One “effective view” for UI/CLI so map/watch use the same filters.
- City filters in Streamlit and CLI, with Mäntsälä/Mantsala normalization.
- CLI encoding cleaned, added .editorconfig to keep UTF-8 + spaces.
- Housing filtering unified via `is_housing_company` (domains, map, filters).
- `run --skip-geocode` now keeps lat/lon columns and reports omitted rows.
- Map markers: radius scaling and size controls; housing skipped via shared helper.
- Added CLI smoke tests for help/map/watch to catch regressions early.
