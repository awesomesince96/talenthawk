"""Extract compensation hints from free-text job descriptions (HTML or plain)."""

from __future__ import annotations

import re
from html import unescape
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# e.g. "base salary range ... $70,400.00 - 113,700.00 USD annually"
_RANGE_LONG = re.compile(
    r"(?:base\s+)?(?:salary|compensation|pay)(?:\s+range)?\s*[:\-]?\s*"
    r"((?:USD\s*)?\$?\s*[\d,.]+(?:\s*[-–—]\s*|\s+to\s+)\s*(?:USD\s*)?\$?\s*[\d,.]+"
    r"(?:\s*(?:USD|EUR|GBP))?(?:\s*(?:annually|per\s*year|\/yr|a\s+year|yearly))?)",
    re.IGNORECASE,
)
# $120k - $180k USD
_RANGE_K = re.compile(
    r"(\$?\s*\d{2,3}(?:\.\d+)?\s*k\s*[-–—]\s*\$?\s*\d{2,3}(?:\.\d+)?\s*k)(?:\s*(?:USD|EUR|GBP|base))?",
    re.IGNORECASE,
)
# $150,000 - $200,000
_RANGE_COMMA = re.compile(
    r"(\$?\s*\d{1,3}(?:,\d{3})+(?:\.\d{2})?\s*[-–—]\s*\$?\s*\d{1,3}(?:,\d{3})+(?:\.\d{2})?)"
    r"(?:\s*(?:USD|EUR|GBP))?(?:\s*(?:annually|per\s*year|\/yr))?",
    re.IGNORECASE,
)
# Fallback: two money tokens with dash (greedy but short)
_RANGE_FALLBACK = re.compile(
    r"(\$?\s*[\d,.]+\s*[-–—]\s*\$?\s*[\d,.]+)(?:\s*(?:USD|EUR|GBP|annually|per\s*year|\/yr))?",
    re.IGNORECASE,
)
_HOURLY = re.compile(
    r"(\$?\s*\d{1,4}(?:\.\d{1,2})?\s*/\s*(?:hr|hour|h)(?:\s*USD)?)",
    re.IGNORECASE,
)


def _prepare_text(text: str) -> str:
    t = unescape(text or "")
    t = _TAG_RE.sub(" ", t)
    t = t.replace("<br/>", " ").replace("<br>", " ")
    t = _WS.sub(" ", t).strip()
    return t[:14000]


def _clean_snippet(s: str, max_len: int) -> str:
    s = _WS.sub(" ", (s or "").strip())
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def extract_salary_from_text(text: str, *, max_len: int = 48) -> str:
    """
    Return a short compensation string if a common pattern appears in posting text.
    Empty string if nothing reliable is found.
    """
    t = _prepare_text(text)
    if not t:
        return ""

    for rx in (_RANGE_LONG, _RANGE_COMMA, _RANGE_K, _RANGE_FALLBACK):
        m = rx.search(t)
        if m:
            got = (m.group(1) if m.lastindex else m.group(0)).strip()
            if len(got) >= 6:
                return _clean_snippet(got, max_len)

    m = _HOURLY.search(t)
    if m:
        return _clean_snippet(m.group(1).strip(), max_len)

    return ""


def gather_job_description_text(job: dict[str, Any]) -> str:
    """Collect plain/HTML description blobs from a normalized job row and optional ``raw`` payload."""
    parts: list[str] = []
    for key in ("description",):
        v = job.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v)

    raw = job.get("raw")
    if isinstance(raw, dict):
        for key in (
            "description",
            "description_html",
            "job_description",
            "preferred_qualifications",
            "basic_qualifications",
        ):
            v = raw.get(key)
            if isinstance(v, str) and v.strip():
                parts.append(v)
    return "\n".join(parts)


def salary_display_for_api_job(job: dict[str, Any]) -> str:
    """Prefer explicit ``salary`` from the feed; otherwise parse from description text."""
    explicit = str(job.get("salary") or "").strip()
    if explicit:
        return explicit
    blob = gather_job_description_text(job)
    return extract_salary_from_text(blob)


def salary_display_for_career_row(row: dict[str, Any]) -> str:
    """Prefer ``compensation`` / ``pay``; otherwise parse from ``raw`` description fields."""
    for key in ("compensation", "pay"):
        v = str(row.get(key) or "").strip()
        if v:
            return v
    raw = row.get("raw")
    blob = ""
    if isinstance(raw, dict):
        chunks: list[str] = []
        for key in (
            "description",
            "description_html",
            "preferred_qualifications",
            "basic_qualifications",
        ):
            v = raw.get(key)
            if isinstance(v, str) and v.strip():
                chunks.append(v)
        blob = "\n".join(chunks)
    return extract_salary_from_text(blob)
