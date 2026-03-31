"""Local JSON persistence for blocklists, category rules, and optional job cache."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from talenthawk.settings import (
    BLOCKLIST_FILE,
    CATEGORY_KEYWORDS_FILE,
    DEFAULT_BLOCKLIST,
    DEFAULT_CATEGORY_KEYWORDS,
    JOBS_CACHE_FILE,
    PERSISTENCE_DIR,
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


def load_blocklist() -> list[str]:
    raw = _read_json(BLOCKLIST_FILE, DEFAULT_BLOCKLIST.copy())
    if not isinstance(raw, list):
        return list(DEFAULT_BLOCKLIST)
    return [str(x).strip() for x in raw if str(x).strip()]


def save_blocklist(companies: list[str]) -> None:
    cleaned = sorted({c.strip() for c in companies if c and c.strip()}, key=str.lower)
    _write_json(BLOCKLIST_FILE, cleaned)


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
        "blocklist": BLOCKLIST_FILE,
        "category_keywords": CATEGORY_KEYWORDS_FILE,
        "jobs_cache": JOBS_CACHE_FILE,
    }
