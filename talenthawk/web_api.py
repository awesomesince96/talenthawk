"""
FastAPI server for the React dashboard. Replaces ``streamlit_app.py``.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

load_dotenv()

from talenthawk.career_page_tracker import fetch_tracked_career_jobs, sort_career_jobs_by_created_desc
from talenthawk.fetch_jobs import fetch_jobs_feed, matches_text_filter, parse_title_ignore_words_input
from talenthawk.job_cache import (
    DEFAULT_TTL_SECONDS,
    ensure_jobs_cache_dirs,
    feed_cache_fingerprint,
    try_restore_jobs_session_from_feed_cache,
    write_jobs_feed_cache,
)
from talenthawk.storage import (
    load_career_page_mappings,
    load_career_tracker_filter,
    load_category_filters,
    load_company_filters,
    load_serpapi_prefs,
    load_title_filters,
    load_title_ignore_words,
    persistence_paths,
    save_career_tracker_filter,
    save_category_filters,
    save_company_filters,
    save_serpapi_prefs,
    save_title_filters,
    save_title_ignore_words,
)
from talenthawk.viz_core import (
    ChartIncludes,
    RECENCY_DAY_CHOICES,
    compute_career_bundle,
    compute_jobs_api_bundle,
    salary_line_for_career_row,
    truncate,
)


def _serpapi_key() -> str | None:
    for env in ("SERPAPI_API_KEY", "SERPAPI_KEY"):
        v = os.environ.get(env, "").strip()
        if v:
            return v
    return None


def ensure_persistence_defaults() -> None:
    paths = persistence_paths()
    paths["persistence_dir"].mkdir(parents=True, exist_ok=True)
    paths["mappings_dir"].mkdir(parents=True, exist_ok=True)
    ensure_jobs_cache_dirs()
    if not paths["title_filter"].exists():
        save_title_filters([])
    if not paths["company_filter"].exists():
        save_company_filters([])
    if not paths["category_filter"].exists():
        save_category_filters([])
    if not paths["title_ignore_words"].exists():
        save_title_ignore_words([])
    load_career_page_mappings()


class AppState:
    """In-memory session (single-user local app)."""

    def __init__(self) -> None:
        self.jobs_raw: list[dict[str, Any]] = []
        self.jobs_source: str | None = None
        self.jobs_error: str | None = None
        self.jobs_fetch_mode: str = "remotive"
        self.serpapi_query: str = ""
        self.serpapi_location: str = ""
        self.serpapi_pages: int = 3
        self.jobs_recency_days: int = 30
        self.career_tracker_selection: list[str] = []
        self.career_tracker_rows: list[dict[str, Any]] = []
        self.career_tracker_errs: list[str] = []
        self.career_cache_notes: list[str] = []


STATE = AppState()


def _hydrate_jobs_from_disk_cache() -> bool:
    mode = STATE.jobs_fetch_mode if STATE.jobs_fetch_mode in ("remotive", "serpapi", "both") else "remotive"
    q = STATE.serpapi_query.strip()
    loc_s = STATE.serpapi_location.strip()
    pages = max(1, min(5, int(STATE.serpapi_pages or 3)))
    got = try_restore_jobs_session_from_feed_cache(
        mode=mode,
        serpapi_query=q,
        serpapi_location=loc_s,
        serpapi_max_pages=pages,
        ttl_seconds=DEFAULT_TTL_SECONDS,
    )
    if got is None:
        return False
    jobs, label = got
    STATE.jobs_raw = jobs
    STATE.jobs_source = f"{label} (cached ≤{DEFAULT_TTL_SECONDS // 3600}h)"
    STATE.jobs_error = None
    return True


def load_jobs_into_session(*, bypass_cache: bool) -> None:
    mode = STATE.jobs_fetch_mode if STATE.jobs_fetch_mode in ("remotive", "serpapi", "both") else "remotive"
    q = STATE.serpapi_query.strip()
    loc = STATE.serpapi_location.strip() or None
    loc_s = STATE.serpapi_location.strip()
    pages = max(1, min(5, int(STATE.serpapi_pages or 3)))
    if not bypass_cache:
        got = try_restore_jobs_session_from_feed_cache(
            mode=mode,
            serpapi_query=q,
            serpapi_location=loc_s,
            serpapi_max_pages=pages,
            ttl_seconds=DEFAULT_TTL_SECONDS,
        )
        if got is not None:
            jobs, label = got
            STATE.jobs_raw = jobs
            STATE.jobs_source = f"{label} (cached ≤{DEFAULT_TTL_SECONDS // 3600}h)"
            STATE.jobs_error = None
            save_serpapi_prefs(STATE.serpapi_query, STATE.serpapi_location)
            return
    try:
        jobs, label = fetch_jobs_feed(
            mode,
            serpapi_api_key=_serpapi_key(),
            serpapi_query=q,
            serpapi_location=loc,
            serpapi_max_pages=pages,
        )
        STATE.jobs_raw = jobs
        STATE.jobs_source = label
        STATE.jobs_error = None
        fp = feed_cache_fingerprint(mode, q, loc_s, pages)
        write_jobs_feed_cache(
            fp,
            jobs,
            source_label=label,
            mode=mode,
            serpapi_query=q,
            serpapi_location=loc_s,
            serpapi_max_pages=pages,
        )
    except Exception as e:
        STATE.jobs_raw = []
        STATE.jobs_source = "none"
        STATE.jobs_error = str(e)
    finally:
        save_serpapi_prefs(STATE.serpapi_query, STATE.serpapi_location)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_persistence_defaults()
    prefs = load_serpapi_prefs()
    STATE.serpapi_query = prefs["query"]
    STATE.serpapi_location = prefs["location"]
    STATE.career_tracker_selection = load_career_tracker_filter()
    _hydrate_jobs_from_disk_cache()
    if STATE.career_tracker_selection and not STATE.career_tracker_rows:
        jobs, errs, notes = fetch_tracked_career_jobs(
            STATE.career_tracker_selection,
            force_refresh=False,
            use_cache=True,
            allow_network=False,
        )
        if jobs:
            STATE.career_tracker_rows = jobs
            STATE.career_tracker_errs = errs
            STATE.career_cache_notes = notes
        elif errs:
            STATE.career_tracker_errs = errs
    yield


ROOT = Path(__file__).resolve().parents[1]
WEB_DIST = ROOT / "web" / "dist"

app = FastAPI(title="TalentHawk API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:3000", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChartIncludesModel(BaseModel):
    title_tokens: list[str] = Field(default_factory=list)
    summary_tokens: list[str] = Field(default_factory=list)
    summary_buckets: list[str] = Field(default_factory=list)
    include_categories: list[str] = Field(default_factory=list)
    include_companies: list[str] = Field(default_factory=list)
    include_titles_exact: list[str] = Field(default_factory=list)

    def to_core(self) -> ChartIncludes:
        return ChartIncludes(
            title_tokens=list(self.title_tokens),
            summary_tokens=list(self.summary_tokens),
            summary_buckets=list(self.summary_buckets),
            include_categories=list(self.include_categories),
            include_companies=list(self.include_companies),
            include_titles_exact=list(self.include_titles_exact),
        )


class JobsViewRequest(BaseModel):
    search_q: str = ""
    days_window: int = 30
    chart_includes: ChartIncludesModel = Field(default_factory=ChartIncludesModel)


class CareerViewRequest(BaseModel):
    chart_includes: ChartIncludesModel = Field(default_factory=ChartIncludesModel)


class RefreshJobsRequest(BaseModel):
    mode: str = "remotive"
    serpapi_query: str = ""
    serpapi_location: str = ""
    serpapi_pages: int = 3
    jobs_recency_days: int = 30
    bypass_cache: bool = False


class RefreshCareerRequest(BaseModel):
    company_ids: list[str]
    bypass_cache: bool = False


class SaveTitleIgnoreRequest(BaseModel):
    text: str


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/bootstrap")
def bootstrap() -> dict[str, Any]:
    mappings = load_career_page_mappings()
    companies: list[dict[str, str]] = []
    for c in mappings.get("companies", []):
        if isinstance(c, dict):
            cid = str(c.get("id", "")).strip()
            if cid:
                companies.append({"id": cid, "label": str(c.get("display_name", cid)).strip() or cid})
    return {
        "recency_day_choices": list(RECENCY_DAY_CHOICES),
        "cache_ttl_hours": DEFAULT_TTL_SECONDS // 3600,
        "serpapi_key_configured": bool(_serpapi_key()),
        "career_companies": companies,
        "state": {
            "jobs_source": STATE.jobs_source,
            "jobs_error": STATE.jobs_error,
            "jobs_fetch_mode": STATE.jobs_fetch_mode,
            "serpapi_query": STATE.serpapi_query,
            "serpapi_location": STATE.serpapi_location,
            "serpapi_pages": STATE.serpapi_pages,
            "jobs_recency_days": STATE.jobs_recency_days,
            "career_tracker_selection": STATE.career_tracker_selection,
            "career_tracker_errs": STATE.career_tracker_errs,
            "career_cache_notes": STATE.career_cache_notes,
            "jobs_count": len(STATE.jobs_raw),
            "career_count": len(STATE.career_tracker_rows),
        },
        "filters": {
            "title": load_title_filters(),
            "company": load_company_filters(),
            "category": load_category_filters(),
            "title_ignore_words": load_title_ignore_words(),
        },
    }


@app.post("/api/jobs/view")
def jobs_view(body: JobsViewRequest) -> dict[str, Any]:
    days = body.days_window if body.days_window in RECENCY_DAY_CHOICES else 30
    chart = body.chart_includes.to_core()
    bundle = compute_jobs_api_bundle(
        STATE.jobs_raw,
        days_window=days,
        title_filters=load_title_filters(),
        company_filters=load_company_filters(),
        category_filters=load_category_filters(),
        title_ignore_words=load_title_ignore_words(),
        search_q=body.search_q,
        chart_includes=chart,
    )
    return {
        **bundle,
        "has_fetched_jobs": STATE.jobs_source is not None,
        "jobs_source": STATE.jobs_source,
        "jobs_error": STATE.jobs_error,
        "days_window": days,
    }


@app.post("/api/jobs/refresh")
def refresh_jobs(body: RefreshJobsRequest) -> dict[str, Any]:
    if body.mode not in ("remotive", "serpapi", "both"):
        raise HTTPException(status_code=400, detail="Invalid mode")
    STATE.jobs_fetch_mode = body.mode
    STATE.serpapi_query = body.serpapi_query
    STATE.serpapi_location = body.serpapi_location
    STATE.serpapi_pages = max(1, min(5, int(body.serpapi_pages or 3)))
    if body.jobs_recency_days in RECENCY_DAY_CHOICES:
        STATE.jobs_recency_days = body.jobs_recency_days
    load_jobs_into_session(bypass_cache=body.bypass_cache)
    return {
        "ok": STATE.jobs_error is None,
        "error": STATE.jobs_error,
        "count": len(STATE.jobs_raw),
        "source": STATE.jobs_source,
    }


@app.post("/api/career/refresh")
def refresh_career(body: RefreshCareerRequest) -> dict[str, Any]:
    if not body.company_ids:
        raise HTTPException(status_code=400, detail="Select at least one company")
    sel = [str(x).strip() for x in body.company_ids if str(x).strip()]
    jobs, errs, notes = fetch_tracked_career_jobs(
        sel,
        force_refresh=body.bypass_cache,
        use_cache=not body.bypass_cache,
    )
    STATE.career_tracker_rows = jobs
    STATE.career_tracker_errs = errs
    STATE.career_cache_notes = notes
    STATE.career_tracker_selection = sel
    save_career_tracker_filter(sel)
    return {"ok": bool(jobs), "count": len(jobs), "errs": errs, "notes": notes}


@app.post("/api/filters/title-ignore")
def save_title_ignore(body: SaveTitleIgnoreRequest) -> dict[str, Any]:
    words = parse_title_ignore_words_input(body.text)
    save_title_ignore_words(words)
    return {"saved": len(words)}


@app.delete("/api/filters/title/{entry:path}")
def remove_title_filter(entry: str) -> dict[str, str]:
    fl = [x for x in load_title_filters() if x != entry]
    save_title_filters(fl)
    return {"ok": "true"}


@app.delete("/api/filters/company/{entry:path}")
def remove_company_filter(entry: str) -> dict[str, str]:
    fl = [x for x in load_company_filters() if x != entry]
    save_company_filters(fl)
    return {"ok": "true"}


@app.delete("/api/filters/category/{entry:path}")
def remove_category_filter(entry: str) -> dict[str, str]:
    fl = [x for x in load_category_filters() if x != entry]
    save_category_filters(fl)
    return {"ok": "true"}


class AddFilterRequest(BaseModel):
    value: str


@app.post("/api/filters/title")
def add_title_filter(body: AddFilterRequest) -> dict[str, str]:
    t = body.value.strip()
    if not t:
        raise HTTPException(status_code=400, detail="Empty")
    fl = load_title_filters()
    if matches_text_filter(t, fl):
        return {"ok": "duplicate"}
    fl.append(t)
    save_title_filters(fl)
    return {"ok": "true"}


@app.post("/api/filters/company")
def add_company_filter(body: AddFilterRequest) -> dict[str, str]:
    c = body.value.strip()
    if not c:
        raise HTTPException(status_code=400, detail="Empty")
    fl = load_company_filters()
    if matches_text_filter(c, fl):
        return {"ok": "duplicate"}
    fl.append(c)
    save_company_filters(fl)
    return {"ok": "true"}


@app.post("/api/filters/category")
def add_category_filter(body: AddFilterRequest) -> dict[str, str]:
    cat = body.value.strip()
    if not cat:
        raise HTTPException(status_code=400, detail="Empty")
    fl = load_category_filters()
    if matches_text_filter(cat, fl):
        return {"ok": "duplicate"}
    fl.append(cat)
    save_category_filters(fl)
    return {"ok": "true"}


@app.post("/api/session/career-selection")
def save_career_selection(body: dict[str, Any]) -> dict[str, str]:
    raw = body.get("company_ids")
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="company_ids must be a list")
    sel = [str(x).strip() for x in raw if str(x).strip()]
    STATE.career_tracker_selection = sel
    save_career_tracker_filter(sel)
    return {"ok": "true"}


def _career_row_json(r: dict[str, Any]) -> dict[str, Any]:
    title = str(r.get("title", "") or "")
    company = str(r.get("company", "") or "").strip()
    job_id = str(r.get("job_id", "") or "").strip()
    location = str(r.get("salary", "") or "").strip()
    return {
        "title": title,
        "title_truncated": truncate(title, 72),
        "company": company,
        "company_truncated": truncate(company, 36) if company else "—",
        "job_id": job_id,
        "location": location,
        "location_truncated": truncate(location, 28) if location else "—",
        "compensation": salary_line_for_career_row(r),
        "compensation_truncated": truncate(salary_line_for_career_row(r), 48),
        "published_at": str(r.get("published_at", "") or "").strip(),
        "updated_at": str(r.get("updated_at", "") or "").strip(),
        "url": str(r.get("url", "") or "").strip(),
    }



@app.post("/api/career/view")
def career_view(body: CareerViewRequest) -> dict[str, Any]:
    chart = body.chart_includes.to_core()
    sorted_rows = sort_career_jobs_by_created_desc(STATE.career_tracker_rows)
    bundle = compute_career_bundle(
        sorted_rows,
        title_filters=load_title_filters(),
        company_filters=load_company_filters(),
        category_filters=load_category_filters(),
        title_ignore_words=load_title_ignore_words(),
        chart_includes=chart,
    )
    rows_raw: list[dict[str, Any]] = bundle["rows"]
    out = {**bundle, "errs": STATE.career_tracker_errs, "notes": STATE.career_cache_notes}
    out["rows_display"] = [_career_row_json(r) for r in rows_raw]
    return out


if WEB_DIST.is_dir():

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if (
            full_path.startswith("api")
            or full_path in ("docs", "redoc", "openapi.json")
            or full_path.startswith("docs")
        ):
            raise HTTPException(status_code=404, detail="Not found")
        index = WEB_DIST / "index.html"
        if not full_path:
            if index.is_file():
                return FileResponse(index)
            raise HTTPException(status_code=404, detail="Build the web app: cd web && npm run build")
        candidate = WEB_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        # Do not serve index.html for missing scripts/CSS (would break window.Plotly etc. with silent 200 + HTML body).
        last = full_path.rstrip("/").split("/")[-1] if full_path else ""
        if "." in last:
            raise HTTPException(
                status_code=404,
                detail=f"Missing static file: {full_path}. Run: cd web && npm run copy-plotly && npm run build",
            )
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Build the web app: cd web && npm run build")
