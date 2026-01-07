"""Canonical JobPosting model."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any


@dataclass
class JobPosting:
    company_business_id: str
    company_name: str
    company_domain: str
    job_title: str
    job_url: str
    location_text: str | None = None
    employment_type: str | None = None
    posted_date: str | None = None
    description_snippet: str | None = None
    source: str = "unknown"
    tags: List[str] = field(default_factory=list)
    crawl_ts: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
