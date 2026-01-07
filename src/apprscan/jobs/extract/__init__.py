"""Extractors for job postings."""

from .jsonld import extract_jobs_from_jsonld
from .generic_html import extract_jobs_generic

__all__ = ["extract_jobs_from_jsonld", "extract_jobs_generic"]
