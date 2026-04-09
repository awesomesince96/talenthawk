"""Fetch job rows from company career listing pages (pluggable fetchers)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import httpx

from talenthawk.storage import load_career_page_mappings

UBER_SEARCH_API_URL = "https://www.uber.com/api/loadSearchJobsResults?localeCode=en"

FetcherFn = Callable[[str, str, str, float], list[dict[str, Any]]]

TARGET_UBER_USA_JOBS = 50
UBER_PAGE_SIZE = 50
UBER_COUNTRY_USA = "USA"


def _departments_from_careers_url(careers_list_url: str) -> list[str]:
    """Reads ``department`` query params from the careers list URL (e.g. ``Engineering``)."""
    q = parse_qs(urlparse(careers_list_url.strip()).query)
    raw = q.get("department") or []
    out = [x.strip() for x in raw if x and str(x).strip()]
    return out if out else ["Engineering"]


def _uber_location_short(loc: object) -> str:
    if not isinstance(loc, dict):
        return ""
    city = str(loc.get("city") or "").strip()
    region = str(loc.get("region") or "").strip()
    country = str(loc.get("countryName") or loc.get("country") or "").strip()
    parts = [p for p in (city, region, country) if p]
    return " · ".join(parts)[:220]


def _uber_country_code(loc: object) -> str:
    if not isinstance(loc, dict):
        return ""
    return str(loc.get("country") or "").strip()


def _uber_is_usa_job(j: dict[str, Any]) -> bool:
    """True if the primary ``location`` is USA (Uber API uses ``country: \"USA\"``)."""
    loc = j.get("location")
    if isinstance(loc, dict) and _uber_country_code(loc) == UBER_COUNTRY_USA:
        return True
    return False


def _parse_uber_iso_dt(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _normalize_uber_api_job(
    j: dict[str, Any],
    *,
    company_display: str,
    company_id: str,
) -> dict[str, Any]:
    jid = j.get("id")
    job_id = str(int(jid)) if jid is not None else ""
    created = j.get("creationDate") or ""
    updated = j.get("updatedDate") or ""
    loc = _uber_location_short(j.get("location"))
    return {
        "job_id": job_id,
        "title": str(j.get("title") or "").strip(),
        "company": company_display,
        "published_at": str(created) if created else "",
        "updated_at": str(updated) if updated else "",
        "url": f"https://www.uber.com/careers/list/{job_id}",
        "salary": loc,
        "source": f"career_page:{company_id}",
        "career_company_id": company_id,
        "raw": j,
    }


def fetch_via_uber_search_api(
    careers_list_url: str,
    company_display: str,
    company_id: str,
    timeout: float = 90.0,
) -> list[dict[str, Any]]:
    """
    Uber’s ``loadSearchJobsResults`` API. Paginates until we have enough **USA** rows to return
    :data:`TARGET_UBER_USA_JOBS` after filtering, or the API is exhausted. Results are sorted by
    **creation date** (newest first), capped at 50.
    """
    ref = careers_list_url.strip() or "https://www.uber.com/us/en/careers/list/"
    depts = _departments_from_careers_url(careers_list_url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.uber.com",
        "Referer": ref,
        "x-csrf-token": "x",
    }
    raw_accum: list[dict[str, Any]] = []
    page = 1
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        while page <= 80:
            body: dict[str, Any] = {
                "limit": UBER_PAGE_SIZE,
                "page": page,
                "params": {"department": depts},
            }
            r = client.post(UBER_SEARCH_API_URL, json=body, headers=headers)
            r.raise_for_status()
            payload = r.json()
            if payload.get("status") != "success":
                raise RuntimeError(str(payload)[:500])
            data = payload.get("data")
            if not isinstance(data, dict):
                break
            batch = data.get("results")
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                if isinstance(item, dict):
                    raw_accum.append(item)
            usa_n = sum(1 for j in raw_accum if _uber_is_usa_job(j))
            if usa_n >= TARGET_UBER_USA_JOBS:
                break
            if len(batch) < UBER_PAGE_SIZE:
                break
            page += 1

    usa_only = [j for j in raw_accum if _uber_is_usa_job(j)]
    min_dt = datetime.min.replace(tzinfo=timezone.utc)

    def _created_sort_key(row: dict[str, Any]) -> datetime:
        return _parse_uber_iso_dt(row.get("creationDate")) or min_dt

    usa_only.sort(key=_created_sort_key, reverse=True)
    picked = usa_only[:TARGET_UBER_USA_JOBS]
    return [_normalize_uber_api_job(j, company_display=company_display, company_id=company_id) for j in picked]


FETCHERS: dict[str, FetcherFn] = {
    "uber_search_api": fetch_via_uber_search_api,
    # Older mappings used the Jina-based fetcher name; resolve to the official API.
    "jina_markdown_uber": fetch_via_uber_search_api,
}


def fetch_jobs_for_company(
    company_id: str,
    *,
    mappings: dict[str, Any] | None = None,
    timeout: float = 90.0,
) -> list[dict[str, Any]]:
    """Return normalized job dicts for one mapped company, or [] if unknown/fetcher missing."""
    data = mappings if mappings is not None else load_career_page_mappings()
    companies = data.get("companies") if isinstance(data, dict) else None
    if not isinstance(companies, list):
        return []
    entry: dict[str, Any] | None = None
    for c in companies:
        if isinstance(c, dict) and str(c.get("id", "")).strip() == company_id:
            entry = c
            break
    if not entry:
        return []
    fetcher = str(entry.get("fetcher") or "").strip()
    url = str(entry.get("careers_list_url") or "").strip()
    display = str(entry.get("display_name") or entry.get("id") or company_id).strip()
    fn = FETCHERS.get(fetcher)
    if not fn or not url:
        return []
    return fn(url, display, company_id, timeout)


def fetch_tracked_career_jobs(
    company_ids: list[str],
    *,
    timeout: float = 90.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Fetch and merge jobs for each company id. Returns ``(jobs, errors)`` where ``errors`` are
    human-readable strings per failed company.
    """
    mappings = load_career_page_mappings()
    merged: list[dict[str, Any]] = []
    errors: list[str] = []
    valid_ids = {str(c.get("id", "")).strip() for c in mappings.get("companies", []) if isinstance(c, dict)}
    for cid in company_ids:
        c = str(cid).strip()
        if not c:
            continue
        if c not in valid_ids:
            errors.append(f"{c}: not in career_page_mappings.json")
            continue
        try:
            batch = fetch_jobs_for_company(c, mappings=mappings, timeout=timeout)
            if not batch:
                errors.append(f"{c}: no roles returned (API change or empty results)")
            merged.extend(batch)
        except Exception as e:
            errors.append(f"{c}: {e}")
    return merged, errors
