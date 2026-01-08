"""Filtering utilities for company rows."""

from __future__ import annotations

import ast
import re
from typing import Any, Dict, Iterable, Tuple

HOUSING_FORMS = {
    "ASUNTO-OSAKEYHTIO",
    "AS OY",
    "ASUNTO OY",
    "ASUNTO-OSUUSKUNTA",
}

NAME_PATTERNS_RAW = [
    r"(?i)^\s*as\s*oy\b",
    r"(?i)\basunto\s*oy\b",
    r"(?i)\basunto[-\s]?osakeyhtio\b",
    r"(?i)\bkiinteisto\s*oy\b",
]
NAME_PATTERNS = [re.compile(pat) for pat in NAME_PATTERNS_RAW]


def is_housing_company(name: str | None) -> bool:
    """Return True if company name looks like housing company."""
    val = (name or "").strip()
    if not val:
        return False
    val_norm = (
        val.lower()
        .replace("ö", "o")
        .replace("ä", "a")
        .replace("å", "a")
    )
    for pat in NAME_PATTERNS:
        if pat.search(val_norm):
            return True
    return False


def _extract_name(company: Dict[str, Any]) -> str:
    candidates = [
        company.get("name"),
        company.get("names.0.name"),
    ]
    for cand in candidates:
        if cand:
            return str(cand).strip()
    raw = company.get("names")
    if isinstance(raw, list) and raw:
        first = raw[0] or {}
        if isinstance(first, dict):
            return str(first.get("name", "")).strip()
    if isinstance(raw, str) and raw.startswith("["):
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                return str(parsed[0].get("name", "")).strip()
        except Exception:
            pass
    return ""


def _extract_company_form(company: Dict[str, Any]) -> str:
    form_val = str(company.get("companyForm", "") or company.get("company_form", "") or "").strip().upper()
    if form_val:
        return form_val
    raw = company.get("companyForms")
    if isinstance(raw, list) and raw:
        first = raw[0] or {}
        val = first.get("name") or first.get("type") or ""
        if val:
            return str(val).strip().upper()
    if isinstance(raw, str) and raw.startswith("["):
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list) and parsed:
                val = parsed[0].get("name") or parsed[0].get("type") or ""
                return str(val).strip().upper()
        except Exception:
            pass
    return ""


def exclude_company(company: Dict[str, Any]) -> Tuple[bool, str | None]:
    """Return (excluded_bool, reason)."""
    form_val = _extract_company_form(company)
    form_norm = (
        form_val.replace("Ö", "O")
        .replace("Ä", "A")
        .replace("Å", "A")
        .replace("Õ", "O")
    )
    name_val = _extract_name(company)

    if form_norm in HOUSING_FORMS:
        return True, f"company_form:{form_val}"

    if is_housing_company(name_val):
        return True, "name_match:housing"

    return False, None


def industry_pass(
    company: Dict[str, Any],
    whitelist: Iterable[str],
    blacklist: Iterable[str],
) -> Tuple[bool, str | None, bool]:
    """Return (pass, reason, hard_fail)."""
    mbl = str(company.get("mainBusinessLine", "") or "").lower()
    wl = [s.lower() for s in whitelist if s]
    bl = [s.lower() for s in blacklist if s]

    for bad in bl:
        if bad and bad in mbl:
            return False, f"blacklist:{bad}", True

    if wl:
        for good in wl:
            if good and good in mbl:
                return True, f"whitelist:{good}", False
        # whitelist present but no match -> soft fail
        return False, "not_in_whitelist", False

    return True, None, False
