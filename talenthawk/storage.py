"""Local JSON persistence for filters and SerpAPI sidebar preferences."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from talenthawk.settings import (
    CAREER_PAGE_MAPPINGS_FILE,
    CAREER_PAGE_TRACKER_FILTER_FILE,
    CATEGORY_FILTER_FILE,
    COMPANY_FILTER_FILE,
    DEFAULT_CAREER_PAGE_MAPPINGS,
    DEFAULT_CAREER_TRACKER_FILTER,
    DEFAULT_FILTER_LIST,
    DEFAULT_SERPAPI_LOCATION,
    DEFAULT_SERPAPI_QUERY,
    MAPPINGS_DIR,
    PERSISTENCE_DIR,
    SERPAPI_PREFS_FILE,
    TITLE_FILTER_FILE,
    TITLE_IGNORE_WORDS_FILE,
)


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data: Any) -> None:
    _ensure_dir(path)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _normalize_filter_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return list(DEFAULT_FILTER_LIST)
    return [str(x).strip() for x in raw if str(x).strip()]


def load_title_filters() -> list[str]:
    raw = _read_json(TITLE_FILTER_FILE, DEFAULT_FILTER_LIST.copy())
    return _normalize_filter_list(raw)


def save_title_filters(entries: list[str]) -> None:
    cleaned = sorted({e.strip() for e in entries if e and e.strip()}, key=str.lower)
    _write_json(TITLE_FILTER_FILE, cleaned)


def load_title_ignore_words() -> list[str]:
    raw = _read_json(TITLE_IGNORE_WORDS_FILE, DEFAULT_FILTER_LIST.copy())
    return _normalize_filter_list(raw)


def save_title_ignore_words(entries: list[str]) -> None:
    cleaned = sorted({e.strip() for e in entries if e and e.strip()}, key=str.lower)
    _write_json(TITLE_IGNORE_WORDS_FILE, cleaned)


def load_company_filters() -> list[str]:
    raw = _read_json(COMPANY_FILTER_FILE, DEFAULT_FILTER_LIST.copy())
    return _normalize_filter_list(raw)


def save_company_filters(entries: list[str]) -> None:
    cleaned = sorted({e.strip() for e in entries if e and e.strip()}, key=str.lower)
    _write_json(COMPANY_FILTER_FILE, cleaned)


def load_category_filters() -> list[str]:
    raw = _read_json(CATEGORY_FILTER_FILE, DEFAULT_FILTER_LIST.copy())
    return _normalize_filter_list(raw)


def save_category_filters(entries: list[str]) -> None:
    cleaned = sorted({e.strip() for e in entries if e and e.strip()}, key=str.lower)
    _write_json(CATEGORY_FILTER_FILE, cleaned)


def load_serpapi_prefs() -> dict[str, str]:
    """Last saved SerpAPI search query and location (local file only)."""
    default: dict[str, str] = {
        "query": DEFAULT_SERPAPI_QUERY,
        "location": DEFAULT_SERPAPI_LOCATION,
    }
    raw = _read_json(SERPAPI_PREFS_FILE, default.copy())
    if not isinstance(raw, dict):
        return default.copy()
    q = raw.get("query")
    loc = raw.get("location")
    out_q = str(q).strip() if q is not None else DEFAULT_SERPAPI_QUERY
    if not out_q:
        out_q = DEFAULT_SERPAPI_QUERY
    out_loc = str(loc).strip() if loc is not None else DEFAULT_SERPAPI_LOCATION
    return {"query": out_q, "location": out_loc}


def save_serpapi_prefs(query: str, location: str) -> None:
    """Persist SerpAPI query/location after a refresh (or attempted refresh)."""
    q = (query or "").strip() or DEFAULT_SERPAPI_QUERY
    loc = (location or "").strip()
    _write_json(SERPAPI_PREFS_FILE, {"query": q, "location": loc})


def load_career_page_mappings() -> dict[str, Any]:
    """Company id → careers list URL and fetcher (see ``DEFAULT_CAREER_PAGE_MAPPINGS``)."""
    legacy = PERSISTENCE_DIR / "career_page_mappings.json"
    if not CAREER_PAGE_MAPPINGS_FILE.exists() and legacy.exists():
        _ensure_dir(CAREER_PAGE_MAPPINGS_FILE)
        CAREER_PAGE_MAPPINGS_FILE.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
    if not CAREER_PAGE_MAPPINGS_FILE.exists():
        _write_json(CAREER_PAGE_MAPPINGS_FILE, DEFAULT_CAREER_PAGE_MAPPINGS)
    raw = _read_json(CAREER_PAGE_MAPPINGS_FILE, DEFAULT_CAREER_PAGE_MAPPINGS)
    if not isinstance(raw, dict):
        return dict(DEFAULT_CAREER_PAGE_MAPPINGS)
    comps = raw.get("companies")
    if not isinstance(comps, list):
        return dict(DEFAULT_CAREER_PAGE_MAPPINGS)
    return raw


def load_career_tracker_filter() -> list[str]:
    """Which company IDs are tracked in the Career page tracker tab."""
    if not CAREER_PAGE_TRACKER_FILTER_FILE.exists():
        _write_json(CAREER_PAGE_TRACKER_FILTER_FILE, DEFAULT_CAREER_TRACKER_FILTER)
    raw = _read_json(CAREER_PAGE_TRACKER_FILTER_FILE, DEFAULT_CAREER_TRACKER_FILTER.copy())
    if not isinstance(raw, list):
        return list(DEFAULT_CAREER_TRACKER_FILTER)
    out = [str(x).strip() for x in raw if str(x).strip()]
    return out or list(DEFAULT_CAREER_TRACKER_FILTER)


def save_career_tracker_filter(company_ids: list[str]) -> None:
    seen: set[str] = set()
    cleaned: list[str] = []
    for x in company_ids:
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            cleaned.append(s)
    _write_json(CAREER_PAGE_TRACKER_FILTER_FILE, cleaned)


def persistence_paths() -> dict[str, Path]:
    return {
        "persistence_dir": PERSISTENCE_DIR,
        "mappings_dir": MAPPINGS_DIR,
        "title_filter": TITLE_FILTER_FILE,
        "title_ignore_words": TITLE_IGNORE_WORDS_FILE,
        "company_filter": COMPANY_FILTER_FILE,
        "category_filter": CATEGORY_FILTER_FILE,
        "serpapi_prefs": SERPAPI_PREFS_FILE,
        "career_page_mappings": CAREER_PAGE_MAPPINGS_FILE,
        "career_page_tracker_filter": CAREER_PAGE_TRACKER_FILTER_FILE,
    }
