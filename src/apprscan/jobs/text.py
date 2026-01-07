"""Text helpers."""

from __future__ import annotations

from bs4 import BeautifulSoup


def clean_html_snippet(html: str, limit: int = 300) -> str:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    return text[:limit]
