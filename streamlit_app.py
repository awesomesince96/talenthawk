"""
TalentHawk — browse recent remote jobs, filter by title, company, and derived category.

Run: uv run streamlit run streamlit_app.py — then use **Refresh jobs** in the sidebar to fetch feeds.
"""

from __future__ import annotations

import html
import os
import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from talenthawk.career_page_tracker import fetch_tracked_career_jobs, sort_career_jobs_by_created_desc
from talenthawk.categorize import categorize_title
from talenthawk.fetch_jobs import (
    fetch_jobs_feed,
    filter_last_n_days,
    matches_text_filter,
    parse_title_ignore_words_input,
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

MAX_TITLE_LEN = 72
MAX_COMPANY_LEN = 36
MAX_PAY_LEN = 28
MAX_CATEGORY_LEN = 22
TITLE_DIST_TOP_N = 25
TITLE_DIST_CHART_MAX = 56
TITLE_KEYWORD_DIST_TOP_N = 28

MAIN_LIST_HEIGHT_PX = 780

TITLE_KEYWORD_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "as",
        "is",
        "it",
        "be",
        "are",
        "was",
        "were",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "our",
        "your",
        "we",
        "you",
        "all",
        "any",
        "no",
        "not",
        "ii",
        "iii",
        "iv",
        "v",
        "remote",
        "usa",
        "us",
        "uk",
        "ea",
        "emea",
        "apac",
        "latam",
    }
)

_WORD_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.I)

RECENCY_DAY_CHOICES = (1, 3, 7, 14, 30)


def _format_recency_days(n: int) -> str:
    if n == 1:
        return "Last 1 day"
    return f"Last {n} days"


def _recency_window_phrase(n: int) -> str:
    """Natural phrase for captions, e.g. 'the last day' / 'the last 7 days'."""
    if n == 1:
        return "the last day"
    return f"the last {n} days"


def _truncate(text: str, max_len: int) -> str:
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _tokenize_title_words(title: str, *, min_len: int = 2) -> list[str]:
    """Lowercase alphanumeric tokens from a job title; skips very short tokens."""
    out: list[str] = []
    for m in _WORD_TOKEN_RE.finditer(title or ""):
        w = m.group(0).lower()
        if len(w) >= min_len and w not in TITLE_KEYWORD_STOPWORDS:
            out.append(w)
    return out


def _word_to_company_title_index(rows: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Map each token to (company, title) rows whose **title** contains it (one row per word at most)."""
    idx: dict[str, list[tuple[str, str]]] = {}
    for company, title in rows:
        if not (title or "").strip():
            continue
        co = (company or "").strip() or "—"
        ti = title.strip()
        row = (co, ti)
        seen: set[str] = set()
        for w in _tokenize_title_words(title):
            if w in seen:
                continue
            seen.add(w)
            idx.setdefault(w, []).append(row)
    return idx


def _hover_company_title_line(company: str, title: str) -> str:
    co = (company or "").strip() or "—"
    ti = (title or "").strip() or "—"
    return f"Company: {html.escape(co)}, Title: {html.escape(ti)}"


def _render_title_keyword_distribution(
    company_title_rows: list[tuple[str, str]],
    *,
    subheader: str = "Title keyword distribution",
) -> None:
    """Horizontal bar chart of how many rows contain each word in the title; hover lists company + title."""
    st.subheader(subheader)
    st.caption(
        "Each bar = rows whose **Title** contains the word (tokenized; common filler omitted). "
        "Hover a bar for **Company** and **Title** per row. Matches the table above."
    )
    idx = _word_to_company_title_index(company_title_rows)
    if not idx:
        st.caption("No title words to chart.")
        return
    ranked = sorted(idx.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:TITLE_KEYWORD_DIST_TOP_N]
    # Plotly draws first y category at the bottom — reverse so the most common word is at the top.
    ranked_bar = list(reversed(ranked))
    words_y = [w for w, _ in ranked_bar]
    cnts = [len(idx[w]) for w in words_y]
    hover_bodies = [
        "<br>".join(_hover_company_title_line(co, ti) for co, ti in idx[w]) for w in words_y
    ]

    fig = go.Figure(
        data=go.Bar(
            x=cnts,
            y=words_y,
            orientation="h",
            customdata=hover_bodies,
            marker=dict(color=cnts, colorscale="Viridis", showscale=False),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "<b>%{x}</b> row(s)<br><br>"
                "%{customdata}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        height=max(300, min(900, 36 * len(words_y) + 120)),
        margin=dict(l=8, r=8, t=12, b=48),
        xaxis_title="Rows (title contains word)",
        yaxis=dict(title=""),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_top_n_pie(
    df: pd.DataFrame,
    column: str,
    *,
    subheader: str,
    dimension_description: str,
    other_noun: str,
    empty_caption: str = "No rows to chart.",
    label_max: int = TITLE_DIST_CHART_MAX,
    top_n: int = TITLE_DIST_TOP_N,
) -> None:
    """Pie of value counts for ``column``; top ``top_n`` slices plus **Other** when needed."""
    if subheader:
        st.subheader(subheader)
    if df.empty or column not in df.columns:
        st.caption(empty_caption)
        return
    ser = df[column].fillna("(empty)").astype(str)
    vc = ser.value_counts().rename_axis("value").reset_index(name="count")
    n_distinct = len(vc)
    if n_distinct == 0:
        st.caption(empty_caption)
        return
    pie_rows: list[dict] = []
    for _, r in vc.head(top_n).iterrows():
        v = str(r["value"])
        pie_rows.append({"label": _truncate(v, label_max), "count": int(r["count"]), "hover": v})
    if n_distinct > top_n:
        rest = vc.iloc[top_n:]
        other_count = int(rest["count"].sum())
        n_other = n_distinct - top_n
        pie_rows.append(
            {
                "label": f"Other ({n_other} {other_noun})",
                "count": other_count,
                "hover": f"{n_other} distinct {other_noun} not in top {top_n} ({other_count} job rows)",
            }
        )
    pie_df = pd.DataFrame(pie_rows)
    fig = px.pie(
        pie_df,
        names="label",
        values="count",
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.update_traces(
        textinfo="label+percent",
        textposition="auto",
        insidetextorientation="radial",
        hovertemplate="<b>%{customdata}</b><br>Jobs: %{value}<br>%{percent}<extra></extra>",
        customdata=pie_df["hover"],
    )
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="v", yanchor="middle", y=0.5, font=dict(size=11)),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.caption(
        f"Pie by {dimension_description}: top {min(top_n, n_distinct)} of {n_distinct} distinct {other_noun}; "
        "remaining grouped as **Other** when needed. Hover for the full label."
    )
    st.plotly_chart(fig, use_container_width=True)


def ensure_persistence_defaults() -> None:
    paths = persistence_paths()
    paths["persistence_dir"].mkdir(parents=True, exist_ok=True)
    paths["mappings_dir"].mkdir(parents=True, exist_ok=True)
    if not paths["title_filter"].exists():
        save_title_filters([])
    if not paths["company_filter"].exists():
        save_company_filters([])
    if not paths["category_filter"].exists():
        save_category_filters([])
    if not paths["title_ignore_words"].exists():
        save_title_ignore_words([])
    load_career_page_mappings()


def _persist_career_tracker_selection() -> None:
    save_career_tracker_filter(list(st.session_state.get("career_tracker_selection") or []))


def add_company_filter(company: str) -> None:
    c = str(company).strip()
    if not c:
        return
    fl = load_company_filters()
    if matches_text_filter(c, fl):
        return
    fl.append(c)
    save_company_filters(fl)


def add_title_filter(title: str) -> None:
    t = str(title).strip()
    if not t:
        return
    fl = load_title_filters()
    if matches_text_filter(t, fl):
        return
    fl.append(t)
    save_title_filters(fl)


def remove_company_filter_entry(entry: str) -> None:
    fl = [x for x in load_company_filters() if x != entry]
    save_company_filters(fl)


def remove_title_filter_entry(entry: str) -> None:
    fl = [x for x in load_title_filters() if x != entry]
    save_title_filters(fl)


def add_category_filter(category: str) -> None:
    cat = str(category).strip()
    if not cat:
        return
    fl = load_category_filters()
    if matches_text_filter(cat, fl):
        return
    fl.append(cat)
    save_category_filters(fl)


def remove_category_filter_entry(entry: str) -> None:
    fl = [x for x in load_category_filters() if x != entry]
    save_category_filters(fl)


def render_sidebar_filters(
    title_filters: list[str],
    company_filters: list[str],
    category_filters: list[str],
) -> None:
    st.header("Filters")
    st.caption(
        "Substring match, case-insensitive. **Title ignore words** = comma/newline keywords; "
        "on **Jobs API** use **−** on a row for title/company/category rules; **✕** removes a saved rule."
    )

    niw = len(load_title_ignore_words())
    with st.expander(f"Title ignore words ({niw})", expanded=False):
        st.caption(
            "Comma or newline separated. If a job **title** contains any phrase (case-insensitive), it is hidden. "
            "Saved to `data/persistence/title_ignore_words.json`."
        )
        st.text_area(
            "Words or phrases",
            key="title_ignore_words_input",
            height=96,
            placeholder="e.g. manager, sales, director",
            label_visibility="visible",
        )
        if st.button("Save title ignore words", key="save_title_ignore_words_btn"):
            words = parse_title_ignore_words_input(str(st.session_state.get("title_ignore_words_input") or ""))
            save_title_ignore_words(words)
            st.session_state.pop("title_ignore_words_input", None)
            st.toast(f"Saved {len(words)} phrase(s).")
            st.rerun()

    nt, nc, ng = len(title_filters), len(company_filters), len(category_filters)
    with st.expander(f"Title ({nt})", expanded=False):
        if not title_filters:
            st.caption("No rules yet.")
        else:
            for i, entry in enumerate(title_filters):
                c_l, c_r = st.columns([0.78, 0.22], vertical_alignment="center")
                with c_l:
                    st.text(_truncate(entry, 42))
                with c_r:
                    if st.button("✕", key=f"sb_title_rm_{i}", help="Remove from title filter"):
                        remove_title_filter_entry(entry)
                        st.toast("Removed title rule")
                        st.rerun()

    with st.expander(f"Company ({nc})", expanded=False):
        if not company_filters:
            st.caption("No rules yet.")
        else:
            for i, entry in enumerate(company_filters):
                c_l, c_r = st.columns([0.78, 0.22], vertical_alignment="center")
                with c_l:
                    st.text(_truncate(entry, 42))
                with c_r:
                    if st.button("✕", key=f"sb_co_rm_{i}", help="Remove from company filter"):
                        remove_company_filter_entry(entry)
                        st.toast("Removed company rule")
                        st.rerun()

    with st.expander(f"Category ({ng})", expanded=False):
        if not category_filters:
            st.caption("Inferred from job title — none yet.")
        else:
            st.caption("Inferred label, not raw title.")
            for i, entry in enumerate(category_filters):
                c_l, c_r = st.columns([0.78, 0.22], vertical_alignment="center")
                with c_l:
                    st.text(_truncate(entry, 36))
                with c_r:
                    if st.button("✕", key=f"sb_cat_rm_{i}", help="Remove from category filter"):
                        remove_category_filter_entry(entry)
                        st.toast("Removed category rule")
                        st.rerun()

    with st.expander("Persistence paths"):
        for label, path in persistence_paths().items():
            st.caption(f"{label}: `{path}`")


def annotate_jobs(jobs: list[dict]) -> list[dict]:
    out = []
    for j in jobs:
        title = j.get("title") or ""
        company = j.get("company") or ""
        salary = j.get("salary") or ""
        raw = j.get("raw") if isinstance(j.get("raw"), dict) else {}
        jid = j.get("job_id")
        if not jid and raw:
            rid = raw.get("id")
            jid = str(rid).strip() if rid is not None and str(rid).strip() else ""
        job_id = str(jid).strip() if jid else ""
        cat = categorize_title(title)
        row = {
            **j,
            "job_id": job_id,
            "category": cat,
            "company": company,
            "title": title,
            "salary": salary if salary else "",
        }
        out.append(row)
    return out


def _serpapi_key() -> str | None:
    for env in ("SERPAPI_API_KEY", "SERPAPI_KEY"):
        v = os.environ.get(env, "").strip()
        if v:
            return v
    try:
        sec = st.secrets.get("SERPAPI_API_KEY", "")
        if sec and str(sec).strip():
            return str(sec).strip()
    except (FileNotFoundError, KeyError, AttributeError, RuntimeError):
        pass
    return None


def load_jobs_into_session() -> None:
    mode = str(st.session_state.get("jobs_fetch_mode", "remotive"))
    if mode not in ("remotive", "serpapi", "both"):
        mode = "remotive"
    q = (st.session_state.get("serpapi_query") or "software engineer").strip()
    loc = (st.session_state.get("serpapi_location") or "").strip() or None
    pages = int(st.session_state.get("serpapi_pages", 3) or 3)
    pages = max(1, min(5, pages))
    try:
        jobs, label = fetch_jobs_feed(
            mode,
            serpapi_api_key=_serpapi_key(),
            serpapi_query=q,
            serpapi_location=loc,
            serpapi_max_pages=pages,
        )
        st.session_state["jobs_raw"] = jobs
        st.session_state["jobs_source"] = label
        st.session_state.pop("jobs_error", None)
    except Exception as e:
        st.session_state["jobs_raw"] = []
        st.session_state["jobs_source"] = "none"
        st.session_state["jobs_error"] = str(e)
    finally:
        save_serpapi_prefs(
            str(st.session_state.get("serpapi_query") or ""),
            str(st.session_state.get("serpapi_location") or ""),
        )


def job_is_included(
    job: dict,
    title_filters: list[str],
    company_filters: list[str],
    category_filters: list[str],
    title_ignore_words: list[str],
) -> bool:
    t = job.get("title") or ""
    c = job.get("company") or ""
    g = job.get("category") or ""
    if matches_text_filter(t, title_filters):
        return False
    if matches_text_filter(t, title_ignore_words):
        return False
    if matches_text_filter(c, company_filters):
        return False
    if matches_text_filter(g, category_filters):
        return False
    return True


def main() -> None:
    st.set_page_config(page_title="TalentHawk", layout="wide")
    st.markdown(
        """
        <style>
        .main .block-container {
            padding-top: 0.65rem !important;
            padding-bottom: 0.65rem !important;
            max-width: 100%;
        }
        section[data-testid="stSidebar"] .block-container {
            padding-top: 0.5rem !important;
            padding-bottom: 0.5rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    ensure_persistence_defaults()

    if "jobs_fetch_mode" not in st.session_state:
        st.session_state["jobs_fetch_mode"] = "remotive"
    if "serpapi_query" not in st.session_state:
        prefs = load_serpapi_prefs()
        st.session_state["serpapi_query"] = prefs["query"]
        st.session_state["serpapi_location"] = prefs["location"]
    if "serpapi_pages" not in st.session_state:
        st.session_state["serpapi_pages"] = 3
    if "jobs_recency_days" not in st.session_state:
        st.session_state["jobs_recency_days"] = 30

    if "jobs_raw" not in st.session_state:
        st.session_state["jobs_raw"] = []
    if "career_tracker_selection" not in st.session_state:
        st.session_state["career_tracker_selection"] = load_career_tracker_filter()
    if "career_tracker_rows" not in st.session_state:
        st.session_state["career_tracker_rows"] = []
    if "career_tracker_errs" not in st.session_state:
        st.session_state["career_tracker_errs"] = []
    if "title_ignore_words_input" not in st.session_state:
        st.session_state["title_ignore_words_input"] = ", ".join(load_title_ignore_words())

    title_filters = load_title_filters()
    company_filters = load_company_filters()
    category_filters = load_category_filters()

    with st.sidebar:
        st.markdown("###### TalentHawk")
        render_sidebar_filters(title_filters, company_filters, category_filters)

        view = st.radio(
            "View",
            ["Career page tracker", "Jobs API"],
            key="main_view",
        )

        if view == "Jobs API":
            st.header("Jobs")
            st.caption("Feeds run only when you click **Refresh jobs** (no auto-fetch on load).")
            st.selectbox(
                "Job source",
                options=["remotive", "serpapi", "both"],
                format_func=lambda x: {
                    "remotive": "Remotive (free, no API key)",
                    "serpapi": "SerpAPI — Google Jobs",
                    "both": "Remotive + SerpAPI (merged)",
                }[x],
                key="jobs_fetch_mode",
            )
            st.selectbox(
                "Posted within",
                options=list(RECENCY_DAY_CHOICES),
                format_func=_format_recency_days,
                key="jobs_recency_days",
            )
            st.text_input(
                "SerpAPI search query (`q`)",
                key="serpapi_query",
                help="Stored in data/persistence/serpapi_prefs.json when you Refresh jobs; SerpAPI runs only on refresh.",
            )
            st.text_input(
                "SerpAPI location (optional)",
                placeholder="e.g. United States",
                key="serpapi_location",
                help="Stored locally with the query on Refresh jobs; sent to SerpAPI only when you refresh.",
            )
            st.number_input("SerpAPI pages (10 jobs/page, max 5)", min_value=1, max_value=5, step=1, key="serpapi_pages")
            if st.session_state.get("jobs_fetch_mode") in ("serpapi", "both"):
                if not _serpapi_key():
                    st.warning("Set **SERPAPI_API_KEY** in the environment or `.streamlit/secrets.toml`.")

            if st.button("Refresh jobs", type="primary"):
                with st.spinner("Fetching…"):
                    load_jobs_into_session()
                    err = st.session_state.get("jobs_error")
                    n = len(st.session_state.get("jobs_raw") or [])
                    if err:
                        st.error(err)
                    else:
                        st.success(f"Loaded {n} listings ({st.session_state.get('jobs_source', '?')}).")

            has_fetched_jobs = "jobs_source" in st.session_state
            if not has_fetched_jobs:
                st.caption("**Source:** not loaded yet")
            else:
                src = st.session_state.get("jobs_source", "?")
                st.caption(f"**Source:** {src}")
            err = st.session_state.get("jobs_error")
            if err and has_fetched_jobs:
                st.caption(f"Last fetch error: {err}")

        elif view == "Career page tracker":
            st.divider()
            st.subheader("Career page tracker")
            _cm = load_career_page_mappings()
            _ids: list[str] = []
            _id_label: dict[str, str] = {}
            for _c in _cm.get("companies", []):
                if isinstance(_c, dict):
                    _i = str(_c.get("id", "")).strip()
                    if not _i:
                        continue
                    _ids.append(_i)
                    _id_label[_i] = str(_c.get("display_name", _i)).strip() or _i
            st.multiselect(
                "Companies to track",
                options=_ids,
                format_func=lambda x: _id_label.get(x, x),
                key="career_tracker_selection",
                help="Saved to data/persistence/career_page_tracker_filter.json",
                on_change=_persist_career_tracker_selection,
            )
            st.caption("Refresh listings in the main area.")

    title_ignore_words = load_title_ignore_words()

    # After sidebar widgets + optional refresh: re-read jobs so the first Refresh click updates the main area
    # in the same run (Streamlit executes top-to-bottom).
    has_fetched_jobs = "jobs_source" in st.session_state
    days_window = int(st.session_state.get("jobs_recency_days", 30) or 30)
    if days_window not in RECENCY_DAY_CHOICES:
        days_window = 30
    raw = st.session_state.get("jobs_raw") or []
    windowed = filter_last_n_days(raw, days=days_window)
    annotated = annotate_jobs(windowed)

    included = [
        j
        for j in annotated
        if job_is_included(j, title_filters, company_filters, category_filters, title_ignore_words)
    ]
    excluded_title = [j for j in annotated if matches_text_filter(j["title"], title_filters)]
    excluded_title_words = [j for j in annotated if matches_text_filter(j["title"], title_ignore_words)]
    excluded_company = [j for j in annotated if matches_text_filter(j["company"], company_filters)]
    excluded_category = [j for j in annotated if matches_text_filter(j["category"], category_filters)]

    if view == "Career page tracker":
        st.caption(
            "Roles come from each company’s configured **careers list URL** and fetcher in "
            "`data/mappings/career_page_mappings.json`. "
            "**Uber** (`loadSearchJobsResults`), **Netflix** (Eightfold), **Microsoft** (PCSX): **USA** locations where applicable, up to **50** rows per company, **newest created first**; **Updated** when the API provides it."
        )
        if st.button("Refresh career listings", type="primary"):
            sel = list(st.session_state.get("career_tracker_selection") or [])
            if not sel:
                st.warning("Select at least one company under **Career page tracker** in the sidebar.")
            else:
                with st.spinner("Fetching career pages…"):
                    jobs, errs = fetch_tracked_career_jobs(sel)
                st.session_state["career_tracker_rows"] = jobs
                st.session_state["career_tracker_errs"] = errs
                if not errs and jobs:
                    st.success(f"Loaded {len(jobs)} role(s).")
                elif errs and jobs:
                    st.success(f"Loaded {len(jobs)} role(s) with warnings.")
                elif errs:
                    st.error("Could not load listings; see warnings below.")

        for msg in st.session_state.get("career_tracker_errs") or []:
            st.warning(msg)

        c_rows = sort_career_jobs_by_created_desc(st.session_state.get("career_tracker_rows") or [])
        if c_rows:
            visible_career = [
                r
                for r in c_rows
                if job_is_included(r, title_filters, company_filters, category_filters, title_ignore_words)
            ]
            n_c = len(c_rows)
            n_vis = len(visible_career)
            if n_vis < n_c:
                st.caption(f"Showing **{n_vis}** of {n_c} role(s); the rest match a sidebar exclude rule.")
            st.caption(
                "The **filter** control next to **Title** adds that text to the **Title** exclude list (same rules as **−** on **Jobs API**); matching roles disappear here and there."
            )
            if not visible_career:
                st.info(
                    "Every loaded role matches a title rule, **Title ignore words**, or company/category rule. "
                    "Adjust the sidebar **Title ignore words** and **Filters** panel."
                )
            else:
                # ``salary`` in career rows holds location text from fetchers; optional ``compensation`` if present.
                _ccw = [1.65, 0.32, 1.0, 0.48, 0.95, 0.72, 0.68, 0.68, 0.42]
                with st.container(height=MAIN_LIST_HEIGHT_PX, border=True):
                    hdr = st.columns(_ccw, vertical_alignment="center")
                    hdr[0].markdown("**Title**")
                    hdr[1].markdown("** **")
                    hdr[2].markdown("**Company**")
                    hdr[3].markdown("**ID**")
                    hdr[4].markdown("**Location**")
                    hdr[5].markdown("**Salary**")
                    hdr[6].markdown("**Created**")
                    hdr[7].markdown("**Updated**")
                    hdr[8].markdown("**Link**")

                    for pos, row in enumerate(visible_career):
                        title = str(row.get("title", "") or "")
                        company = str(row.get("company", "") or "").strip()
                        job_id = str(row.get("job_id", "") or "").strip()
                        location = str(row.get("salary", "") or "").strip()
                        compensation = str(row.get("compensation") or row.get("pay") or "").strip()
                        pub = str(row.get("published_at", "") or "").strip()
                        upd = str(row.get("updated_at", "") or "").strip()
                        url = str(row.get("url", "") or "").strip()
                        row_key = f"career_{pos}"

                        cols = st.columns(_ccw, vertical_alignment="center")
                        with cols[0]:
                            st.text(_truncate(title, MAX_TITLE_LEN))
                        with cols[1]:
                            t_disabled = (
                                not title.strip()
                                or matches_text_filter(title, title_filters)
                                or matches_text_filter(title, title_ignore_words)
                            )
                            if st.button(
                                "",
                                key=f"ctf_title_{row_key}",
                                help="Add to Title exclude filter (substring match)",
                                disabled=t_disabled,
                                icon=":material/filter_list:",
                            ):
                                add_title_filter(title)
                                st.toast("Title excluded (filter updated)")
                                st.rerun()
                        with cols[2]:
                            st.text(_truncate(company, MAX_COMPANY_LEN) if company else "—")
                        with cols[3]:
                            st.text(job_id if job_id else "—")
                        with cols[4]:
                            st.text(_truncate(location, MAX_PAY_LEN) if location else "—")
                        with cols[5]:
                            st.text(_truncate(compensation, MAX_PAY_LEN) if compensation else "—")
                        with cols[6]:
                            st.text(pub if pub else "—")
                        with cols[7]:
                            st.text(upd if upd else "—")
                        with cols[8]:
                            if url:
                                safe = html.escape(url, quote=True)
                                st.markdown(
                                    f'<a href="{safe}" target="_blank" rel="noopener noreferrer">Open</a>',
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.caption("—")
                _render_title_keyword_distribution(
                    [
                        (
                            str(r.get("company", "") or "").strip() or "—",
                            str(r.get("title", "") or ""),
                        )
                        for r in visible_career
                    ],
                )
        elif st.session_state.get("career_tracker_errs"):
            st.caption("No rows to show.")
        else:
            st.info("Select companies in the sidebar and click **Refresh career listings**.")

    elif view == "Jobs API":
        st.caption(
            f"**Window:** {_recency_window_phrase(days_window)} (when dated). "
            "**Remotive** = free · **SerpAPI** = paid. "
            "**−** = title/company/category rule · sidebar **Title ignore words** = keywords · **✕** removes rules."
        )
        if not has_fetched_jobs:
            st.info("Use **Refresh jobs** in the sidebar (**Remotive** / **SerpAPI** / both).")

        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
        c1.metric("Fetched (feed)", len(raw))
        c2.metric(_format_recency_days(days_window), len(windowed))
        c3.metric("Shown", len(included))
        c4.metric("Hidden (title rules)", len(excluded_title))
        c5.metric("Hidden (title words)", len(excluded_title_words))
        c6.metric("Hidden (company)", len(excluded_company))
        c7.metric("Hidden (category)", len(excluded_category))

        q = st.text_input("Search Jobs API listings (id, title, company, category, salary, source)", "")
        df_i = pd.DataFrame(included)
        if not df_i.empty:
            if q.strip():
                ql = q.lower()
                pay_col = df_i["salary"].fillna("").astype(str)
                id_col = df_i["job_id"].fillna("").astype(str)
                m = (
                    id_col.str.lower().str.contains(ql, na=False)
                    | df_i["title"].str.lower().str.contains(ql, na=False)
                    | df_i["company"].str.lower().str.contains(ql, na=False)
                    | df_i["category"].str.lower().str.contains(ql, na=False)
                    | pay_col.str.lower().str.contains(ql, na=False)
                )
                if "source" in df_i.columns:
                    m = m | df_i["source"].fillna("").astype(str).str.lower().str.contains(ql, na=False)
                df_show = df_i[m]
            else:
                df_show = df_i

            n_show = len(df_show)
            if n_show == 0:
                st.info("No rows match your search.")
            else:
                st.caption(
                    f"{n_show} row{'s' if n_show != 1 else ''} · **−** adds a title / company / category filter · **Salary** / **Open** from the feed"
                )

                _colw = [0.52, 1.78, 0.26, 1.12, 0.26, 0.52, 0.26, 0.85, 0.44]
                with st.container(height=MAIN_LIST_HEIGHT_PX, border=True):
                    hdr = st.columns(_colw, vertical_alignment="center")
                    hdr[0].markdown("**Job ID**")
                    hdr[1].markdown("**Title**")
                    hdr[2].markdown("** **")
                    hdr[3].markdown("**Company**")
                    hdr[4].markdown("** **")
                    hdr[5].markdown("**Cat**")
                    hdr[6].markdown("** **")
                    hdr[7].markdown("**Salary**")
                    hdr[8].markdown("**Link**")

                    for pos in range(n_show):
                        row = df_show.iloc[pos]
                        job_id = str(row.get("job_id", "") or "").strip()
                        title = str(row.get("title", "") or "")
                        company = str(row.get("company", "") or "").strip()
                        category = str(row.get("category", "") or "")
                        salary = str(row.get("salary", "") or "").strip()
                        url = str(row.get("url", "") or "").strip()
                        row_key = f"inc_{pos}"

                        cols = st.columns(_colw, vertical_alignment="center")
                        with cols[0]:
                            st.text(job_id if job_id else "—")
                        with cols[1]:
                            st.text(_truncate(title, MAX_TITLE_LEN))
                        with cols[2]:
                            t_disabled = not title or matches_text_filter(title, title_filters) or matches_text_filter(
                                title, title_ignore_words
                            )
                            if st.button(
                                "-",
                                key=f"tf_{row_key}",
                                help="Exclude jobs matching this title",
                                disabled=t_disabled,
                            ):
                                add_title_filter(title)
                                st.toast("Title excluded (filter updated)")
                                st.rerun()
                        with cols[3]:
                            st.text(_truncate(company, MAX_COMPANY_LEN) if company else "—")
                        with cols[4]:
                            c_disabled = not company or matches_text_filter(company, company_filters)
                            if st.button(
                                "-",
                                key=f"cf_{row_key}",
                                help="Exclude jobs from this company",
                                disabled=c_disabled,
                            ):
                                add_company_filter(company)
                                st.toast("Company excluded (filter updated)")
                                st.rerun()
                        with cols[5]:
                            st.text(_truncate(category, MAX_CATEGORY_LEN) if category else "—")
                        with cols[6]:
                            g_disabled = not category or matches_text_filter(category, category_filters)
                            if st.button(
                                "-",
                                key=f"gf_{row_key}",
                                help="Exclude jobs in this category",
                                disabled=g_disabled,
                            ):
                                add_category_filter(category)
                                st.toast("Category excluded (filter updated)")
                                st.rerun()
                        with cols[7]:
                            st.text(_truncate(salary, MAX_PAY_LEN) if salary else "—")
                        with cols[8]:
                            if url:
                                safe = html.escape(url, quote=True)
                                st.markdown(
                                    f'<a href="{safe}" target="_blank" rel="noopener noreferrer">Open</a>',
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.caption("—")
                _render_title_keyword_distribution(
                    [
                        (str(c).strip() or "—", str(t))
                        for c, t in zip(
                            df_show["company"].fillna("").astype(str),
                            df_show["title"].fillna("").astype(str),
                            strict=True,
                        )
                    ],
                )
        else:
            if not has_fetched_jobs:
                st.caption("Load listings with **Refresh jobs** in the sidebar.")
            else:
                st.info(f"No jobs in {_recency_window_phrase(days_window)} (or feed is empty).")

        with st.expander("Category distribution (Jobs API)", expanded=False):
            _render_top_n_pie(
                df_i,
                "category",
                subheader="",
                dimension_description="category inferred from job title",
                other_noun="categories",
                empty_caption="No categories to chart.",
            )
        with st.expander("Company distribution (Jobs API)", expanded=False):
            _render_top_n_pie(
                df_i,
                "company",
                subheader="",
                dimension_description="company name",
                other_noun="companies",
                empty_caption="No companies to chart.",
            )
        with st.expander("Job title distribution (Jobs API)", expanded=False):
            _render_top_n_pie(
                df_i,
                "title",
                subheader="",
                dimension_description="exact job title",
                other_noun="titles",
                empty_caption="No titles to chart.",
            )


if __name__ == "__main__":
    main()
