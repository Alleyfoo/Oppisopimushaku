# Apprenticeship Employer Scanner (Oppisopimushaku)

Työkalu, joka kokoaa shortlistan työnantajista (Uusimaa + Lahti/Päijät-Häme) oppisopimusmahdollisuuksia varten. Lähtökohtana on PRH/YTJ API:n data, geokoodaus Nominatimilla ja raportointi Excel/GeoJSON/HTML-karttana.

## Mitä tämä tekee / ei tee
- Hakee yrityksiä PRH/YTJ:stä, geokoodaa osoitteet ja pisteyttää sijainnin mukaan.
- Suodattaa pois taloyhtiöt ja muut ei-työnantaja -muodot; tukee toimialan whitelist/blacklist -rajausta.
- Tukee työntekijämäärän kynnystä, jos data on saatavilla erillisestä CSV:stä.
- (V2+) Etsii kevyesti “oppisopimus” -signaaleja shortlistatuista yrityksistä rajatulla ja kohteliaalla crawlilla.
- Ei yritä listata kaikkia oppisopimuspaikkoja “totuutena”, eikä tee aggressiivista web-scrapea.

## Asennus
1) Luo ja aktivoi virtuaaliympäristö (esim. `python -m venv .venv && .\.venv\Scripts\activate` tai `source .venv/bin/activate`).
2) Asenna riippuvuudet:
   - `pip install -e .[dev]` (sisältää ruff + pytest) tai
   - `pip install -r requirements-dev.txt`

## Nopeasti alkuun
- Tulosta apu: `python -m apprscan --help`
- Esimerkki:\
  `apprscan run --cities Helsinki,Espoo,Vantaa,Lahti --radius-km 1.0 --out out/ --max-pages 3 --include-excluded --whitelist koulutus --blacklist holding`\
  `apprscan run --cities Helsinki --employee-csv employees.csv --out out/`\
  `apprscan jobs --companies out/companies.xlsx --domains domains.csv --out out/jobs --max-domains 100 --max-pages-per-domain 20 --rate-limit 1.0`\
  `python scripts/pipeline.py --cities Helsinki,Espoo,Vantaa,Lahti --include-excluded` (ajaa run -> jobs -> run activityllä -> master.xlsx -> watch_report.txt)

## Konfiguraatio ja oletukset
- Kaupungit: CSV-lista `--cities`-argumentissa (tuki config-tiedostolle tulossa).
- Sijainti: geokoodaus Nominatimilla, jossa on 1 s rate limit; SQLite-välimuisti (`data/geocode_cache.sqlite`, polku konfiguroitavissa `--geocode-cache`) estää turhat kyselyt. Cache on .gitignore:ssa.
- Asemadata: Trainline CSV tai paikallinen `data/stations_fi.csv`, jos halutaan deterministinen ja nopea ajo.
- Toimialasuodatus: whitelist + blacklist TOL-koodeille tai teksti-osumille.
- Työntekijämäärä: erillinen CSV enrichment (`businessId,employee_count/employee_band`), jonka lähde tallennetaan raporttiin.
- Job-diff fingerprint normalisoi yleistä kohinaa (case/whitespace ja esim. “, Finland”) vähentääkseen turhia “new job” -hälytyksiä.

## Outputit
- Excel (Shortlist + haluttaessa Excluded), GeoJSON ja HTML-kartta (folium) kansioon `--out` (oletus `out/`).
- Vakiosarakkeet (tyhjä sallittu): business_id, name, company_form, main_business_line, domicile_city/_source_city, street, post_code, city, full_address, lat, lon, nearest_station, distance_km, score, score_reasons, excluded_reason, employee_count, employee_band, employee_source, employee_gate, oppisopimus_hit, oppisopimus_class, evidence_url, evidence_snippet.

## Kehitys ja testit
- Lint: `ruff check .` ja format: `ruff format .`
- Testit: `pytest`
- Tavoite: `python -m apprscan --help` toimii ja testit ajettavissa.

## Muistiinpanot
- Nominatimilla on tiukat käyttöehdot; käytä välimuistia ja pidä viive vähintään 1 s.
- Tutkimusmateriaali: alkuperäinen Colab-export sijoitetaan tiedostoon `research/work_commute_scanner_original.py` (ei sisälly repoihin).
