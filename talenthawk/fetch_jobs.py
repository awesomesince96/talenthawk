"""Fetch remote jobs and normalize to a common schema."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from talenthawk.settings import REMOTE_JOBS_URL


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                chunk = s[:19] if "T" in s and fmt != "%Y-%m-%d" else s[:10]
                dt = datetime.strptime(chunk, fmt)
            except ValueError:
                dt = None
            if dt is not None:
                return dt.replace(tzinfo=timezone.utc)
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fetch_remotive_jobs(timeout: float = 30.0) -> list[dict[str, Any]]:
    with httpx.Client(timeout=timeout) as client:
        r = client.get(REMOTE_JOBS_URL)
        r.raise_for_status()
        payload = r.json()
    jobs_raw = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs_raw, list):
        return []
    out: list[dict[str, Any]] = []
    for j in jobs_raw:
        if not isinstance(j, dict):
            continue
        title = (j.get("title") or "").strip()
        company = (j.get("company_name") or j.get("company") or "").strip()
        pub = j.get("publication_date") or j.get("created_at")
        url = j.get("url") or j.get("apply_url") or ""
        salary = (j.get("salary") or "").strip()
        jid = j.get("id")
        job_id = str(jid).strip() if jid is not None and str(jid).strip() else ""
        out.append(
            {
                "job_id": job_id,
                "title": title,
                "company": company,
                "published_at": str(pub) if pub else "",
                "url": str(url) if url else "",
                "salary": salary,
                "source": "remotive",
                "raw": j,
            }
        )
    return out


def filter_last_n_days(jobs: list[dict[str, Any]], days: int = 30) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept: list[dict[str, Any]] = []
    for job in jobs:
        dt = _parse_date(job.get("published_at"))
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= cutoff:
            kept.append(job)
    return kept


def matches_text_filter(value: str, patterns: list[str]) -> bool:
    """True if ``value`` matches any pattern (case-insensitive): exact, substring either way."""
    c = value.lower().strip()
    if not c:
        return False
    for b in patterns:
        bl = b.lower().strip()
        if not bl:
            continue
        if bl == c or bl in c or c in bl:
            return True
    return False


def company_is_blocked(company: str, blocklist: list[str]) -> bool:
    """Backward-compatible alias for :func:`matches_text_filter`."""
    return matches_text_filter(company, blocklist)
