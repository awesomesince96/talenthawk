"""Map job titles to category labels using built-in keyword rules (first match wins)."""

from __future__ import annotations

from typing import Any

DEFAULT_CATEGORY_KEYWORDS: list[dict[str, Any]] = [
    {"name": "Engineering", "keywords": ["engineer", "developer", "software", "devops", "sre", "backend", "frontend", "full stack", "fullstack"]},
    {"name": "Data & ML", "keywords": ["data scientist", "data engineer", "machine learning", "ml engineer", "analytics", "bi developer"]},
    {"name": "Product", "keywords": ["product manager", "product owner", "product lead", "technical program"]},
    {"name": "Design", "keywords": ["designer", "ux", "ui designer", "product design"]},
    {"name": "QA", "keywords": ["qa", "quality assurance", "test engineer", "sdet"]},
    {"name": "Security", "keywords": ["security", "infosec", "cyber"]},
    {"name": "Management", "keywords": ["cto", "vp engineering", "head of engineering", "engineering manager", "director"]},
]


def categorize_title(title: str, categories: list[dict[str, Any]] | None = None) -> str:
    rules = DEFAULT_CATEGORY_KEYWORDS if categories is None else categories
    t = " " + title.lower().strip() + " "
    for cat in rules:
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
