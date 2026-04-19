"""
Visualization and filtering logic shared by the web UI (formerly Streamlit).

Builds Plotly figure dicts for JSON transport to react-plotly.js.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from talenthawk.categorize import categorize_title
from talenthawk.fetch_jobs import filter_last_n_days, matches_text_filter
from talenthawk.salary_parse import (
    job_summary_plain_text,
    salary_display_for_api_job,
    salary_display_for_career_row,
)

MAX_TITLE_LEN = 72
MAX_COMPANY_LEN = 36
MAX_PAY_LEN = 28
MAX_SALARY_DISPLAY_LEN = 48
MAX_CATEGORY_LEN = 22
TITLE_DIST_TOP_N = 25
TITLE_DIST_CHART_MAX = 56
TITLE_KEYWORD_DIST_TOP_N = 28
SUMMARY_KEYWORD_DIST_TOP_N = 24

SUMMARY_LEN_BUCKET_ORDER = (
    "No summary text",
    "1–49 words",
    "50–149 words",
    "150–299 words",
    "300+ words",
)

_WORD_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.I)

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

RECENCY_DAY_CHOICES = (1, 3, 7, 14, 30)


@dataclass
class ChartIncludes:
    title_tokens: list[str] = field(default_factory=list)
    summary_tokens: list[str] = field(default_factory=list)
    summary_buckets: list[str] = field(default_factory=list)


def truncate(text: str, max_len: int) -> str:
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def format_recency_days(n: int) -> str:
    if n == 1:
        return "Last 1 day"
    return f"Last {n} days"


def recency_window_phrase(n: int) -> str:
    if n == 1:
        return "the last day"
    return f"the last {n} days"


def tokenize_title_words(title: str, *, min_len: int = 2) -> list[str]:
    out: list[str] = []
    for m in _WORD_TOKEN_RE.finditer(title or ""):
        w = m.group(0).lower()
        if len(w) >= min_len and w not in TITLE_KEYWORD_STOPWORDS:
            out.append(w)
    return out


def tokenize_summary_words(text: str, *, min_len: int = 3) -> list[str]:
    out: list[str] = []
    for m in _WORD_TOKEN_RE.finditer(text or ""):
        w = m.group(0).lower()
        if len(w) >= min_len and w not in SUMMARY_KEYWORD_STOPWORDS:
            out.append(w)
    return out


def bucket_summary_word_count(wc: int) -> str:
    if wc <= 0:
        return "No summary text"
    if wc < 50:
        return "1–49 words"
    if wc < 150:
        return "50–149 words"
    if wc < 300:
        return "150–299 words"
    return "300+ words"


def word_to_company_title_index(rows: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    idx: dict[str, list[tuple[str, str]]] = {}
    for company, title in rows:
        if not (title or "").strip():
            continue
        co = (company or "").strip() or "—"
        ti = title.strip()
        row = (co, ti)
        seen: set[str] = set()
        for w in tokenize_title_words(title):
            if w in seen:
                continue
            seen.add(w)
            idx.setdefault(w, []).append(row)
    return idx


def hover_company_title_line(company: str, title: str) -> str:
    co = (company or "").strip() or "—"
    ti = (title or "").strip() or "—"
    return f"Company: {html.escape(co)}, Title: {html.escape(ti)}"


def summary_word_index(company_title_rows_from_jobs: list[dict[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    idx: dict[str, list[tuple[str, str]]] = {}
    for j in company_title_rows_from_jobs:
        company = (j.get("company") or "").strip() or "—"
        title = (j.get("title") or "").strip() or "—"
        text = job_summary_plain_text(j)
        seen: set[str] = set()
        for w in tokenize_summary_words(text):
            if w in seen:
                continue
            seen.add(w)
            idx.setdefault(w, []).append((company, title))
    return idx


def annotate_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
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
        cat = categorize_title(str(title))
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


def jobs_api_row_matches_search(job: dict[str, Any], q: str) -> bool:
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


def filter_jobs_api_list_with_charts(
    jobs: list[dict[str, Any]],
    q: str,
    includes: ChartIncludes,
) -> list[dict[str, Any]]:
    it = set(includes.title_tokens)
    is_kw = set(includes.summary_tokens)
    ib = set(includes.summary_buckets)
    out: list[dict[str, Any]] = []
    for j in jobs:
        if not jobs_api_row_matches_search(j, q):
            continue
        title = str(j.get("title") or "")
        if it:
            if set(tokenize_title_words(title)).isdisjoint(it):
                continue
        if is_kw:
            if set(tokenize_summary_words(job_summary_plain_text(j))).isdisjoint(is_kw):
                continue
        if ib:
            text = job_summary_plain_text(j)
            wc = len(text.split()) if text else 0
            b = bucket_summary_word_count(wc)
            if b not in ib:
                continue
        out.append(j)
    return out


def filter_career_list_with_charts(rows: list[dict[str, Any]], includes: ChartIncludes) -> list[dict[str, Any]]:
    it = set(includes.title_tokens)
    is_kw = set(includes.summary_tokens)
    ib = set(includes.summary_buckets)
    out: list[dict[str, Any]] = []
    for j in rows:
        title = str(j.get("title") or "")
        if it:
            if set(tokenize_title_words(title)).isdisjoint(it):
                continue
        if is_kw:
            if set(tokenize_summary_words(job_summary_plain_text(j))).isdisjoint(is_kw):
                continue
        if ib:
            text = job_summary_plain_text(j)
            wc = len(text.split()) if text else 0
            b = bucket_summary_word_count(wc)
            if b not in ib:
                continue
        out.append(j)
    return out


def job_is_included(
    job: dict[str, Any],
    title_filters: list[str],
    company_filters: list[str],
    category_filters: list[str],
    title_ignore_words: list[str],
) -> bool:
    t = job.get("title") or ""
    c = job.get("company") or ""
    g = job.get("category") or ""
    if matches_text_filter(str(t), title_filters):
        return False
    if matches_text_filter(str(t), title_ignore_words):
        return False
    if matches_text_filter(str(c), company_filters):
        return False
    if matches_text_filter(str(g), category_filters):
        return False
    return True


def figure_to_dict(fig: go.Figure) -> dict[str, Any]:
    return json.loads(fig.to_json())


_DIST_BASE_LAYOUT: dict[str, Any] = {
    "template": "plotly_white",
    "font": {
        "family": "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        "size": 12,
        "color": "#1e293b",
    },
    "paper_bgcolor": "#f8fafc",
    "plot_bgcolor": "#f8fafc",
}


def _finish_hbar_distribution(
    fig: go.Figure,
    *,
    xaxis_title: str,
    height: int,
    margin_bottom: int = 52,
) -> dict[str, Any]:
    fig.update_layout(
        **_DIST_BASE_LAYOUT,
        height=height,
        margin=dict(l=8, r=28, t=16, b=margin_bottom),
        xaxis_title=xaxis_title,
        yaxis=dict(title=""),
        showlegend=False,
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(15, 23, 42, 0.08)", zeroline=False)
    fig.update_yaxes(showgrid=False)
    return figure_to_dict(fig)


def _finish_vbar_distribution(
    fig: go.Figure,
    *,
    yaxis_title: str,
    height: int = 340,
    margin_bottom: int = 72,
    x_tickangle: int = -32,
) -> dict[str, Any]:
    fig.update_layout(
        **_DIST_BASE_LAYOUT,
        height=height,
        margin=dict(l=48, r=16, t=16, b=margin_bottom),
        xaxis_title="",
        yaxis_title=yaxis_title,
        showlegend=False,
        xaxis_tickangle=x_tickangle,
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(15, 23, 42, 0.08)", zeroline=False)
    return figure_to_dict(fig)


# One color per summary-length bucket (ordered light → strong by typical length).
_SUMMARY_LEN_BAR_COLORS = ("#94a3b8", "#7dd3fc", "#38bdf8", "#0284c7", "#0c4a6e")


def build_title_keyword_figure(
    company_title_rows: list[tuple[str, str]],
    *,
    top_n: int = TITLE_KEYWORD_DIST_TOP_N,
) -> dict[str, Any] | None:
    idx = word_to_company_title_index(company_title_rows)
    if not idx:
        return None
    ranked = sorted(idx.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:top_n]
    ranked_bar = list(reversed(ranked))
    words_y = [w for w, _ in ranked_bar]
    cnts = [len(idx[w]) for w in words_y]
    hover_bodies = ["<br>".join(hover_company_title_line(co, ti) for co, ti in idx[w]) for w in words_y]

    fig = go.Figure(
        data=go.Bar(
            x=cnts,
            y=words_y,
            orientation="h",
            customdata=hover_bodies,
            marker=dict(
                color=cnts,
                colorscale="Teal",
                showscale=False,
                line=dict(width=0),
            ),
            text=[str(c) for c in cnts],
            textposition="outside",
            textfont=dict(size=11, color="#475569"),
            cliponaxis=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "<b>%{x}</b> row(s)<br><br>"
                "%{customdata}<extra></extra>"
            ),
        )
    )
    return _finish_hbar_distribution(
        fig,
        xaxis_title="Rows (title contains word)",
        height=max(300, min(900, 36 * len(words_y) + 140)),
    )


def build_summary_length_figure(jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    counts: dict[str, int] = {k: 0 for k in SUMMARY_LEN_BUCKET_ORDER}
    for j in jobs:
        text = job_summary_plain_text(j)
        wc = len(text.split()) if text else 0
        b = bucket_summary_word_count(wc)
        counts[b] = counts[b] + 1
    x = list(SUMMARY_LEN_BUCKET_ORDER)
    y = [counts[k] for k in x]
    if sum(y) == 0:
        return None
    total = sum(y)
    pct = [round(100 * v / total, 1) if total else 0.0 for v in y]
    colors = [_SUMMARY_LEN_BAR_COLORS[i % len(_SUMMARY_LEN_BAR_COLORS)] for i in range(len(x))]
    fig = go.Figure(
        data=go.Bar(
            x=x,
            y=y,
            marker=dict(color=colors, line=dict(width=0)),
            customdata=[[p] for p in pct],
            text=[f"{v}<br>({p}%)" if v else "" for v, p in zip(y, pct, strict=True)],
            textposition="outside",
            textfont=dict(size=11, color="#475569"),
            cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>Jobs: %{y}<br>%{customdata[0]:.1f}% of shown<extra></extra>",
        )
    )
    return _finish_vbar_distribution(fig, yaxis_title="Jobs")


def build_summary_keyword_figure(
    jobs: list[dict[str, Any]],
    *,
    top_n: int = SUMMARY_KEYWORD_DIST_TOP_N,
) -> dict[str, Any] | None:
    idx = summary_word_index(jobs)
    if not idx:
        return None
    ranked = sorted(idx.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:top_n]
    ranked_bar = list(reversed(ranked))
    words_y = [w for w, _ in ranked_bar]
    cnts = [len(idx[w]) for w in words_y]
    hover_bodies = ["<br>".join(hover_company_title_line(co, ti) for co, ti in idx[w]) for w in words_y]

    fig = go.Figure(
        data=go.Bar(
            x=cnts,
            y=words_y,
            orientation="h",
            customdata=hover_bodies,
            marker=dict(
                color=cnts,
                colorscale="PuBu",
                showscale=False,
                line=dict(width=0),
            ),
            text=[str(c) for c in cnts],
            textposition="outside",
            textfont=dict(size=11, color="#475569"),
            cliponaxis=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "<b>%{x}</b> row(s)<br><br>"
                "%{customdata}<extra></extra>"
            ),
        )
    )
    return _finish_hbar_distribution(
        fig,
        xaxis_title="Rows (summary contains word)",
        height=max(300, min(900, 36 * len(words_y) + 140)),
    )


def build_top_n_pie_figure(
    df: pd.DataFrame,
    column: str,
    *,
    top_n: int = TITLE_DIST_TOP_N,
    label_max: int = TITLE_DIST_CHART_MAX,
) -> dict[str, Any] | None:
    if df.empty or column not in df.columns:
        return None
    ser = df[column].fillna("(empty)").astype(str)
    vc = ser.value_counts().rename_axis("value").reset_index(name="count")
    n_distinct = len(vc)
    if n_distinct == 0:
        return None
    pie_rows: list[dict[str, Any]] = []
    for _, r in vc.head(top_n).iterrows():
        v = str(r["value"])
        pie_rows.append({"label": truncate(v, label_max), "count": int(r["count"]), "hover": v})
    if n_distinct > top_n:
        rest = vc.iloc[top_n:]
        other_count = int(rest["count"].sum())
        n_other = n_distinct - top_n
        other_noun = "categories" if column == "category" else ("companies" if column == "company" else "titles")
        pie_rows.append(
            {
                "label": f"Other ({n_other} {other_noun})",
                "count": other_count,
                "hover": f"{n_other} distinct {other_noun} not in top {top_n} ({other_count} job rows)",
            }
        )
    pie_df = pd.DataFrame(pie_rows)
    total_jobs = int(pie_df["count"].sum())
    if total_jobs <= 0:
        return None
    pie_df = pie_df.assign(pct=(pie_df["count"] / total_jobs * 100).map(lambda v: round(float(v), 1)))
    pie_df = pie_df.sort_values("count", ascending=True)
    labels = pie_df["label"].astype(str).tolist()
    counts = pie_df["count"].astype(int).tolist()
    hovers = pie_df["hover"].astype(str).tolist()
    pcts = pie_df["pct"].tolist()
    n = len(labels)
    fig = go.Figure(
        data=go.Bar(
            x=counts,
            y=labels,
            orientation="h",
            customdata=list(zip(hovers, pcts, strict=True)),
            marker=dict(
                color=counts,
                colorscale="Teal",
                showscale=False,
                line=dict(width=0),
            ),
            text=[f"{c} ({p}%)" for c, p in zip(counts, pcts, strict=True)],
            textposition="outside",
            textfont=dict(size=11, color="#475569"),
            cliponaxis=False,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Jobs: %{x}<br>"
                "%{customdata[1]:.1f}% of shown rows<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        **_DIST_BASE_LAYOUT,
        height=max(280, min(760, 28 * n + 120)),
        margin=dict(l=8, r=36, t=16, b=48),
        xaxis_title="Jobs",
        yaxis=dict(title="", automargin=True),
        showlegend=False,
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(15, 23, 42, 0.08)", zeroline=False)
    fig.update_yaxes(showgrid=False, automargin=True)
    return figure_to_dict(fig)


def compute_jobs_api_bundle(
    raw_jobs: list[dict[str, Any]],
    *,
    days_window: int,
    title_filters: list[str],
    company_filters: list[str],
    category_filters: list[str],
    title_ignore_words: list[str],
    search_q: str,
    chart_includes: ChartIncludes,
) -> dict[str, Any]:
    if days_window not in RECENCY_DAY_CHOICES:
        days_window = 30
    windowed = filter_last_n_days(raw_jobs, days=days_window)
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

    jobs_visible = filter_jobs_api_list_with_charts(included, search_q, chart_includes)
    df_show = pd.DataFrame(jobs_visible)

    title_kw_fig = None
    sum_len_fig = None
    sum_kw_fig = None
    pie_cat = pie_co = pie_title = None
    if not df_show.empty:
        title_kw_fig = build_title_keyword_figure(
            [
                (str(c).strip() or "—", str(t))
                for c, t in zip(
                    df_show["company"].fillna("").astype(str),
                    df_show["title"].fillna("").astype(str),
                    strict=True,
                )
            ],
        )
        sum_len_fig = build_summary_length_figure(jobs_visible)
        sum_kw_fig = build_summary_keyword_figure(jobs_visible)
        pie_cat = build_top_n_pie_figure(df_show, "category")
        pie_co = build_top_n_pie_figure(df_show, "company")
        pie_title = build_top_n_pie_figure(df_show, "title")

    return {
        "windowed_count": len(windowed),
        "annotated_count": len(annotated),
        "included_count": len(included),
        "jobs_visible": jobs_visible,
        "metrics": {
            "fetched": len(raw_jobs),
            "windowed": len(windowed),
            "shown": len(jobs_visible),
            "hidden_title_rules": len(excluded_title),
            "hidden_title_words": len(excluded_title_words),
            "hidden_company": len(excluded_company),
            "hidden_category": len(excluded_category),
        },
        "charts": {
            "title_keywords": title_kw_fig,
            "summary_length": sum_len_fig,
            "summary_keywords": sum_kw_fig,
            "pie_category": pie_cat,
            "pie_company": pie_co,
            "pie_title": pie_title,
        },
    }


def compute_career_bundle(
    career_rows: list[dict[str, Any]],
    *,
    title_filters: list[str],
    company_filters: list[str],
    category_filters: list[str],
    title_ignore_words: list[str],
    chart_includes: ChartIncludes,
) -> dict[str, Any]:
    visible = [
        r
        for r in career_rows
        if job_is_included(r, title_filters, company_filters, category_filters, title_ignore_words)
    ]
    filtered = filter_career_list_with_charts(visible, chart_includes)
    title_kw_fig = build_title_keyword_figure(
        [
            (
                str(r.get("company", "") or "").strip() or "—",
                str(r.get("title", "") or ""),
            )
            for r in filtered
        ],
    )
    sum_len_fig = build_summary_length_figure(filtered)
    sum_kw_fig = build_summary_keyword_figure(filtered)
    return {
        "visible_pre_chart": visible,
        "rows": filtered,
        "total_loaded": len(career_rows),
        "charts": {
            "title_keywords": title_kw_fig,
            "summary_length": sum_len_fig,
            "summary_keywords": sum_kw_fig,
        },
    }


def salary_line_for_career_row(row: dict[str, Any]) -> str:
    return salary_display_for_career_row(row)
