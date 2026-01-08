"""Google Places API (New) client helpers."""

from __future__ import annotations

import os
import time
from typing import Any, Iterable

import requests

API_URL = "https://places.googleapis.com/v1/places:searchText"
NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
DEFAULT_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.location,"
    "places.types,"
    "places.websiteUri,"
    "places.businessStatus"
)


def get_api_key(env_var: str = "GOOGLE_MAPS_API_KEY") -> str:
    key = os.getenv(env_var)
    if not key:
        raise RuntimeError(f"{env_var} is not set")
    return key


def _field_mask(field_mask: str | Iterable[str] | None) -> str:
    if field_mask is None:
        return DEFAULT_FIELD_MASK
    if isinstance(field_mask, str):
        return field_mask
    return ",".join(field_mask)


def search_text(
    query: str,
    *,
    api_key: str | None = None,
    region_code: str | None = "FI",
    language_code: str | None = "fi",
    page_size: int = 20,
    max_pages: int = 1,
    sleep_s: float = 2.0,
    field_mask: str | Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Search places by text query using Places API (New)."""
    key = api_key or get_api_key()
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": _field_mask(field_mask),
    }

    results: list[dict[str, Any]] = []
    payload: dict[str, Any] = {
        "textQuery": query,
        "pageSize": page_size,
    }
    if region_code:
        payload["regionCode"] = region_code
    if language_code:
        payload["languageCode"] = language_code

    page_token: str | None = None
    for page in range(max_pages):
        if page_token:
            payload = {"pageToken": page_token}
        resp = requests.post(API_URL, json=payload, headers=headers, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"Places API HTTP {resp.status_code}: {resp.text}")
        data = resp.json()
        places = data.get("places", [])
        for place in places:
            display = place.get("displayName") or {}
            location = place.get("location") or {}
            results.append(
                {
                    "place_id": place.get("id"),
                    "name": display.get("text") or "",
                    "formatted_address": place.get("formattedAddress"),
                    "lat": location.get("latitude"),
                    "lon": location.get("longitude"),
                    "types": place.get("types") or [],
                    "website": place.get("websiteUri"),
                    "business_status": place.get("businessStatus"),
                    "source": "google_places_new",
                }
            )
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(sleep_s)
    return results


def search_nearby(
    lat: float,
    lon: float,
    radius_m: float,
    *,
    included_type: str | None = None,
    api_key: str | None = None,
    region_code: str | None = "FI",
    language_code: str | None = "fi",
    max_results: int = 20,
    max_pages: int = 1,
    sleep_s: float = 2.0,
    field_mask: str | Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Search places near a point using Places API (New)."""
    key = api_key or get_api_key()
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": _field_mask(field_mask),
    }

    results: list[dict[str, Any]] = []
    payload: dict[str, Any] = {
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": radius_m,
            }
        },
        "maxResultCount": max_results,
    }
    if included_type:
        payload["includedTypes"] = [included_type]
    if region_code:
        payload["regionCode"] = region_code
    if language_code:
        payload["languageCode"] = language_code

    page_token: str | None = None
    for page in range(max_pages):
        if page_token:
            payload = {"pageToken": page_token}
        resp = requests.post(NEARBY_URL, json=payload, headers=headers, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"Places API HTTP {resp.status_code}: {resp.text}")
        data = resp.json()
        places = data.get("places", [])
        for place in places:
            display = place.get("displayName") or {}
            location = place.get("location") or {}
            results.append(
                {
                    "place_id": place.get("id"),
                    "name": display.get("text") or "",
                    "formatted_address": place.get("formattedAddress"),
                    "lat": location.get("latitude"),
                    "lon": location.get("longitude"),
                    "types": place.get("types") or [],
                    "website": place.get("websiteUri"),
                    "business_status": place.get("businessStatus"),
                    "source": "google_places_new",
                }
            )
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(sleep_s)
    return results
