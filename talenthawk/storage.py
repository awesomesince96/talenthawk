"""Local JSON persistence for filters, category rules, and optional job cache."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from talenthawk.settings import (
    CATEGORY_KEYWORDS_FILE,
    COMPANY_FILTER_FILE,
    DEFAULT_CATEGORY_KEYWORDS,
    DEFAULT_FILTER_LIST,
    JOBS_CACHE_FILE,
    LEGACY_BLOCKLIST_2_FILE,
    LEGACY_BLOCKLIST_FILE,
    PERSISTENCE_DIR,
    TITLE_FILTER_FILE,
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


def migrate_legacy_company_blocklists_if_needed() -> None:
    """Create ``company_filter.json`` if missing, merging legacy ``companies_blocklist*.json`` when present."""
    if COMPANY_FILTER_FILE.exists():
        return
    merged: list[str] = []
    for path in (LEGACY_BLOCKLIST_FILE, LEGACY_BLOCKLIST_2_FILE):
        merged.extend(_normalize_filter_list(_read_json(path, [])))
    cleaned = sorted({c.strip() for c in merged if c and c.strip()}, key=str.lower)
    _write_json(COMPANY_FILTER_FILE, cleaned)


def load_title_filters() -> list[str]:
    raw = _read_json(TITLE_FILTER_FILE, DEFAULT_FILTER_LIST.copy())
    return _normalize_filter_list(raw)


def save_title_filters(entries: list[str]) -> None:
    cleaned = sorted({e.strip() for e in entries if e and e.strip()}, key=str.lower)
    _write_json(TITLE_FILTER_FILE, cleaned)


def load_company_filters() -> list[str]:
    raw = _read_json(COMPANY_FILTER_FILE, DEFAULT_FILTER_LIST.copy())
    return _normalize_filter_list(raw)


def save_company_filters(entries: list[str]) -> None:
    cleaned = sorted({e.strip() for e in entries if e and e.strip()}, key=str.lower)
    _write_json(COMPANY_FILTER_FILE, cleaned)


def load_category_keywords() -> list[dict[str, Any]]:
    raw = _read_json(CATEGORY_KEYWORDS_FILE, None)
    if raw is None:
        return [dict(x) for x in DEFAULT_CATEGORY_KEYWORDS]
    if not isinstance(raw, list):
        return [dict(x) for x in DEFAULT_CATEGORY_KEYWORDS]
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        kws = item.get("keywords")
        if isinstance(name, str) and isinstance(kws, list):
            out.append({"name": name.strip(), "keywords": [str(k).strip().lower() for k in kws if str(k).strip()]})
    return out if out else [dict(x) for x in DEFAULT_CATEGORY_KEYWORDS]


def save_category_keywords(categories: list[dict[str, Any]]) -> None:
    _write_json(CATEGORY_KEYWORDS_FILE, categories)


def load_jobs_cache() -> dict[str, Any] | None:
    raw = _read_json(JOBS_CACHE_FILE, None)
    if isinstance(raw, dict) and "fetched_at" in raw and "jobs" in raw:
        return raw
    return None


def save_jobs_cache(jobs: list[dict[str, Any]], fetched_at_iso: str) -> None:
    _write_json(JOBS_CACHE_FILE, {"fetched_at": fetched_at_iso, "jobs": jobs})


def persistence_paths() -> dict[str, Path]:
    return {
        "persistence_dir": PERSISTENCE_DIR,
        "title_filter": TITLE_FILTER_FILE,
        "company_filter": COMPANY_FILTER_FILE,
        "category_keywords": CATEGORY_KEYWORDS_FILE,
        "jobs_cache": JOBS_CACHE_FILE,
    }
