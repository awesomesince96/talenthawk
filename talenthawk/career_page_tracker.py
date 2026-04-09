"""Fetch job rows from company career listing pages (pluggable fetchers)."""

from __future__ import annotations

import re
from typing import Any, Callable

import httpx

from talenthawk.storage import load_career_page_mappings

JINA_READER_BASE = "https://r.jina.ai/"
# Markdown links to role detail pages on Uber's careers site.
_UBER_CAREERS_LIST_LINK = re.compile(
    r"\[([^\]]+)\]\((https://(?:www\.)?uber\.com[^)]*?/careers/list/(\d+)[^)]*)\)",
    re.IGNORECASE,
)

FetcherFn = Callable[[str, str, str, float], list[dict[str, Any]]]


def _parse_uber_jina_markdown(markdown: str, company_display: str, company_id: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for m in _UBER_CAREERS_LIST_LINK.finditer(markdown):
        title = (m.group(1) or "").strip()
        url = (m.group(2) or "").strip()
        jid = (m.group(3) or "").strip()
        if not title or not url or jid in seen:
            continue
        seen.add(jid)
        out.append(
            {
                "job_id": jid,
                "title": title,
                "company": company_display,
                "published_at": "",
                "url": url,
                "salary": "",
                "source": f"career_page:{company_id}",
                "career_company_id": company_id,
                "raw": {"link_match": m.group(0)},
            }
        )
    return out


def fetch_via_jina_markdown_uber(
    careers_list_url: str,
    company_display: str,
    company_id: str,
    timeout: float = 120.0,
) -> list[dict[str, Any]]:
    """
    Load the public careers HTML via `Jina AI Reader <https://jina.ai/reader/>`_, which returns
    rendered markdown including role titles and links (Uber's listings are heavily client-rendered).
    """
    target = careers_list_url.strip()
    if not target:
        return []
    jina_url = f"{JINA_READER_BASE}{target}"
    headers = {
        "User-Agent": "talenthawk-career-tracker/1.0",
        "Accept": "text/plain",
        "X-Return-Format": "markdown",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(jina_url, headers=headers)
        r.raise_for_status()
    text = r.text or ""
    return _parse_uber_jina_markdown(text, company_display, company_id)


FETCHERS: dict[str, FetcherFn] = {
    "jina_markdown_uber": fetch_via_jina_markdown_uber,
}


def fetch_jobs_for_company(
    company_id: str,
    *,
    mappings: dict[str, Any] | None = None,
    timeout: float = 120.0,
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
    timeout: float = 120.0,
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
                errors.append(f"{c}: no roles parsed (site layout change, timeout, or Jina reader empty)")
            merged.extend(batch)
        except Exception as e:
            errors.append(f"{c}: {e}")
    return merged, errors
