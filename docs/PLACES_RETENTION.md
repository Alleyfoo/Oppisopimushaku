# Places data retention note

Google Places outputs are treated as local-only cache files and are not committed.
Keep them only while actively working and purge after 30 days (or sooner if not needed).

Tracked source-of-truth fields:
- place_id
- derived fields (score, tags, hiring signal, scan provenance)

If you need Places details (name/address/website/lat/lng), re-fetch on demand and
do not use them on non-Google map renderers.
