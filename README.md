# Apprenticeship Employer Scanner (Oppisopimushaku)

Browse first, crawl optional. Työkalu shortlistaukseen, karttaan ja analytiikkaan PRH/YTJ-datasta; jobs-crawl on lisäbonus, ei oletus.

## 3-step happy path
1) **Browse & curate (ei verkkoa)**
   - Aja run, avaa editori: `streamlit run streamlit_app.py` (auto-resolvoi `out/`-artefaktit tai anna polut).
   - Käytä presettejä/filttereitä, lisää note/tagit, shortlist/exclude/hide. Dry-run → Commit (backup + audit) → Undo Audit-tabista tarvittaessa.
2) **Act**
   - Export outreach.xlsx nykyisestä filtterinäkymästä (Outreach + Meta sheet: polut, päivämäärät, filtterit).
3) **Publish**
   - Jaettava kartta/watch: `python -m apprscan map` ja `python -m apprscan watch` (automaattisesti uusimmat artefaktit, tai anna polut).

Optional (raskas): jobs-crawl, jos haluat tuoreet job-signaalit.

## Artefaktit
- `out/master_YYYYMMDD.xlsx` (Shortlist, industry, score, etäisyydet)
- `out/run_YYYYMMDD/jobs/diff.xlsx` (uudet jobit)
- `out/run_YYYYMMDD/jobs/jobs.xlsx` (kaikki jobit)

## Asennus
```
python -m venv .venv && .\.venv\Scripts\activate   # tai source .venv/bin/activate
pip install -e .[dev]   # tai pip install -r requirements-dev.txt
```

## Nopeasti alkuun
- Apu: `python -m apprscan --help`
- Kartta: `python -m apprscan map`
- Watch: `python -m apprscan watch`
- Run (esim.): `python -m apprscan run --cities "Helsinki,Espoo,Vantaa,Kerava,Mäntsälä,Lahti" --radius-km 1.0 --max-pages 3 --include-excluded --out out/run_YYYYMMDD --master-xlsx out/master_YYYYMMDD.xlsx`
- Jobs-crawl (valinnainen): `python -m apprscan jobs --companies out/run_YYYYMMDD/companies.xlsx --domains domains.csv --suggested domains_suggested.csv --out out/run_YYYYMMDD/jobs --max-domains 20 --max-pages-per-domain 5`

## Konfiguraatio
- Industry-ryhmät: `config/industry_groups.yaml` (pisin prefix voittaa).
- Profiilit: `config/profiles.yaml` (valitse yksi ja käytä `--profile`).
- Geokoodaus cache: `--geocode-cache` (oletus `data/geocode_cache.sqlite`, .gitignore:ssa).
- Asemadata: `data/stations_fi.csv` tai oma `--stations-file`.

## Kehitys ja testit
- Lint: `ruff check .` (format: `ruff format .`)
- Testit: `python -m pytest`
- Tavoite: `python -m apprscan --help` toimii ja testit ajettavissa.

Lisäohje: katso myös `docs/WORKFLOW.md` (kenttäopas, <2 min lukuaika).
