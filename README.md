# Apprenticeship Employer Scanner (Oppisopimushaku)

“Browse first, crawl optional.” Työkalu, joka tekee shortlistauksen, kartan ja analytiikan PRH/YTJ-datasta; jobs-crawl on lisäbonus, ei oletus.

## 3-step workflow
1) **Browse**  
   - Aja run, avaa master.xlsx (Shortlist) + kartta/analytics.  
   - Esim. `python -m apprscan run --cities "Helsinki,Espoo,Vantaa,Kerava,Mäntsälä,Lahti" --radius-km 1.0 --max-pages 3 --include-excluded --out out/run_YYYYMMDD --master-xlsx out/master_YYYYMMDD.xlsx`
   - Kartta/analytics ilman lisä-crawlia: `apprscan map` ja `apprscan analytics` käyttävät uusimpia artefakteja automaattisesti.
2) **Shortlist (human)**  
   - Shortlist-sheet on se mitä kuratoit; jobs-crawl lukee oletuksena vain Shortlistin.  
   - Industry-ryhmät muokattavissa: `config/industry_groups.yaml`.
3) **Outreach (manual)**  
   - Avaa HTML-kartta, klikkaa job/website-linkkejä, tee yhteydenotot työkalun ulkopuolella. Crawl on lisäbonus, ei pakollinen.

Optional: jobs-crawl (raskas) jos haluat tuoreet job-signaalit. Pipeline (run → jobs → run activity → watch/map/analytics) on valmiina.

## Artefaktit
- `out/master_YYYYMMDD.xlsx` (Shortlist + haluttaessa Excluded, includes industry)  
- `out/run_YYYYMMDD/jobs/diff.xlsx` (uudet jobit)  
- `out/run_YYYYMMDD/jobs/jobs.xlsx` (kaikki jobit)

## Asennus
1) `python -m venv .venv && .\.venv\Scripts\activate` (tai `source .venv/bin/activate`)  
2) `pip install -e .[dev]` (tai `pip install -r requirements-dev.txt`)

## Nopeasti alkuun
- Apu: `python -m apprscan --help`
- Kartta (uusiin artefakteihin automaattisesti): `python -m apprscan map`
- Watch (uusiin artefakteihin automaattisesti): `python -m apprscan watch`
- Jobs-crawl: `python -m apprscan jobs --companies out/run_YYYYMMDD/companies.xlsx --domains domains.csv --suggested domains_suggested.csv --out out/run_YYYYMMDD/jobs --max-domains 20 --max-pages-per-domain 5`

## Konfiguraatio
- Industry-ryhmät: `config/industry_groups.yaml` (pisin prefix voittaa).  
- Profiilit: `config/profiles.yaml` (valitse yksi ja käytä `--profile`).  
- Geokoodaus cache: `--geocode-cache` (oletus data/geocode_cache.sqlite, .gitignore:ssa).  
- Asemadata: `data/stations_fi.csv` tai oma `--stations-file`.

## Kehitys ja testit
- Lint: `ruff check .` (format: `ruff format .`)  
- Testit: `pytest`  
- Tavoite: `python -m apprscan --help` toimii ja testit ajettavissa.

Lisäohje: katso myös `docs/WORKFLOW.md` (kenttäopas, <2 min lukuaika).
