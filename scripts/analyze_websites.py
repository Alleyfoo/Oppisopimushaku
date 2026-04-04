#!/usr/bin/env python
"""Analyze company websites with a local LLM via Ollama.

For each company that has a website (from PRH or discovered by discover_websites.py),
fetch the homepage and ask a local Ollama model to extract structured signals:
  - what they sell
  - whether they already have an online shop
  - technology platform if detectable
  - estimated headcount if mentioned
  - short Finnish description

Results are cached permanently in data/website_analysis.sqlite so the script
can be stopped and resumed.

Usage
-----
  # Install Ollama: https://ollama.com  then pull a model:
  #   ollama pull gemma4
  #
  # Analyse Kerava/Savio/Haarajoki companies (default):
  python scripts/analyze_websites.py

  # All areas:
  python scripts/analyze_websites.py --areas all

  # Custom model and area:
  python scripts/analyze_websites.py --model gemma4:27b --areas Lahti Kerava

  # Limit to N companies (for testing):
  python scripts/analyze_websites.py --limit 10

Output
------
Writes columns llm_has_shop, llm_platform, llm_headcount, llm_description
back to out/companies.csv in-place.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
import textwrap
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH   = _ROOT / "out" / "companies.csv"
CACHE_PATH = _ROOT / "data" / "website_analysis.sqlite"

OLLAMA_URL   = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "gemma4"
DEFAULT_AREAS = ["Haarajoki", "Savio", "Kerava"]

FETCH_TIMEOUT  = 15   # seconds for homepage fetch
OLLAMA_TIMEOUT = 120  # seconds for LLM response

PROMPT_TEMPLATE = textwrap.dedent("""\
    Olet yritysanalyytikko. Analysoi alla oleva yrityksen kotisivu ja vastaa
    AINOASTAAN yhdellä JSON-objektilla, ei muuta tekstiä. Älä käytä emojeja.

    JSON-rakenne:
    {{
      "has_shop": true/false,          // onko verkkokauppa tai ostoskorimahdollisuus
      "has_online_sales": true/false,  // voiko sivulta ostaa tai tilata jotain (myös tarjouspyyntö, kalenteri, jne.)
      "is_hiring": true/false,         // onko sivulla avoimia työpaikkoja tai rekrytointiosio
      "platform": "string or null",    // teknologia-alusta jos näkyy (esim. Shopify, WooCommerce, Magento, custom)
      "headcount": "string or null",   // henkilöstömäärä tai -arvio jos mainitaan, muuten null
      "sells": "string",               // lyhyt kuvaus mitä myyvät tai tekevät (max 15 sanaa, suomeksi)
      "description": "string"          // yksi lause yrityksestä suomeksi, myyntikelpoinen kuvaus
    }}

    Kotisivu (max 3000 merkkiä):
    {page_text}
""")

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _open_cache(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analysis (
            url TEXT PRIMARY KEY,
            result TEXT,
            fetched_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def _cache_get(conn: sqlite3.Connection, url: str) -> dict | None:
    row = conn.execute("SELECT result FROM analysis WHERE url=?", (url,)).fetchone()
    if row and row[0]:
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None
    return None


def _cache_set(conn: sqlite3.Connection, url: str, result: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO analysis (url, result) VALUES (?, ?)",
        (url, json.dumps(result, ensure_ascii=False)),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _ensure_scheme(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "https://" + url
    return url


def _fetch_page_text(url: str, max_chars: int = 3000) -> str | None:
    """Fetch homepage and return visible text (stripped of HTML tags)."""
    import re
    try:
        resp = httpx.get(
            _ensure_scheme(url),
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TyopaikkaSkanneri/1.0)"},
        )
        resp.raise_for_status()
        html = resp.text
    except Exception:
        return None

    # Strip scripts and styles
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    # Strip tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def _strip_emoji(text: str | None) -> str | None:
    """Remove emoji and other non-BMP characters from a string."""
    if not text:
        return text
    import re
    return re.sub(r"[^\u0000-\uFFFF]", "", text).strip()


def _call_ollama(page_text: str, model: str) -> dict | None:
    prompt = PROMPT_TEMPLATE.format(page_text=page_text)
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    try:
        resp = httpx.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        # Extract JSON from response
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        return json.loads(raw[start:end])
    except Exception as exc:
        print(f"    Ollama error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse company websites with Ollama")
    parser.add_argument("--areas", nargs="+", default=DEFAULT_AREAS,
                        help="Station names to process, or 'all'")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--limit", type=int, default=0, help="Max companies to process (0=all)")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds between requests")
    parser.add_argument("--reanalyze", action="store_true",
                        help="Re-analyse even if already cached")
    args = parser.parse_args()

    # Check Ollama reachability
    try:
        httpx.get("http://localhost:11434", timeout=3).raise_for_status()
    except Exception:
        print("ERROR: Ollama not reachable at localhost:11434.")
        print("  Start it with: ollama serve")
        print(f"  Then pull a model: ollama pull {args.model}")
        return

    df = pd.read_csv(CSV_PATH)
    if "found_website" not in df.columns:
        df["found_website"] = None
    df["best_website"] = df["website"].combine_first(df["found_website"])

    # Filter by area
    if args.areas != ["all"]:
        mask = df["nearest_station"].isin(args.areas)
        subset = df[mask & df["best_website"].notna()].copy()
    else:
        subset = df[df["best_website"].notna()].copy()

    if args.limit:
        subset = subset.head(args.limit)

    print(f"Companies to analyse: {len(subset)} "
          f"(areas: {', '.join(args.areas) if args.areas != ['all'] else 'all'})")
    print(f"Model: {args.model}\n")

    conn = _open_cache(CACHE_PATH)
    results: dict[str, dict] = {}

    for i, row in enumerate(subset.itertuples(), 1):
        url = str(row.best_website)
        name = row.name

        cached = None if args.reanalyze else _cache_get(conn, url)
        if cached is not None:
            print(f"[{i}/{len(subset)}] {name} — cached ✓")
            results[row.business_id] = cached
            continue

        print(f"[{i}/{len(subset)}] {name} ({url})", end=" ", flush=True)

        page_text = _fetch_page_text(url)
        if not page_text:
            print("— fetch failed, skip")
            continue

        result = _call_ollama(page_text, args.model)
        if result is None:
            print("— LLM failed, skip")
            continue

        # Sanitise text fields
        for field in ("platform", "headcount", "sells", "description"):
            result[field] = _strip_emoji(result.get(field))

        _cache_set(conn, url, result)
        results[row.business_id] = result

        shop_flag   = "🛒" if result.get("has_shop") else ("💶" if result.get("has_online_sales") else "  ")
        hire_flag   = " 📢" if result.get("is_hiring") else ""
        platform    = result.get("platform") or ""
        sells       = result.get("sells", "")[:60]
        print(f"{shop_flag}{hire_flag} {sells}  [{platform}]")

        time.sleep(args.sleep)

    conn.close()

    if not results:
        print("\nNo results to write.")
        return

    # Write results back to CSV
    df = pd.read_csv(CSV_PATH)
    df["best_website"] = df["website"].combine_first(
        df["found_website"] if "found_website" in df.columns else pd.Series(dtype=str)
    )

    for col in ["llm_has_shop", "llm_has_online_sales", "llm_is_hiring",
                "llm_platform", "llm_headcount", "llm_sells", "llm_description"]:
        if col not in df.columns:
            df[col] = None

    for biz_id, res in results.items():
        mask = df["business_id"] == biz_id
        df.loc[mask, "llm_has_shop"]         = res.get("has_shop")
        df.loc[mask, "llm_has_online_sales"] = res.get("has_online_sales")
        df.loc[mask, "llm_is_hiring"]        = res.get("is_hiring")
        df.loc[mask, "llm_platform"]         = res.get("platform")
        df.loc[mask, "llm_headcount"]        = res.get("headcount")
        df.loc[mask, "llm_sells"]            = res.get("sells")
        df.loc[mask, "llm_description"]      = res.get("description")

    df.drop(columns=["best_website"], errors="ignore").to_csv(
        CSV_PATH, index=False, encoding="utf-8-sig"
    )
    print(f"\nWrote {len(results)} results to {CSV_PATH}")


if __name__ == "__main__":
    main()
