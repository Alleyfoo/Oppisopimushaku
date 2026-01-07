"""Deterministic tagging for job postings."""

from __future__ import annotations

from typing import Dict, List

DEFAULT_TAG_RULES: Dict[str, List[str]] = {
    "oppisopimus": ["oppisopimus", "apprentice"],
    "trainee": ["trainee", "harjoittel", "intern"],
    "junior": ["junior"],
    "data": ["data", "analyyt", "analytics", "bi ", " sql", "sql "],
    "it_support": ["it-tuki", "helpdesk", "service desk", "support"],
    "marketing": ["marketing", "markkinointi"],
    "salesforce": ["salesforce"],
}


def detect_tags(text: str, rules: Dict[str, List[str]] | None = None) -> List[str]:
    rules = rules or DEFAULT_TAG_RULES
    lower = text.lower()
    tags: List[str] = []
    for tag, keywords in rules.items():
        if any(kw.lower() in lower for kw in keywords):
            tags.append(tag)
    return tags
