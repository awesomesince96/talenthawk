"""On-disk cache for job listings under ``data/jobs/`` (TTL + config fingerprint)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from talenthawk.settings import JOBS_CACHE_CAREER_SUBDIR, JOBS_CACHE_DIR, JOBS_CACHE_FEED_SUBDIR

CACHE_FORMAT_VERSION = 1
DEFAULT_TTL_SECONDS = 4 * 60 * 60  # 4 hours


def jobs_career_cache_dir() -> Path:
    return JOBS_CACHE_DIR / JOBS_CACHE_CAREER_SUBDIR


def jobs_feed_cache_dir() -> Path:
    return JOBS_CACHE_DIR / JOBS_CACHE_FEED_SUBDIR


def ensure_jobs_cache_dirs() -> None:
    jobs_career_cache_dir().mkdir(parents=True, exist_ok=True)
    jobs_feed_cache_dir().mkdir(parents=True, exist_ok=True)


def _safe_id(s: str) -> str:
    out = "".join(c if c.isalnum() or c in "-_" else "_" for c in s.strip())[:120]
    return out or "unknown"


def career_cache_path(company_id: str) -> Path:
    return jobs_career_cache_dir() / f"{_safe_id(company_id)}.json"


def career_entry_fingerprint(entry: dict[str, Any]) -> str:
    """Stable hash of mapping fields that affect fetching (excludes ``display_name``)."""
    subset = {k: v for k, v in sorted(entry.items()) if k != "display_name"}
    raw = json.dumps(subset, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _parse_iso_utc(s: object) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_fresh(fetched_at: object, ttl_seconds: int) -> bool:
    dt = _parse_iso_utc(fetched_at) if isinstance(fetched_at, str) else None
    if dt is None:
        return False
    age = datetime.now(timezone.utc) - dt
    return age.total_seconds() <= ttl_seconds


def read_career_company_cache(
    company_id: str,
    *,
    expected_fingerprint: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> list[dict[str, Any]] | None:
    path = career_cache_path(company_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != CACHE_FORMAT_VERSION:
        return None
    if str(data.get("config_fingerprint") or "") != expected_fingerprint:
        return None
    if not _is_fresh(data.get("fetched_at"), ttl_seconds):
        return None
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        return None
    return [j for j in jobs if isinstance(j, dict)]


def write_career_company_cache(
    company_id: str,
    jobs: list[dict[str, Any]],
    *,
    config_fingerprint: str,
    source: str,
) -> None:
    if not jobs:
        return
    ensure_jobs_cache_dirs()
    envelope: dict[str, Any] = {
        "version": CACHE_FORMAT_VERSION,
        "company_id": company_id,
        "config_fingerprint": config_fingerprint,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "jobs": jobs,
    }
    path = career_cache_path(company_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def feed_cache_fingerprint(
    mode: str,
    serpapi_query: str,
    serpapi_location: str,
    serpapi_max_pages: int,
) -> str:
    raw = json.dumps(
        {
            "mode": mode,
            "q": serpapi_query.strip(),
            "loc": serpapi_location.strip(),
            "pages": serpapi_max_pages,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def feed_cache_path(fingerprint: str) -> Path:
    return jobs_feed_cache_dir() / f"{fingerprint}.json"


def read_jobs_feed_cache(
    fingerprint: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> tuple[list[dict[str, Any]], str] | None:
    path = feed_cache_path(fingerprint)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != CACHE_FORMAT_VERSION:
        return None
    if not _is_fresh(data.get("fetched_at"), ttl_seconds):
        return None
    if str(data.get("feed_fingerprint") or "") != fingerprint:
        return None
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        return None
    label = str(data.get("source_label") or "cached")
    out = [j for j in jobs if isinstance(j, dict)]
    return out, label


def write_jobs_feed_cache(
    fingerprint: str,
    jobs: list[dict[str, Any]],
    *,
    source_label: str,
    mode: str,
    serpapi_query: str,
    serpapi_location: str,
    serpapi_max_pages: int,
) -> None:
    if not jobs:
        return
    ensure_jobs_cache_dirs()
    envelope: dict[str, Any] = {
        "version": CACHE_FORMAT_VERSION,
        "feed_fingerprint": fingerprint,
        "mode": mode,
        "serpapi_query": serpapi_query,
        "serpapi_location": serpapi_location,
        "serpapi_max_pages": serpapi_max_pages,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_label": source_label,
        "jobs": jobs,
    }
    path = feed_cache_path(fingerprint)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def try_restore_jobs_session_from_feed_cache(
    *,
    mode: str,
    serpapi_query: str,
    serpapi_location: str,
    serpapi_max_pages: int,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> tuple[list[dict[str, Any]], str] | None:
    """If a fresh feed file exists for this fingerprint, return ``(jobs, label)``."""
    fp = feed_cache_fingerprint(mode, serpapi_query, serpapi_location, serpapi_max_pages)
    return read_jobs_feed_cache(fp, ttl_seconds=ttl_seconds)
