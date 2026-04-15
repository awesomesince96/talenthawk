"""
TalentHawk — browse recent remote jobs, filter by title, company, and derived category.

Run: uv run streamlit run streamlit_app.py — then use **Refresh jobs** in the sidebar to fetch feeds.
"""

from __future__ import annotations

import html
import os
import re
from collections.abc import Callable

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from talenthawk.career_page_tracker import fetch_tracked_career_jobs, sort_career_jobs_by_created_desc
from talenthawk.salary_parse import (
    job_summary_plain_text,
    salary_display_for_api_job,
    salary_display_for_career_row,
)
from talenthawk.job_cache import (
    DEFAULT_TTL_SECONDS,
    ensure_jobs_cache_dirs,
    feed_cache_fingerprint,
    try_restore_jobs_session_from_feed_cache,
    write_jobs_feed_cache,
)
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
MAX_SALARY_DISPLAY_LEN = 48
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

SUMMARY_EXTRA_STOPWORDS = frozenset(
    {
        "experience",
        "years",
        "year",
        "working",
        "skills",
        "strong",
        "excellent",
        "looking",
        "including",
        "position",
        "role",
        "responsibilities",
        "requirements",
        "qualifications",
        "preferred",
        "required",
        "opportunities",
        "opportunity",
        "join",
        "business",
        "customers",
        "customer",
        "various",
        "related",
        "ensure",
        "support",
        "services",
        "service",
        "based",
        "global",
        "lead",
        "leading",
        "multiple",
        "well",
        "highly",
        "relevant",
        "understanding",
        "understand",
        "proven",
        "demonstrated",
        "environment",
        "internal",
        "external",
        "ability",
        "abilities",
        "must",
        "will",
    }
)

SUMMARY_KEYWORD_STOPWORDS = TITLE_KEYWORD_STOPWORDS | SUMMARY_EXTRA_STOPWORDS

SUMMARY_KEYWORD_DIST_TOP_N = 24
SUMMARY_LEN_BUCKET_ORDER = (
    "No summary text",
    "1–49 words",
    "50–149 words",
    "150–299 words",
    "300+ words",
)

_WORD_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.I)

RECENCY_DAY_CHOICES = (1, 3, 7, 14, 30)

# Temporary “chart hide” filters (session only): bar selections move jobs out of the table until toggled back.
SS_JOBS_HIDE_TITLE_KW = "jobs_api_chart_hide_title_tokens"
SS_JOBS_HIDE_SUMMARY_KW = "jobs_api_chart_hide_summary_tokens"
SS_JOBS_HIDE_SUMMARY_BUCKET = "jobs_api_chart_hide_summary_buckets"
SS_CAREER_HIDE_TITLE_KW = "career_chart_hide_title_tokens"
SS_CAREER_HIDE_SUMMARY_KW = "career_chart_hide_summary_tokens"
SS_CAREER_HIDE_SUMMARY_BUCKET = "career_chart_hide_summary_buckets"

# Bump to remount Plotly widgets after **Clear chart hides** so stale selection does not re-apply hides.
NONCE_PLOTLY_JOBS_TITLE_KW = "nonce_plotly_jobs_title_kw"
NONCE_PLOTLY_JOBS_SUM_LEN = "nonce_plotly_jobs_sum_len"
NONCE_PLOTLY_JOBS_SUM_KW = "nonce_plotly_jobs_sum_kw"
NONCE_PLOTLY_CAREER_TITLE_KW = "nonce_plotly_career_title_kw"
NONCE_PLOTLY_CAREER_SUM_LEN = "nonce_plotly_career_sum_len"
NONCE_PLOTLY_CAREER_SUM_KW = "nonce_plotly_career_sum_kw"


def _init_chart_hide_session_keys() -> None:
    for k in (
        SS_JOBS_HIDE_TITLE_KW,
        SS_JOBS_HIDE_SUMMARY_KW,
        SS_JOBS_HIDE_SUMMARY_BUCKET,
        SS_CAREER_HIDE_TITLE_KW,
        SS_CAREER_HIDE_SUMMARY_KW,
        SS_CAREER_HIDE_SUMMARY_BUCKET,
    ):
        if k not in st.session_state:
            st.session_state[k] = []
    for nk in (
        NONCE_PLOTLY_JOBS_TITLE_KW,
        NONCE_PLOTLY_JOBS_SUM_LEN,
        NONCE_PLOTLY_JOBS_SUM_KW,
        NONCE_PLOTLY_CAREER_TITLE_KW,
        NONCE_PLOTLY_CAREER_SUM_LEN,
        NONCE_PLOTLY_CAREER_SUM_KW,
    ):
        if nk not in st.session_state:
            st.session_state[nk] = 0


def _plotly_points(chart_widget_key: str) -> list[dict]:
    w = st.session_state.get(chart_widget_key)
    if w is None:
        return []
    sel = getattr(w, "selection", None)
    if sel is None and isinstance(w, dict):
        sel = w.get("selection")
    if sel is None:
        return []
    if isinstance(sel, dict):
        pts = sel.get("points") or []
    else:
        pts = getattr(sel, "points", None) or []
    return [p for p in pts if isinstance(p, dict)]


def _sync_plotly_selection_to_hides(
    chart_widget_key: str,
    hide_session_key: str,
    *,
    label_from_point: Callable[[dict], str | None],
) -> None:
    """
    Mirror current Plotly bar selection into the hide list (selected categories = hidden from the table).
    Call **before** building filtered job rows so the table and charts stay in sync.
    """
    if st.session_state.get(chart_widget_key) is None:
        return
    labels: list[str] = []
    for pt in _plotly_points(chart_widget_key):
        lab = label_from_point(pt)
        if lab:
            labels.append(lab)
    new_list = sorted({x for x in labels if x}, key=str.lower)
    old = sorted(list(st.session_state.get(hide_session_key) or []), key=str.lower)
    if new_list != old:
        st.session_state[hide_session_key] = new_list


def sync_jobs_api_plotly_selections_into_hides() -> None:
    """Apply Jobs API Plotly widget state to session hide lists (must run after widgets exist, before filtering)."""
    _sync_plotly_selection_to_hides(
        f"jobs_api_title_kw_plotly_{st.session_state.get(NONCE_PLOTLY_JOBS_TITLE_KW, 0)}",
        SS_JOBS_HIDE_TITLE_KW,
        label_from_point=lambda p: (str(p.get("y") or p.get("label") or "").strip() or None),
    )
    _sync_plotly_selection_to_hides(
        f"jobs_api_summary_len_plotly_{st.session_state.get(NONCE_PLOTLY_JOBS_SUM_LEN, 0)}",
        SS_JOBS_HIDE_SUMMARY_BUCKET,
        label_from_point=lambda p: (str(p.get("x") or p.get("label") or "").strip() or None),
    )
    _sync_plotly_selection_to_hides(
        f"jobs_api_summary_kw_plotly_{st.session_state.get(NONCE_PLOTLY_JOBS_SUM_KW, 0)}",
        SS_JOBS_HIDE_SUMMARY_KW,
        label_from_point=lambda p: (str(p.get("y") or p.get("label") or "").strip() or None),
    )


def sync_career_plotly_selections_into_hides() -> None:
    """Same as :func:`sync_jobs_api_plotly_selections_into_hides` for Career tracker charts."""
    _sync_plotly_selection_to_hides(
        f"career_title_kw_plotly_{st.session_state.get(NONCE_PLOTLY_CAREER_TITLE_KW, 0)}",
        SS_CAREER_HIDE_TITLE_KW,
        label_from_point=lambda p: (str(p.get("y") or p.get("label") or "").strip() or None),
    )
    _sync_plotly_selection_to_hides(
        f"career_summary_len_plotly_{st.session_state.get(NONCE_PLOTLY_CAREER_SUM_LEN, 0)}",
        SS_CAREER_HIDE_SUMMARY_BUCKET,
        label_from_point=lambda p: (str(p.get("x") or p.get("label") or "").strip() or None),
    )
    _sync_plotly_selection_to_hides(
        f"career_summary_kw_plotly_{st.session_state.get(NONCE_PLOTLY_CAREER_SUM_KW, 0)}",
        SS_CAREER_HIDE_SUMMARY_KW,
        label_from_point=lambda p: (str(p.get("y") or p.get("label") or "").strip() or None),
    )


def _filter_jobs_api_list_with_charts(jobs: list[dict], q: str) -> list[dict]:
    """Search box + temporary chart-driven hides (title token, summary token, length bucket)."""
    ht = set(st.session_state.get(SS_JOBS_HIDE_TITLE_KW) or [])
    hs = set(st.session_state.get(SS_JOBS_HIDE_SUMMARY_KW) or [])
    hb = set(st.session_state.get(SS_JOBS_HIDE_SUMMARY_BUCKET) or [])
    out: list[dict] = []
    for j in jobs:
        if not _jobs_api_row_matches_search(j, q):
            continue
        title = str(j.get("title") or "")
        if ht and not set(_tokenize_title_words(title)).isdisjoint(ht):
            continue
        if hs and not set(_tokenize_summary_words(job_summary_plain_text(j))).isdisjoint(hs):
            continue
        if hb:
            text = job_summary_plain_text(j)
            wc = len(text.split()) if text else 0
            b = _bucket_summary_word_count(wc)
            if b in hb:
                continue
        out.append(j)
    return out


def _filter_career_list_with_charts(rows: list[dict]) -> list[dict]:
    ht = set(st.session_state.get(SS_CAREER_HIDE_TITLE_KW) or [])
    hs = set(st.session_state.get(SS_CAREER_HIDE_SUMMARY_KW) or [])
    hb = set(st.session_state.get(SS_CAREER_HIDE_SUMMARY_BUCKET) or [])
    out: list[dict] = []
    for j in rows:
        title = str(j.get("title") or "")
        if ht and not set(_tokenize_title_words(title)).isdisjoint(ht):
            continue
        if hs and not set(_tokenize_summary_words(job_summary_plain_text(j))).isdisjoint(hs):
            continue
        if hb:
            text = job_summary_plain_text(j)
            wc = len(text.split()) if text else 0
            b = _bucket_summary_word_count(wc)
            if b in hb:
                continue
        out.append(j)
    return out


def _bump_jobs_plotly_nonces() -> None:
    for nk in (NONCE_PLOTLY_JOBS_TITLE_KW, NONCE_PLOTLY_JOBS_SUM_LEN, NONCE_PLOTLY_JOBS_SUM_KW):
        st.session_state[nk] = int(st.session_state.get(nk) or 0) + 1


def _bump_career_plotly_nonces() -> None:
    for nk in (NONCE_PLOTLY_CAREER_TITLE_KW, NONCE_PLOTLY_CAREER_SUM_LEN, NONCE_PLOTLY_CAREER_SUM_KW):
        st.session_state[nk] = int(st.session_state.get(nk) or 0) + 1


def _clear_all_jobs_chart_cross_filters() -> None:
    st.session_state[SS_JOBS_HIDE_TITLE_KW] = []
    st.session_state[SS_JOBS_HIDE_SUMMARY_KW] = []
    st.session_state[SS_JOBS_HIDE_SUMMARY_BUCKET] = []
    _bump_jobs_plotly_nonces()


def _clear_all_career_chart_cross_filters() -> None:
    st.session_state[SS_CAREER_HIDE_TITLE_KW] = []
    st.session_state[SS_CAREER_HIDE_SUMMARY_KW] = []
    st.session_state[SS_CAREER_HIDE_SUMMARY_BUCKET] = []
    _bump_career_plotly_nonces()


def _remove_one_cross_filter(hide_key: str, value: str) -> None:
    cur = [x for x in (st.session_state.get(hide_key) or []) if x != value]
    st.session_state[hide_key] = cur


def _render_cross_filter_panel_jobs() -> None:
    """Single place to see chart-driven filters that apply together (AND) across table + all charts."""
    ht = list(st.session_state.get(SS_JOBS_HIDE_TITLE_KW) or [])
    hs = list(st.session_state.get(SS_JOBS_HIDE_SUMMARY_KW) or [])
    hb = list(st.session_state.get(SS_JOBS_HIDE_SUMMARY_BUCKET) or [])
    if not ht and not hs and not hb:
        return
    with st.expander("Active chart cross-filters (session)", expanded=True):
        st.caption(
            "Bar selections on **title keywords**, **summary keywords**, and **summary length** combine here (**AND**). "
            "The table and every chart below use the same filtered rows. Remove a chip or clear all."
        )
        if st.button("Clear all chart cross-filters", key="clear_all_jobs_cross_filters"):
            _clear_all_jobs_chart_cross_filters()
            st.rerun()
        if ht:
            st.markdown("**Title keywords** (hidden if title contains token)")
            for i, v in enumerate(ht):
                c1, c2 = st.columns([0.88, 0.12], vertical_alignment="center")
                with c1:
                    st.text(v)
                with c2:
                    if st.button("✕", key=f"rm_jobs_tkw_{i}", help="Remove this title-keyword filter"):
                        _remove_one_cross_filter(SS_JOBS_HIDE_TITLE_KW, v)
                        st.rerun()
        if hs:
            st.markdown("**Summary keywords**")
            for i, v in enumerate(hs):
                c1, c2 = st.columns([0.88, 0.12], vertical_alignment="center")
                with c1:
                    st.text(v)
                with c2:
                    if st.button("✕", key=f"rm_jobs_skw_{i}", help="Remove this summary-keyword filter"):
                        _remove_one_cross_filter(SS_JOBS_HIDE_SUMMARY_KW, v)
                        st.rerun()
        if hb:
            st.markdown("**Summary length buckets**")
            for i, v in enumerate(hb):
                c1, c2 = st.columns([0.88, 0.12], vertical_alignment="center")
                with c1:
                    st.text(v)
                with c2:
                    if st.button("✕", key=f"rm_jobs_bkt_{i}", help="Remove this length-bucket filter"):
                        _remove_one_cross_filter(SS_JOBS_HIDE_SUMMARY_BUCKET, v)
                        st.rerun()


def _render_cross_filter_panel_career() -> None:
    ht = list(st.session_state.get(SS_CAREER_HIDE_TITLE_KW) or [])
    hs = list(st.session_state.get(SS_CAREER_HIDE_SUMMARY_KW) or [])
    hb = list(st.session_state.get(SS_CAREER_HIDE_SUMMARY_BUCKET) or [])
    if not ht and not hs and not hb:
        return
    with st.expander("Active chart cross-filters (session)", expanded=True):
        st.caption("Same as **Jobs API**: chart selections stack (**AND**); table and charts share one filtered dataset.")
        if st.button("Clear all chart cross-filters", key="clear_all_career_cross_filters"):
            _clear_all_career_chart_cross_filters()
            st.rerun()
        if ht:
            st.markdown("**Title keywords**")
            for i, v in enumerate(ht):
                c1, c2 = st.columns([0.88, 0.12], vertical_alignment="center")
                with c1:
                    st.text(v)
                with c2:
                    if st.button("✕", key=f"rm_car_tkw_{i}", help="Remove"):
                        _remove_one_cross_filter(SS_CAREER_HIDE_TITLE_KW, v)
                        st.rerun()
        if hs:
            st.markdown("**Summary keywords**")
            for i, v in enumerate(hs):
                c1, c2 = st.columns([0.88, 0.12], vertical_alignment="center")
                with c1:
                    st.text(v)
                with c2:
                    if st.button("✕", key=f"rm_car_skw_{i}", help="Remove"):
                        _remove_one_cross_filter(SS_CAREER_HIDE_SUMMARY_KW, v)
                        st.rerun()
        if hb:
            st.markdown("**Summary length buckets**")
            for i, v in enumerate(hb):
                c1, c2 = st.columns([0.88, 0.12], vertical_alignment="center")
                with c1:
                    st.text(v)
                with c2:
                    if st.button("✕", key=f"rm_car_bkt_{i}", help="Remove"):
                        _remove_one_cross_filter(SS_CAREER_HIDE_SUMMARY_BUCKET, v)
                        st.rerun()


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
    chart_key: str | None = None,
    hide_session_key: str | None = None,
    clear_nonce_key: str | None = None,
) -> None:
    """Horizontal bar chart of how many rows contain each word in the title; hover lists company + title."""
    st.subheader(subheader)
    st.caption(
        "Each bar = rows whose **Title** contains the word (tokenized; common filler omitted). "
        "Hover a bar for **Company** and **Title** per row. Matches the table above."
    )
    if chart_key and hide_session_key:
        st.caption(
            "**Interactive:** select one or more bars — the **table above** and **other charts** refresh on the next run "
            "(selected categories are hidden from results). Deselect all bars on this chart to clear its filter. "
            "**Clear chart hides** also resets this chart and remounts it."
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
    if chart_key and hide_session_key:
        st.plotly_chart(
            fig,
            width="stretch",
            key=chart_key,
            on_select="rerun",
            selection_mode="points",
        )
        if st.button("Clear chart hides", key=f"cl_{chart_key}"):
            st.session_state[hide_session_key] = []
            if clear_nonce_key:
                st.session_state[clear_nonce_key] = int(st.session_state.get(clear_nonce_key) or 0) + 1
            st.rerun()
        hid = st.session_state.get(hide_session_key) or []
        if hid:
            st.caption("Keywords hidden from the table (from bar selection): **" + "**, **".join(hid) + "**")
    else:
        st.plotly_chart(fig, use_container_width=True)


def _tokenize_summary_words(text: str, *, min_len: int = 3) -> list[str]:
    out: list[str] = []
    for m in _WORD_TOKEN_RE.finditer(text or ""):
        w = m.group(0).lower()
        if len(w) >= min_len and w not in SUMMARY_KEYWORD_STOPWORDS:
            out.append(w)
    return out


def _summary_word_index(company_title_rows_from_jobs: list[dict]) -> dict[str, list[tuple[str, str]]]:
    idx: dict[str, list[tuple[str, str]]] = {}
    for j in company_title_rows_from_jobs:
        company = (j.get("company") or "").strip() or "—"
        title = (j.get("title") or "").strip() or "—"
        text = job_summary_plain_text(j)
        seen: set[str] = set()
        for w in _tokenize_summary_words(text):
            if w in seen:
                continue
            seen.add(w)
            idx.setdefault(w, []).append((company, title))
    return idx


def _bucket_summary_word_count(wc: int) -> str:
    if wc <= 0:
        return "No summary text"
    if wc < 50:
        return "1–49 words"
    if wc < 150:
        return "50–149 words"
    if wc < 300:
        return "150–299 words"
    return "300+ words"


def _render_summary_length_distribution(
    jobs: list[dict],
    *,
    chart_key: str | None = None,
    hide_session_key: str | None = None,
    clear_nonce_key: str | None = None,
) -> None:
    """Histogram of word counts for :func:`talenthawk.salary_parse.job_summary_plain_text`."""
    st.subheader("Summary length (word count)")
    st.caption(
        "Teaser text when the feed provides it (e.g. **description_short**), else full cleaned description. "
        "Jobs with no text fall under **No summary text**."
    )
    if chart_key and hide_session_key:
        st.caption(
            "**Interactive:** select length bucket bar(s) to hide those jobs from the table; all charts update together."
        )
    counts: dict[str, int] = {k: 0 for k in SUMMARY_LEN_BUCKET_ORDER}
    for j in jobs:
        text = job_summary_plain_text(j)
        wc = len(text.split()) if text else 0
        b = _bucket_summary_word_count(wc)
        counts[b] = counts[b] + 1
    x = list(SUMMARY_LEN_BUCKET_ORDER)
    y = [counts[k] for k in x]
    if sum(y) == 0:
        st.caption("No rows to chart.")
        return
    fig = go.Figure(
        data=go.Bar(
            x=x,
            y=y,
            marker=dict(color=y, colorscale="Blues", showscale=False),
        )
    )
    fig.update_layout(
        height=320,
        margin=dict(l=8, r=8, t=12, b=80),
        xaxis_title="",
        yaxis_title="Jobs",
        showlegend=False,
        xaxis_tickangle=-28,
    )
    if chart_key and hide_session_key:
        st.plotly_chart(
            fig,
            width="stretch",
            key=chart_key,
            on_select="rerun",
            selection_mode="points",
        )
        if st.button("Clear chart hides", key=f"cl_{chart_key}"):
            st.session_state[hide_session_key] = []
            if clear_nonce_key:
                st.session_state[clear_nonce_key] = int(st.session_state.get(clear_nonce_key) or 0) + 1
            st.rerun()
        hid = st.session_state.get(hide_session_key) or []
        if hid:
            st.caption("Length buckets hidden from the table: **" + "**, **".join(hid) + "**")
    else:
        st.plotly_chart(fig, use_container_width=True)


def _render_summary_keyword_distribution(
    jobs: list[dict],
    *,
    chart_key: str | None = None,
    hide_session_key: str | None = None,
    clear_nonce_key: str | None = None,
) -> None:
    """Horizontal bar of token frequencies in summary text (hover: company + title)."""
    st.subheader("Summary keyword distribution")
    st.caption(
        "Each bar = rows whose **summary** text contains the token (HTML stripped; common résumé-style filler omitted)."
    )
    if chart_key and hide_session_key:
        st.caption(
            "**Interactive:** select bar(s) to hide those summary tokens from the table; charts stay aligned."
        )
    idx = _summary_word_index(jobs)
    if not idx:
        st.caption("No summary words to chart (add listings with description text).")
        return
    ranked = sorted(idx.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:SUMMARY_KEYWORD_DIST_TOP_N]
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
            marker=dict(color=cnts, colorscale="Cividis", showscale=False),
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
        xaxis_title="Rows (summary contains word)",
        yaxis=dict(title=""),
        showlegend=False,
    )
    if chart_key and hide_session_key:
        st.plotly_chart(
            fig,
            width="stretch",
            key=chart_key,
            on_select="rerun",
            selection_mode="points",
        )
        if st.button("Clear chart hides", key=f"cl_{chart_key}"):
            st.session_state[hide_session_key] = []
            if clear_nonce_key:
                st.session_state[clear_nonce_key] = int(st.session_state.get(clear_nonce_key) or 0) + 1
            st.rerun()
        hid = st.session_state.get(hide_session_key) or []
        if hid:
            st.caption("Summary keywords hidden from the table: **" + "**, **".join(hid) + "**")
    else:
        st.plotly_chart(fig, use_container_width=True)


def _jobs_api_row_matches_search(job: dict, q: str) -> bool:
    if not (q or "").strip():
        return True
    ql = q.strip().lower()
    parts = [
        str(job.get("job_id") or ""),
        str(job.get("title") or ""),
        str(job.get("company") or ""),
        str(job.get("category") or ""),
        str(job.get("salary") or ""),
        str(job.get("source") or ""),
    ]
    return any(ql in p.lower() for p in parts)


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
        row["salary"] = salary_display_for_api_job(row)
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


def _try_hydrate_jobs_from_disk_cache() -> bool:
    """Fill ``jobs_raw`` / ``jobs_source`` from ``data/jobs/feed/`` when TTL allows."""
    mode = str(st.session_state.get("jobs_fetch_mode", "remotive"))
    if mode not in ("remotive", "serpapi", "both"):
        mode = "remotive"
    q = (st.session_state.get("serpapi_query") or "software engineer").strip()
    loc_s = (st.session_state.get("serpapi_location") or "").strip()
    pages = int(st.session_state.get("serpapi_pages", 3) or 3)
    pages = max(1, min(5, pages))
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
    st.session_state["jobs_raw"] = jobs
    st.session_state["jobs_source"] = f"{label} (cached ≤{DEFAULT_TTL_SECONDS // 3600}h)"
    st.session_state.pop("jobs_error", None)
    return True


def load_jobs_into_session() -> None:
    mode = str(st.session_state.get("jobs_fetch_mode", "remotive"))
    if mode not in ("remotive", "serpapi", "both"):
        mode = "remotive"
    q = (st.session_state.get("serpapi_query") or "software engineer").strip()
    loc = (st.session_state.get("serpapi_location") or "").strip() or None
    loc_s = (st.session_state.get("serpapi_location") or "").strip()
    pages = int(st.session_state.get("serpapi_pages", 3) or 3)
    pages = max(1, min(5, pages))
    bypass = bool(st.session_state.get("jobs_ignore_cache", False))
    if not bypass:
        got = try_restore_jobs_session_from_feed_cache(
            mode=mode,
            serpapi_query=q,
            serpapi_location=loc_s,
            serpapi_max_pages=pages,
            ttl_seconds=DEFAULT_TTL_SECONDS,
        )
        if got is not None:
            jobs, label = got
            st.session_state["jobs_raw"] = jobs
            st.session_state["jobs_source"] = f"{label} (cached ≤{DEFAULT_TTL_SECONDS // 3600}h)"
            st.session_state.pop("jobs_error", None)
            save_serpapi_prefs(
                str(st.session_state.get("serpapi_query") or ""),
                str(st.session_state.get("serpapi_location") or ""),
            )
            return
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
    _init_chart_hide_session_keys()

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
            st.caption(
                "Click **Refresh jobs** to load listings. Uses **data/jobs/feed/** cache when fresh "
                f"(≤{DEFAULT_TTL_SECONDS // 3600}h) unless **Fetch live** is checked."
            )
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

            st.checkbox(
                "Fetch live (bypass cache)",
                value=False,
                key="jobs_ignore_cache",
                help=f"When unchecked, Refresh uses data/jobs/feed for this source/query if still fresh ({DEFAULT_TTL_SECONDS // 3600}h). Check to always call Remotive/SerpAPI.",
            )
            if st.button("Refresh jobs", type="primary"):
                with st.spinner("Loading…"):
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
            st.checkbox(
                "Fetch live (bypass cache)",
                value=False,
                key="career_ignore_cache",
                help=f"When unchecked, Refresh uses data/jobs/career per company if still fresh ({DEFAULT_TTL_SECONDS // 3600}h). Check to always hit each careers API.",
            )
            st.caption("Refresh listings in the main area (cache-first unless **Fetch live** is on).")

    title_ignore_words = load_title_ignore_words()

    # Restore from ``data/jobs/`` when session lists are empty (no network for career; optional disk read for Jobs API).
    if view == "Jobs API" and not (st.session_state.get("jobs_raw") or []):
        _try_hydrate_jobs_from_disk_cache()
    if view == "Career page tracker":
        _career_sel = list(st.session_state.get("career_tracker_selection") or [])
        if _career_sel and not (st.session_state.get("career_tracker_rows") or []):
            _cj, _ce, _cn = fetch_tracked_career_jobs(
                _career_sel,
                force_refresh=False,
                use_cache=True,
                allow_network=False,
            )
            if _cj:
                st.session_state["career_tracker_rows"] = _cj
                st.session_state["career_tracker_errs"] = _ce
                st.session_state["career_cache_notes"] = _cn
            elif _ce:
                st.session_state["career_tracker_errs"] = _ce

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
            "**Uber** (search API), **Netflix** (Eightfold), **Microsoft** (PCSX), **Amazon** (`amazon.jobs` JSON): **USA** where applicable, up to **50** rows per company. "
            "Many more employers in the multiselect use **SerpAPI** (same `SERPAPI_API_KEY` as **Jobs API**); see `data/mappings/career_page_mappings.json`. Filtered by company name / apply URL. **Newest first** where dates exist; **Updated** when the source provides it. "
            f"**Refresh** prefers **data/jobs/career/** when fresh (≤{DEFAULT_TTL_SECONDS // 3600}h); enable **Fetch live** to bypass. "
            "**Salary** uses explicit pay fields when present; otherwise a range is parsed from description text (e.g. Amazon qualifications)."
        )
        if st.button("Refresh career listings", type="primary"):
            sel = list(st.session_state.get("career_tracker_selection") or [])
            if not sel:
                st.warning("Select at least one company under **Career page tracker** in the sidebar.")
            else:
                _bypass = bool(st.session_state.get("career_ignore_cache", False))
                with st.spinner("Fetching career pages…" if _bypass else "Loading career listings…"):
                    jobs, errs, notes = fetch_tracked_career_jobs(
                        sel,
                        force_refresh=_bypass,
                        use_cache=not _bypass,
                    )
                st.session_state["career_tracker_rows"] = jobs
                st.session_state["career_tracker_errs"] = errs
                st.session_state["career_cache_notes"] = notes
                if not errs and jobs:
                    st.success(f"Loaded {len(jobs)} role(s). {' · '.join(notes)}")
                elif errs and jobs:
                    st.success(f"Loaded {len(jobs)} role(s) with warnings. {' · '.join(notes)}")
                elif errs:
                    st.error("Could not load listings; see warnings below.")

        for msg in st.session_state.get("career_tracker_errs") or []:
            st.warning(msg)

        _cc_notes = st.session_state.get("career_cache_notes") or []
        if _cc_notes:
            st.caption("Load info: " + " · ".join(str(x) for x in _cc_notes))

        c_rows = sort_career_jobs_by_created_desc(st.session_state.get("career_tracker_rows") or [])
        if c_rows:
            visible_career = [
                r
                for r in c_rows
                if job_is_included(r, title_filters, company_filters, category_filters, title_ignore_words)
            ]
            sync_career_plotly_selections_into_hides()
            visible_career = _filter_career_list_with_charts(visible_career)
            _render_cross_filter_panel_career()
            n_c = len(c_rows)
            n_vis = len(visible_career)
            if n_vis < n_c:
                st.caption(f"Showing **{n_vis}** of {n_c} role(s); the rest match a sidebar exclude rule.")
            st.caption(
                "The **filter** control next to **Title** adds that text to the **Title** exclude list (same rules as **−** on **Jobs API**); matching roles disappear here and there."
            )
            if not visible_career:
                st.info(
                    "Every loaded role matches a title rule, **Title ignore words**, company/category rule, "
                    "or **chart bar hide** (title/summary/length charts below). Adjust filters or **Clear chart hides** on each chart."
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
                        compensation = salary_display_for_career_row(row)
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
                            st.text(_truncate(compensation, MAX_SALARY_DISPLAY_LEN) if compensation else "—")
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
                    chart_key=f"career_title_kw_plotly_{st.session_state.get(NONCE_PLOTLY_CAREER_TITLE_KW, 0)}",
                    hide_session_key=SS_CAREER_HIDE_TITLE_KW,
                    clear_nonce_key=NONCE_PLOTLY_CAREER_TITLE_KW,
                )
                with st.expander("Job summary distribution (Career tracker)", expanded=False):
                    _render_summary_length_distribution(
                        visible_career,
                        chart_key=f"career_summary_len_plotly_{st.session_state.get(NONCE_PLOTLY_CAREER_SUM_LEN, 0)}",
                        hide_session_key=SS_CAREER_HIDE_SUMMARY_BUCKET,
                        clear_nonce_key=NONCE_PLOTLY_CAREER_SUM_LEN,
                    )
                    _render_summary_keyword_distribution(
                        visible_career,
                        chart_key=f"career_summary_kw_plotly_{st.session_state.get(NONCE_PLOTLY_CAREER_SUM_KW, 0)}",
                        hide_session_key=SS_CAREER_HIDE_SUMMARY_KW,
                        clear_nonce_key=NONCE_PLOTLY_CAREER_SUM_KW,
                    )
        elif st.session_state.get("career_tracker_errs"):
            st.caption("No rows to show.")
        else:
            st.info("Select companies in the sidebar and click **Refresh career listings**.")

    elif view == "Jobs API":
        st.caption(
            f"**Window:** {_recency_window_phrase(days_window)} (when dated). "
            "**Remotive** = free · **SerpAPI** = paid. "
            "**−** = title/company/category rule · sidebar **Title ignore words** = keywords · **✕** removes rules. "
            "**Salary** uses the feed when present; otherwise a range is parsed from posting text when available."
        )
        if not has_fetched_jobs:
            st.info("Use **Refresh jobs** in the sidebar (**Remotive** / **SerpAPI** / both).")

        q = st.text_input("Search Jobs API listings (id, title, company, category, salary, source)", "")
        sync_jobs_api_plotly_selections_into_hides()
        df_i = pd.DataFrame(included)
        jobs_visible = _filter_jobs_api_list_with_charts(included, q) if not df_i.empty else []
        df_show = pd.DataFrame(jobs_visible)
        _render_cross_filter_panel_jobs()

        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
        c1.metric("Fetched (feed)", len(raw))
        c2.metric(_format_recency_days(days_window), len(windowed))
        c3.metric("Shown (search + charts)", len(jobs_visible))
        c4.metric("Hidden (title rules)", len(excluded_title))
        c5.metric("Hidden (title words)", len(excluded_title_words))
        c6.metric("Hidden (company)", len(excluded_company))
        c7.metric("Hidden (category)", len(excluded_category))

        if not df_i.empty:
            n_show = len(df_show)
            if n_show == 0:
                st.info("No rows match your search or **chart bar hides** (summary / title keyword / length). Clear hides under the charts or use **Clear chart hides**.")
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
                            st.text(_truncate(salary, MAX_SALARY_DISPLAY_LEN) if salary else "—")
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
                    chart_key=f"jobs_api_title_kw_plotly_{st.session_state.get(NONCE_PLOTLY_JOBS_TITLE_KW, 0)}",
                    hide_session_key=SS_JOBS_HIDE_TITLE_KW,
                    clear_nonce_key=NONCE_PLOTLY_JOBS_TITLE_KW,
                )
                with st.expander("Job summary distribution (Jobs API)", expanded=False):
                    _render_summary_length_distribution(
                        jobs_visible,
                        chart_key=f"jobs_api_summary_len_plotly_{st.session_state.get(NONCE_PLOTLY_JOBS_SUM_LEN, 0)}",
                        hide_session_key=SS_JOBS_HIDE_SUMMARY_BUCKET,
                        clear_nonce_key=NONCE_PLOTLY_JOBS_SUM_LEN,
                    )
                    _render_summary_keyword_distribution(
                        jobs_visible,
                        chart_key=f"jobs_api_summary_kw_plotly_{st.session_state.get(NONCE_PLOTLY_JOBS_SUM_KW, 0)}",
                        hide_session_key=SS_JOBS_HIDE_SUMMARY_KW,
                        clear_nonce_key=NONCE_PLOTLY_JOBS_SUM_KW,
                    )
        else:
            if not has_fetched_jobs:
                st.caption("Load listings with **Refresh jobs** in the sidebar.")
            else:
                st.info(f"No jobs in {_recency_window_phrase(days_window)} (or feed is empty).")

        df_pie_view = pd.DataFrame(jobs_visible)
        with st.expander("Category distribution (Jobs API)", expanded=False):
            _render_top_n_pie(
                df_pie_view,
                "category",
                subheader="",
                dimension_description="category inferred from job title",
                other_noun="categories",
                empty_caption="No categories to chart.",
            )
        with st.expander("Company distribution (Jobs API)", expanded=False):
            _render_top_n_pie(
                df_pie_view,
                "company",
                subheader="",
                dimension_description="company name",
                other_noun="companies",
                empty_caption="No companies to chart.",
            )
        with st.expander("Job title distribution (Jobs API)", expanded=False):
            _render_top_n_pie(
                df_pie_view,
                "title",
                subheader="",
                dimension_description="exact job title",
                other_noun="titles",
                empty_caption="No titles to chart.",
            )


if __name__ == "__main__":
    main()
