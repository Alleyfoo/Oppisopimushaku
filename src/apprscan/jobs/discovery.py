"""Domain discovery for careers pages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, FeatureNotFound

COMMON_PATHS = [
    "/careers",
    "/jobs",
    "/rekry",
    "/tyopaikat",
    "/ura",
    "/open-positions",
    "/positions",
    "/join-us",
]

SITEMAP_KEYWORDS = ["job", "career", "rekry", "tyopaikat", "ura"]


@dataclass
class DiscoveryResult:
    domain: str
    seed_urls: List[str] = field(default_factory=list)
    stats: Dict[str, object] = field(default_factory=dict)


def discover_paths(domain: str, existing: Optional[List[str]] = None) -> List[str]:
    base = f"https://{domain}"
    seeds = []
    seeds.extend(existing or [])
    for path in COMMON_PATHS:
        seeds.append(urljoin(base, path))
    return list(dict.fromkeys(seeds))  # dedup preserving order


def parse_sitemap(xml_text: str, base_url: str, max_urls: int = 200) -> List[str]:
    try:
        soup = BeautifulSoup(xml_text, "lxml-xml")
    except FeatureNotFound:
        try:
            soup = BeautifulSoup(xml_text, "xml")
        except FeatureNotFound:
            soup = BeautifulSoup(xml_text, "html.parser")
    urls = []
    for loc in soup.find_all("loc"):
        if len(urls) >= max_urls:
            break
        href = loc.get_text(strip=True)
        if not href:
            continue
        lowered = href.lower()
        if any(key in lowered for key in SITEMAP_KEYWORDS):
            urls.append(href)
    return urls


def filter_discovery_results(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True).lower()
        if any(k in href.lower() for k in SITEMAP_KEYWORDS) or any(
            kw in text for kw in SITEMAP_KEYWORDS
        ):
            urls.append(urljoin(base_url, href))
    return list(dict.fromkeys(urls))
