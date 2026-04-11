"""Fetch job rows from company career listing pages (pluggable fetchers)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import httpx

from talenthawk.fetch_jobs import fetch_serpapi_google_jobs
from talenthawk.job_cache import (
    DEFAULT_TTL_SECONDS,
    career_entry_fingerprint,
    read_career_company_cache,
    write_career_company_cache,
)
from talenthawk.storage import load_career_page_mappings

UBER_SEARCH_API_URL = "https://www.uber.com/api/loadSearchJobsResults?localeCode=en"
NETFLIX_EIGHTFOLD_JOBS_URL = "https://netflix.eightfold.ai/api/apply/v2/jobs"
MICROSOFT_PCSX_SEARCH_URL = "https://apply.careers.microsoft.com/api/pcsx/search"
MICROSOFT_JOB_BASE_URL = "https://apply.careers.microsoft.com"
AMAZON_JOBS_SEARCH_URL = "https://www.amazon.jobs/en/search"

FetcherFn = Callable[[dict[str, Any], str, str, float], list[dict[str, Any]]]

TARGET_USA_JOBS = 50
UBER_PAGE_SIZE = 50
UBER_COUNTRY_USA = "USA"
NETFLIX_PAGE_SIZE = 10
MICROSOFT_PAGE_SIZE = 10


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


def _normalized_created_sort_key(job: dict[str, Any]) -> datetime:
    """Parse ``published_at`` for ordering merged career rows (newest first)."""
    min_dt = datetime.min.replace(tzinfo=timezone.utc)
    return _parse_uber_iso_dt(job.get("published_at")) or min_dt


def sort_career_jobs_by_created_desc(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy sorted by ``published_at`` descending (latest first)."""
    out = list(jobs)
    out.sort(key=_normalized_created_sort_key, reverse=True)
    return out


def _unix_ts_to_iso(ts: object) -> str:
    if ts is None:
        return ""
    try:
        sec = int(float(ts))
    except (TypeError, ValueError):
        return ""
    if sec <= 0:
        return ""
    dt = datetime.fromtimestamp(sec, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _unix_ts_to_dt(ts: object) -> datetime | None:
    if ts is None:
        return None
    try:
        sec = int(float(ts))
    except (TypeError, ValueError):
        return None
    if sec <= 0:
        return None
    return datetime.fromtimestamp(sec, tz=timezone.utc)


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
    entry: dict[str, Any],
    company_display: str,
    company_id: str,
    timeout: float = 90.0,
) -> list[dict[str, Any]]:
    """
    Uber’s ``loadSearchJobsResults`` API. Paginates until we have enough **USA** rows to return
    :data:`TARGET_USA_JOBS` after filtering, or the API is exhausted. Results are sorted by
    **creation date** (newest first), capped at 50.
    """
    careers_list_url = str(entry.get("careers_list_url") or "").strip()
    ref = careers_list_url or "https://www.uber.com/us/en/careers/list/"
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
            if usa_n >= TARGET_USA_JOBS:
                break
            if len(batch) < UBER_PAGE_SIZE:
                break
            page += 1

    usa_only = [j for j in raw_accum if _uber_is_usa_job(j)]
    min_dt = datetime.min.replace(tzinfo=timezone.utc)

    def _created_sort_key(row: dict[str, Any]) -> datetime:
        return _parse_uber_iso_dt(row.get("creationDate")) or min_dt

    usa_only.sort(key=_created_sort_key, reverse=True)
    picked = usa_only[:TARGET_USA_JOBS]
    return [_normalize_uber_api_job(j, company_display=company_display, company_id=company_id) for j in picked]


def _netflix_is_usa(p: dict[str, Any]) -> bool:
    loc = str(p.get("location") or "")
    if "United States" in loc or loc.strip().upper().startswith("USA"):
        return True
    locs = p.get("locations")
    if isinstance(locs, list):
        for x in locs:
            if isinstance(x, str) and ("United States" in x or x.strip().upper().startswith("USA")):
                return True
    return False


def _netflix_location_short(p: dict[str, Any]) -> str:
    loc = str(p.get("location") or "").strip()
    if loc:
        return loc[:220]
    locs = p.get("locations")
    if isinstance(locs, list):
        parts = [str(x).strip() for x in locs[:4] if x and str(x).strip()]
        return " · ".join(parts)[:220]
    return ""


def _normalize_netflix_job(
    p: dict[str, Any],
    *,
    company_display: str,
    company_id: str,
) -> dict[str, Any]:
    jid = p.get("id")
    job_id = str(jid) if jid is not None else ""
    url = str(p.get("canonicalPositionUrl") or "").strip()
    return {
        "job_id": job_id,
        "title": str(p.get("name") or "").strip(),
        "company": company_display,
        "published_at": _unix_ts_to_iso(p.get("t_create")),
        "updated_at": _unix_ts_to_iso(p.get("t_update")),
        "url": url,
        "salary": _netflix_location_short(p),
        "source": f"career_page:{company_id}",
        "career_company_id": company_id,
        "raw": p,
    }


def fetch_via_eightfold_netflix(
    entry: dict[str, Any],
    company_display: str,
    company_id: str,
    timeout: float = 90.0,
) -> list[dict[str, Any]]:
    """
    Netflix Eightfold ``apply/v2/jobs``. Paginates with optional ``location`` filter; keeps **USA**
    rows, sorts by **t_create** (newest first), capped at :data:`TARGET_USA_JOBS`.
    """
    loc_filter = str(entry.get("eightfold_location") or "United States").strip()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    raw_accum: list[dict[str, Any]] = []
    total: int | None = None
    start = 0
    max_pages = 120
    page_i = 0
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        while page_i < max_pages:
            params: dict[str, Any] = {
                "domain": "netflix.com",
                "hl": "en",
                "start": start,
            }
            if loc_filter:
                params["location"] = loc_filter
            r = client.get(NETFLIX_EIGHTFOLD_JOBS_URL, params=params, headers=headers)
            r.raise_for_status()
            payload = r.json()
            if total is None and isinstance(payload.get("count"), int):
                total = int(payload["count"])
            batch = payload.get("positions")
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                if isinstance(item, dict):
                    raw_accum.append(item)
            usa_n = sum(1 for j in raw_accum if _netflix_is_usa(j))
            if usa_n >= TARGET_USA_JOBS:
                break
            if len(batch) < NETFLIX_PAGE_SIZE:
                break
            if total is not None and start + len(batch) >= total:
                break
            start += NETFLIX_PAGE_SIZE
            page_i += 1

    usa_only = [j for j in raw_accum if _netflix_is_usa(j)]
    min_dt = datetime.min.replace(tzinfo=timezone.utc)

    def _created_sort_key(row: dict[str, Any]) -> datetime:
        return _unix_ts_to_dt(row.get("t_create")) or min_dt

    usa_only.sort(key=_created_sort_key, reverse=True)
    picked = usa_only[:TARGET_USA_JOBS]
    return [_normalize_netflix_job(p, company_display=company_display, company_id=company_id) for p in picked]


def _microsoft_is_usa(p: dict[str, Any]) -> bool:
    std = p.get("standardizedLocations")
    if isinstance(std, list):
        for x in std:
            if isinstance(x, str) and (x == "US" or x.endswith(", US") or ", US" in x):
                return True
    locs = p.get("locations")
    if isinstance(locs, list):
        for lo in locs:
            if isinstance(lo, str) and "United States" in lo:
                return True
    return False


def _microsoft_location_short(p: dict[str, Any]) -> str:
    locs = p.get("locations")
    if isinstance(locs, list) and locs:
        parts = [str(x).strip() for x in locs[:3] if x and str(x).strip()]
        return " · ".join(parts)[:220]
    return ""


def _normalize_microsoft_job(
    p: dict[str, Any],
    *,
    company_display: str,
    company_id: str,
) -> dict[str, Any]:
    jid = p.get("id")
    job_id = str(jid) if jid is not None else ""
    rel = str(p.get("positionUrl") or "").strip()
    url = f"{MICROSOFT_JOB_BASE_URL}{rel}" if rel.startswith("/") else rel
    return {
        "job_id": job_id,
        "title": str(p.get("name") or "").strip(),
        "company": company_display,
        "published_at": _unix_ts_to_iso(p.get("creationTs")),
        "updated_at": _unix_ts_to_iso(p.get("postedTs")),
        "url": url,
        "salary": _microsoft_location_short(p),
        "source": f"career_page:{company_id}",
        "career_company_id": company_id,
        "raw": p,
    }


def fetch_via_pcsx_microsoft(
    entry: dict[str, Any],
    company_display: str,
    company_id: str,
    timeout: float = 90.0,
) -> list[dict[str, Any]]:
    """
    Microsoft PCSX search on ``apply.careers.microsoft.com``. Paginates with ``location=United States``;
    keeps USA rows, sorts by **creationTs** (newest first), capped at :data:`TARGET_USA_JOBS`.
    """
    q = str(entry.get("pcsx_query") or "").strip()
    loc_filter = str(entry.get("pcsx_location") or "United States").strip()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    raw_accum: list[dict[str, Any]] = []
    start = 0
    max_pages = 200
    page_i = 0
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        while page_i < max_pages:
            params: dict[str, Any] = {
                "domain": "microsoft.com",
                "query": q,
                "start": start,
                "hl": "en",
            }
            if loc_filter:
                params["location"] = loc_filter
            r = client.get(MICROSOFT_PCSX_SEARCH_URL, params=params, headers=headers)
            r.raise_for_status()
            payload = r.json()
            data = payload.get("data")
            if not isinstance(data, dict):
                break
            batch = data.get("positions")
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                if isinstance(item, dict):
                    raw_accum.append(item)
            usa_n = sum(1 for j in raw_accum if _microsoft_is_usa(j))
            if usa_n >= TARGET_USA_JOBS:
                break
            if len(batch) < MICROSOFT_PAGE_SIZE:
                break
            start += MICROSOFT_PAGE_SIZE
            page_i += 1

    usa_only = [j for j in raw_accum if _microsoft_is_usa(j)]
    min_dt = datetime.min.replace(tzinfo=timezone.utc)

    def _created_sort_key(row: dict[str, Any]) -> datetime:
        return _unix_ts_to_dt(row.get("creationTs")) or min_dt

    usa_only.sort(key=_created_sort_key, reverse=True)
    picked = usa_only[:TARGET_USA_JOBS]
    return [_normalize_microsoft_job(p, company_display=company_display, company_id=company_id) for p in picked]


def _parse_amazon_posted_date(s: str) -> str:
    """Parse strings like ``April 11, 2026`` from Amazon search JSON."""
    t = (s or "").strip()
    if not t:
        return ""
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(t, fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return ""


def _normalize_amazon_job(
    j: dict[str, Any],
    *,
    company_display: str,
    company_id: str,
) -> dict[str, Any]:
    job_path = str(j.get("job_path") or "").strip()
    job_id = str(j.get("id_icims") or j.get("id") or "").strip()
    title = str(j.get("title") or "").strip()
    loc = str(j.get("normalized_location") or j.get("location") or "").strip()
    if job_path.startswith("/"):
        url = f"https://www.amazon.jobs{job_path}"
    elif job_path.startswith("http"):
        url = job_path
    else:
        url = ""
    posted = _parse_amazon_posted_date(str(j.get("posted_date") or ""))
    upd = str(j.get("updated_time") or "").strip()
    return {
        "job_id": job_id,
        "title": title,
        "company": company_display,
        "published_at": posted,
        "updated_at": upd,
        "url": url,
        "salary": loc,
        "source": f"career_page:{company_id}",
        "career_company_id": company_id,
        "raw": j,
    }


def fetch_via_amazon_jobs(
    entry: dict[str, Any],
    company_display: str,
    company_id: str,
    timeout: float = 90.0,
) -> list[dict[str, Any]]:
    """Public ``amazon.jobs`` JSON search (USA); no API key."""
    loc_filter = str(entry.get("amazon_location") or "United States").strip() or "United States"
    page_size = 10
    picked: list[dict[str, Any]] = []
    offset = 0
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        while len(picked) < TARGET_USA_JOBS and offset < 8000:
            params: dict[str, str] = {
                "offset": str(offset),
                "result_limit": str(page_size),
                "sort": "recent",
                "base_query": "",
                "loc_query": loc_filter,
            }
            r = client.get(AMAZON_JOBS_SEARCH_URL, params=params, headers=headers)
            r.raise_for_status()
            payload = r.json()
            jobs = payload.get("jobs") if isinstance(payload, dict) else None
            if not isinstance(jobs, list) or not jobs:
                break
            for j in jobs:
                if not isinstance(j, dict):
                    continue
                cc = str(j.get("country_code") or "").strip().upper()
                if cc not in ("USA", "US"):
                    continue
                picked.append(_normalize_amazon_job(j, company_display=company_display, company_id=company_id))
                if len(picked) >= TARGET_USA_JOBS:
                    break
            offset += page_size
            if len(jobs) < page_size:
                break
    return picked


def _serpapi_key_resolved() -> str:
    """Same sources as the Streamlit app: env vars, then ``st.secrets`` when running inside Streamlit."""
    for k in ("SERPAPI_API_KEY", "SERPAPI_KEY"):
        v = os.environ.get(k, "").strip()
        if v:
            return v
    try:
        import streamlit as st

        sec = st.secrets.get("SERPAPI_API_KEY", "")
        if sec and str(sec).strip():
            return str(sec).strip()
    except (FileNotFoundError, KeyError, AttributeError, RuntimeError, ImportError, ModuleNotFoundError):
        pass
    return ""


def _split_serpapi_needles(value: object) -> list[str]:
    """Comma-separated substrings, lowercased (e.g. ``meta, facebook``)."""
    if value is None:
        return []
    return [x.strip().lower() for x in str(value).split(",") if x.strip()]


def _serpapi_url_haystack(j: dict[str, Any]) -> str:
    """All apply links + share link — the first option is often Indeed/LinkedIn, not the employer site."""
    parts: list[str] = [str(j.get("url") or "")]
    raw = j.get("raw")
    if isinstance(raw, dict):
        opts = raw.get("apply_options")
        if isinstance(opts, list):
            for o in opts:
                if isinstance(o, dict):
                    parts.append(str(o.get("link") or ""))
        parts.append(str(raw.get("share_link") or ""))
    return " ".join(parts).lower()


def _serpapi_company_blob(j: dict[str, Any]) -> str:
    """Employer name as shown on the card (often correct even when apply URL is a third party)."""
    parts: list[str] = [str(j.get("company") or "")]
    raw = j.get("raw")
    if isinstance(raw, dict):
        parts.append(str(raw.get("company_name") or ""))
        parts.append(str(raw.get("via") or ""))
    return " ".join(parts).lower()


def _serpapi_row_matches_filters(entry: dict[str, Any], j: dict[str, Any]) -> bool:
    """
    Keep a row if URL needles hit **any** apply link, and/or company needles hit employer fields
    (``company_name`` often matches even when the first apply link is Indeed/LinkedIn).
    If both needle lists are set, either match wins (OR).
    """
    url_needles = _split_serpapi_needles(entry.get("serpapi_url_substring"))
    comp_needles = _split_serpapi_needles(entry.get("serpapi_company_substring"))
    if not url_needles and not comp_needles:
        return True
    url_hay = _serpapi_url_haystack(j)
    comp_blob = _serpapi_company_blob(j)
    ok_url = any(n in url_hay for n in url_needles)
    ok_comp = any(n in comp_blob for n in comp_needles)
    if url_needles and comp_needles:
        return ok_url or ok_comp
    if url_needles:
        return ok_url
    return ok_comp


def _pick_serpapi_apply_url(j: dict[str, Any], entry: dict[str, Any]) -> str:
    """Prefer a careers-site link over the first aggregator apply option."""
    raw = j.get("raw")
    if not isinstance(raw, dict):
        return str(j.get("url") or "").strip()
    candidates: list[str] = []
    opts = raw.get("apply_options")
    if isinstance(opts, list):
        for o in opts:
            if isinstance(o, dict):
                link = str(o.get("link") or "").strip()
                if link:
                    candidates.append(link)
    share = str(raw.get("share_link") or "").strip()
    if share:
        candidates.append(share)
    hints = _split_serpapi_needles(entry.get("serpapi_url_substring")) + _split_serpapi_needles(
        entry.get("serpapi_company_substring")
    )
    for c in candidates:
        cl = c.lower()
        if any(h and len(h) > 2 and h in cl for h in hints):
            return c
    for c in candidates:
        cl = c.lower()
        if any(
            x in cl
            for x in (
                "metacareers.com",
                "facebook.com/careers",
                "careers.google",
                "google.com/about/careers",
            )
        ):
            return c
    return str(j.get("url") or "").strip() or (candidates[0] if candidates else "")


def fetch_via_serpapi_careers(
    entry: dict[str, Any],
    company_display: str,
    company_id: str,
    timeout: float = 90.0,
) -> list[dict[str, Any]]:
    """
    Google Jobs (SerpAPI) with URL/company filters so rows map to one employer’s site
    (e.g. ``careers.google`` / ``metacareers.com``). Requires ``SERPAPI_API_KEY``.
    """
    key = _serpapi_key_resolved()
    if not key:
        raise RuntimeError(
            "Set SERPAPI_API_KEY in the environment (same key as **Jobs API** → SerpAPI) "
            "to load this company."
        )
    q = str(entry.get("serpapi_query") or "software engineer").strip() or "software engineer"
    loc = str(entry.get("serpapi_location") or "").strip() or None
    pages = int(entry.get("serpapi_max_pages") or 3)
    pages = max(1, min(5, pages))
    chips = str(entry.get("serpapi_chips") or "").strip() or None
    raw_jobs = fetch_serpapi_google_jobs(
        key,
        q,
        location=loc,
        max_pages=pages,
        timeout=timeout,
        chips=chips,
    )
    out: list[dict[str, Any]] = []
    for j in raw_jobs:
        if not isinstance(j, dict):
            continue
        if not _serpapi_row_matches_filters(entry, j):
            continue
        serp = j.get("raw")
        apply_url = _pick_serpapi_apply_url(j, entry)
        row = {
            "job_id": str(j.get("job_id") or "").strip(),
            "title": str(j.get("title") or "").strip(),
            "company": company_display,
            "published_at": str(j.get("published_at") or "").strip(),
            "updated_at": "",
            "url": apply_url,
            "salary": str(j.get("salary") or "").strip(),
            "source": f"career_page:{company_id}",
            "career_company_id": company_id,
            "raw": serp if isinstance(serp, dict) else j,
        }
        out.append(row)
        if len(out) >= TARGET_USA_JOBS:
            break
    return out


FETCHERS: dict[str, FetcherFn] = {
    "uber_search_api": fetch_via_uber_search_api,
    # Older mappings used the Jina-based fetcher name; resolve to the official API.
    "jina_markdown_uber": fetch_via_uber_search_api,
    "eightfold_netflix": fetch_via_eightfold_netflix,
    "pcsx_microsoft": fetch_via_pcsx_microsoft,
    "amazon_jobs": fetch_via_amazon_jobs,
    "serpapi_careers": fetch_via_serpapi_careers,
}


def mapping_entry_for_company(
    company_id: str,
    *,
    mappings: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Single company block from ``career_page_mappings.json``."""
    data = mappings if mappings is not None else load_career_page_mappings()
    companies = data.get("companies") if isinstance(data, dict) else None
    if not isinstance(companies, list):
        return None
    cid = str(company_id).strip()
    for c in companies:
        if isinstance(c, dict) and str(c.get("id", "")).strip() == cid:
            return c
    return None


def fetch_jobs_for_company(
    company_id: str,
    *,
    mappings: dict[str, Any] | None = None,
    timeout: float = 90.0,
) -> list[dict[str, Any]]:
    """Return normalized job dicts for one mapped company, or [] if unknown/fetcher missing."""
    entry = mapping_entry_for_company(company_id, mappings=mappings)
    if not entry:
        return []
    fetcher = str(entry.get("fetcher") or "").strip()
    url = str(entry.get("careers_list_url") or "").strip()
    display = str(entry.get("display_name") or entry.get("id") or company_id).strip()
    fn = FETCHERS.get(fetcher)
    if not fn or not url:
        return []
    return fn(entry, display, company_id, timeout)


def fetch_tracked_career_jobs(
    company_ids: list[str],
    *,
    timeout: float = 90.0,
    force_refresh: bool = False,
    use_cache: bool = True,
    allow_network: bool = True,
    cache_ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """
    Fetch and merge jobs for each company id.

    With ``use_cache`` and not ``force_refresh``, loads per-company files under
    ``data/jobs/career/`` when fresh (TTL) and mapping fingerprint matches.

    ``allow_network=False`` skips HTTP when the cache misses (for silent session restore).

    Returns ``(jobs, errors, cache_notes)`` where ``cache_notes`` are short lines like
    ``uber (cache)`` or ``google (fetch)``.
    """
    mappings = load_career_page_mappings()
    merged: list[dict[str, Any]] = []
    errors: list[str] = []
    notes: list[str] = []
    valid_ids = {str(c.get("id", "")).strip() for c in mappings.get("companies", []) if isinstance(c, dict)}
    for cid in company_ids:
        c = str(cid).strip()
        if not c:
            continue
        if c not in valid_ids:
            errors.append(f"{c}: not in career_page_mappings.json")
            continue
        entry = mapping_entry_for_company(c, mappings=mappings)
        if not entry:
            errors.append(f"{c}: not in career_page_mappings.json")
            continue
        fp = career_entry_fingerprint(entry)
        label = str(entry.get("display_name") or c).strip() or c

        if use_cache and not force_refresh:
            cached = read_career_company_cache(c, expected_fingerprint=fp, ttl_seconds=cache_ttl_seconds)
            if cached is not None:
                merged.extend(cached)
                notes.append(f"{label} (cache)")
                continue

        if not allow_network:
            continue

        try:
            batch = fetch_jobs_for_company(c, mappings=mappings, timeout=timeout)
            if not batch:
                errors.append(f"{c}: no roles returned (API change or empty results)")
            else:
                merged.extend(batch)
                write_career_company_cache(
                    c,
                    batch,
                    config_fingerprint=fp,
                    source=str(batch[0].get("source") or "career_page") if batch else "career_page",
                )
                notes.append(f"{label} (fetch)")
        except Exception as e:
            errors.append(f"{c}: {e}")
    return sort_career_jobs_by_created_desc(merged), errors, notes
