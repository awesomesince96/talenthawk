"""Fetch remote jobs and normalize to a common schema."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from talenthawk.settings import REMOTE_JOBS_URL, SERPAPI_SEARCH_URL

_RELATIVE_AGO = re.compile(
    r"(\d+)\s*(day|days|hour|hours|week|weeks|month|months)\s+ago",
    re.IGNORECASE,
)


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


def _parse_relative_posted_at(text: str | None) -> datetime | None:
    """Parse strings like '25 days ago' from Google Jobs / SerpAPI."""
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    low = s.lower()
    if "today" in low or "just posted" in low or low == "new":
        return datetime.now(timezone.utc)
    m = _RELATIVE_AGO.search(s)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    now = datetime.now(timezone.utc)
    if unit.startswith("hour"):
        return now - timedelta(hours=n)
    if unit.startswith("day"):
        return now - timedelta(days=n)
    if unit.startswith("week"):
        return now - timedelta(weeks=n)
    if unit.startswith("month"):
        return now - timedelta(days=min(n * 30, 365))
    return None


def _serpapi_job_posted_at_iso(j: dict[str, Any]) -> str:
    ext = j.get("detected_extensions")
    if isinstance(ext, dict):
        posted = ext.get("posted_at")
        dt = _parse_relative_posted_at(str(posted) if posted else None)
        if dt is not None:
            return dt.isoformat()
    exts = j.get("extensions")
    if isinstance(exts, list):
        for item in exts:
            if isinstance(item, str) and "ago" in item.lower():
                dt = _parse_relative_posted_at(item)
                if dt is not None:
                    return dt.isoformat()
    return ""


def _serpapi_display_job_id(j: dict[str, Any], title: str, company: str, url: str) -> str:
    """
    SerpAPI Google Jobs often returns ``job_id`` as a long base64 JSON blob.
    Prefer the inner ``htidocid`` (short, stable) for display; else a compact hash.
    """
    raw = j.get("job_id")
    s = str(raw).strip() if raw is not None else ""

    def compact_fallback() -> str:
        h = hashlib.sha256(f"{title}\0{company}\0{url}".encode()).hexdigest()[:14]
        return f"serp:{h}"

    if not s:
        return compact_fallback()

    # Long tokens are almost always base64(JSON); extract htidocid when possible.
    if len(s) > 48:
        try:
            pad = (-len(s)) % 4
            blob = base64.b64decode(s + "=" * pad, validate=False)
            payload = json.loads(blob.decode("utf-8"))
            if isinstance(payload, dict):
                ht = payload.get("htidocid")
                if isinstance(ht, str) and ht.strip():
                    return ht.strip()
        except (binascii.Error, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        return compact_fallback()

    return s


def _normalize_serpapi_job(j: dict[str, Any]) -> dict[str, Any]:
    title = (j.get("title") or "").strip()
    company = (j.get("company_name") or "").strip()
    posted = _serpapi_job_posted_at_iso(j)
    url = ""
    opts = j.get("apply_options")
    if isinstance(opts, list) and opts:
        first = opts[0]
        if isinstance(first, dict):
            url = str(first.get("link") or "").strip()
    if not url:
        url = str(j.get("share_link") or "").strip()
    job_id = _serpapi_display_job_id(j, title, company, url)
    salary = ""
    if isinstance(j.get("extensions"), list):
        salary = " · ".join(str(x) for x in j["extensions"][:3] if isinstance(x, str))[:200]
    return {
        "job_id": job_id,
        "title": title,
        "company": company,
        "published_at": posted,
        "url": url,
        "salary": salary,
        "source": "serpapi",
        "raw": j,
    }


def fetch_serpapi_google_jobs(
    api_key: str,
    query: str,
    *,
    location: str | None = None,
    hl: str = "en",
    gl: str = "us",
    max_pages: int = 3,
    timeout: float = 60.0,
) -> list[dict[str, Any]]:
    """Google Jobs via `SerpAPI <https://serpapi.com/google-jobs-api>`_. Requires a paid SerpAPI key."""
    if not api_key or not api_key.strip():
        raise ValueError("SerpAPI api_key is empty")
    q = (query or "").strip()
    if not q:
        raise ValueError("SerpAPI search query (q) is empty")
    out: list[dict[str, Any]] = []
    token: str | None = None
    with httpx.Client(timeout=timeout) as client:
        for _ in range(max(1, max_pages)):
            params: dict[str, str] = {
                "engine": "google_jobs",
                "q": q,
                "api_key": api_key.strip(),
                "hl": hl,
                "gl": gl,
            }
            if location and location.strip():
                params["location"] = location.strip()
            if token:
                params["next_page_token"] = token
            r = client.get(SERPAPI_SEARCH_URL, params=params)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                break
            err = data.get("error")
            if err:
                raise RuntimeError(str(err))
            batch = data.get("jobs_results")
            if isinstance(batch, list):
                for item in batch:
                    if isinstance(item, dict):
                        out.append(_normalize_serpapi_job(item))
            pag = data.get("serpapi_pagination")
            token = None
            if isinstance(pag, dict):
                npt = pag.get("next_page_token")
                if isinstance(npt, str) and npt.strip():
                    token = npt.strip()
            if not token:
                break
    return out


def merge_job_feeds(*feeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe by (title, company, url prefix); preserves first occurrence."""
    seen: set[tuple[str, str, str]] = set()
    merged: list[dict[str, Any]] = []
    for feed in feeds:
        for job in feed:
            t = str(job.get("title") or "").strip().lower()
            c = str(job.get("company") or "").strip().lower()
            u = str(job.get("url") or "").strip()[:160]
            key = (t, c, u)
            if key in seen:
                continue
            if not t and not c:
                continue
            seen.add(key)
            merged.append(job)
    return merged


def fetch_jobs_feed(
    mode: str,
    *,
    serpapi_api_key: str | None = None,
    serpapi_query: str = "software engineer",
    serpapi_location: str | None = None,
    serpapi_max_pages: int = 3,
) -> tuple[list[dict[str, Any]], str]:
    """
    Load jobs for the UI.

    Returns ``(jobs, source_label)``. ``serpapi`` / ``both`` require ``SERPAPI_API_KEY``.
    """
    if mode not in ("remotive", "serpapi", "both"):
        mode = "remotive"
    if mode == "remotive":
        jobs = fetch_remotive_jobs()
        return jobs, "remotive"
    if mode == "serpapi":
        key = (serpapi_api_key or "").strip()
        if not key:
            raise ValueError("SerpAPI requires an API key (env SERPAPI_API_KEY or Streamlit secret SERPAPI_API_KEY).")
        q = (serpapi_query or "software engineer").strip() or "software engineer"
        loc = (serpapi_location or "").strip() or None
        jobs = fetch_serpapi_google_jobs(key, q, location=loc, max_pages=serpapi_max_pages)
        return jobs, "serpapi (Google Jobs)"
    if mode == "both":
        r_jobs = fetch_remotive_jobs()
        key = (serpapi_api_key or "").strip()
        if not key:
            raise ValueError("Combined fetch needs SERPAPI_API_KEY for the SerpAPI half.")
        q = (serpapi_query or "software engineer").strip() or "software engineer"
        loc = (serpapi_location or "").strip() or None
        s_jobs = fetch_serpapi_google_jobs(key, q, location=loc, max_pages=serpapi_max_pages)
        merged = merge_job_feeds(r_jobs, s_jobs)
        return merged, "remotive + serpapi"
    jobs = fetch_remotive_jobs()
    return jobs, "remotive"


def filter_last_n_days(jobs: list[dict[str, Any]], days: int = 30) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept: list[dict[str, Any]] = []
    for job in jobs:
        dt = _parse_date(job.get("published_at"))
        if dt is None:
            # Google Jobs often exposes only relative text; if we could not normalize to ISO, keep SerpAPI rows.
            if job.get("source") == "serpapi":
                kept.append(job)
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


def company_is_blocked(company: str, patterns: list[str]) -> bool:
    """Alias for :func:`matches_text_filter` (company name vs filter lines)."""
    return matches_text_filter(company, patterns)
