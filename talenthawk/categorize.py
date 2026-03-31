"""Map job titles to categories using configurable keyword rules."""

from __future__ import annotations

from typing import Any


def categorize_title(title: str, categories: list[dict[str, Any]]) -> str:
    t = " " + title.lower().strip() + " "
    for cat in categories:
        name = cat.get("name", "")
        kws = cat.get("keywords", [])
        if not name or not isinstance(kws, list):
            continue
        for kw in kws:
            if not kw:
                continue
            needle = kw.lower().strip()
            if not needle:
                continue
            if needle in t:
                return str(name)
    return "Other"
