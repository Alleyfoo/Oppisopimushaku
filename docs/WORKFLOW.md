# Workflow (browse first, crawl optional)

## 1) Browse (no crawling)
- Run once to create artifacts (cities and radius as needed):  
  `python -m apprscan run --cities "Helsinki,Espoo,Vantaa,Kerava,Mäntsälä,Lahti" --radius-km 1.0 --max-pages 3 --include-excluded --out out/run_YYYYMMDD --master-xlsx out/master_YYYYMMDD.xlsx`
- Artifacts you open:
  - `out/master_YYYYMMDD.xlsx` → Shortlist (pisteet, etäisyys, industry)
  - `out/run_YYYYMMDD/jobs/diff.xlsx` → uudet työpaikat (jos jobs ajettu)
  - `out/run_YYYYMMDD/jobs/jobs.xlsx` → kaikki jobit (jos jobs ajettu)
- Kartta ja analytiikka ilman uutta crawlia:  
  `python -m apprscan map --mode companies --sheet all --industries it,marketing --max-distance-km 1.5`  
  `python -m apprscan analytics --master-xlsx out/master_YYYYMMDD.xlsx --jobs-xlsx out/run_YYYYMMDD/jobs/jobs.xlsx --jobs-diff out/run_YYYYMMDD/jobs/diff.xlsx --out out/analytics_YYYYMMDD.xlsx`

## 2) Shortlist (human in the loop)
- Shortlist on sopimus: jobs-crawl lukee oletuksena vain Shortlist-sheetin.  
- Käytä master.xlsx:ää (Shortlist) ja karttaa/analyticsia päättääksesi ketkä ovat kiinnostavia.
- Industry-ryhmät ovat muokattavissa: `config/industry_groups.yaml`.

## 3) Outreach (manuaalinen)
- Avaa kartta (HTML) ja analytics, klikkaa job/website-linkkejä ja tee outreach työkalun ulkopuolella.
- Kopioi business_id + linkki popupista; Top_Companies/Industry_Summary auttaa priorisoimaan.

## 4) (Optional) Crawl jobs
- Heavier step, aja vain kun haluat tuoreita job-signaaleja:  
  `python -m apprscan jobs --companies out/run_YYYYMMDD/companies.xlsx --domains domains.csv --suggested domains_suggested.csv --out out/run_YYYYMMDD/jobs --max-domains 20 --max-pages-per-domain 5`
- Päivitä master & raportit:  
  `python -m apprscan run --cities ... --activity-file out/run_YYYYMMDD/jobs/company_activity.xlsx --master-xlsx out/master_YYYYMMDD.xlsx --out out/run_YYYYMMDD`  
  `python -m apprscan watch` (automaattisesti uusin master/diff)  
  `python -m apprscan map` (automaattisesti uusin master/diff)
