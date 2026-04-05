"""Local JSON persistence for title, company, and category filters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from talenthawk.settings import (
    CATEGORY_FILTER_FILE,
    COMPANY_FILTER_FILE,
    DEFAULT_FILTER_LIST,
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


def load_category_filters() -> list[str]:
    raw = _read_json(CATEGORY_FILTER_FILE, DEFAULT_FILTER_LIST.copy())
    return _normalize_filter_list(raw)


def save_category_filters(entries: list[str]) -> None:
    cleaned = sorted({e.strip() for e in entries if e and e.strip()}, key=str.lower)
    _write_json(CATEGORY_FILTER_FILE, cleaned)


def persistence_paths() -> dict[str, Path]:
    return {
        "persistence_dir": PERSISTENCE_DIR,
        "title_filter": TITLE_FILTER_FILE,
        "company_filter": COMPANY_FILTER_FILE,
        "category_filter": CATEGORY_FILTER_FILE,
    }
