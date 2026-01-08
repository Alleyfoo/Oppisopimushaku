# Workflow (kenttäopas, 1 sivu)

## 0) Perusajatus
Browse → Curate → Act → Publish. Crawlia tarvitaan vain, kun haluat tuoreet job-signaalit.

## A) Browse & curate (ei verkkoa)
- Avaa editori: `streamlit run streamlit_app.py` (käyttää automaattisesti `out/`-hakemiston uusimpia master/diff/curation-artefakteja, tai anna polut käsin).
- Käytä presettejä ja filttereitä, lisää note/tagit, shortlist/exclude/hide.
- Dry-run summary näyttää muutokset; Commit kirjoittaa overlayn backupilla. Undo löytyy Audit-tabista.

## B) Act (export)
- Nappi “Export outreach.xlsx” vie nykyisen filtterinäkymän (Outreach + Meta sheet: polut, päivämäärät, filtterit).

## C) Publish (map/watch)
- Tarvitset jaettavan näkymän? Aja:
  - `python -m apprscan map` → HTML-kartta (käyttää uusimpia artefakteja automaattisesti).
  - `python -m apprscan watch` → teksti-/raporttinäkymä (jos käytössä).

## D) Optional: refresh data (crawl)
- Kun haluat päivittää lähdedatan:
  - `python -m apprscan run --cities "Helsinki,Espoo,Vantaa,Kerava,Mäntsälä,Lahti" --radius-km 1.0 --max-pages 3 --include-excluded --out out/run_YYYYMMDD --master-xlsx out/master_YYYYMMDD.xlsx`
  - (valinnainen) jobs-crawl: `python -m apprscan jobs --companies out/run_YYYYMMDD/companies.xlsx --domains domains.csv --suggested domains_suggested.csv --out out/run_YYYYMMDD/jobs --max-domains 20 --max-pages-per-domain 5`
  - Päivitä master + raportit: `python -m apprscan run ... --activity-file out/run_YYYYMMDD/jobs/company_activity.xlsx --master-xlsx out/master_YYYYMMDD.xlsx --out out/run_YYYYMMDD`

## Troubleshooting
- Master/diff mismatch: anna polut eksplisiittisesti tai käytä samaa run-id:tä.
- Commit blocked: masterin `business_id` puuttuu/ei ole uniikki → korjaa masterin lähteessä ja aja run uudelleen.
- Kartta ei vastaa editoria: varmista että käytät viimeisintä masteria ja ettei preview pending -tila ole päällä.
