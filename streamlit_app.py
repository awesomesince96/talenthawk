"""
TalentHawk — browse recent remote jobs, filter by title, company, and derived category.

Run: uv run streamlit run streamlit_app.py — then use **Refresh jobs** in the sidebar to fetch feeds.
"""

from __future__ import annotations

import html
import os

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from talenthawk.categorize import categorize_title
from talenthawk.fetch_jobs import (
    fetch_jobs_feed,
    filter_last_n_days,
    matches_text_filter,
)
from talenthawk.storage import (
    load_category_filters,
    load_company_filters,
    load_serpapi_prefs,
    load_title_filters,
    persistence_paths,
    save_category_filters,
    save_company_filters,
    save_serpapi_prefs,
    save_title_filters,
)

PAGE_SIZE = 25
MAX_TITLE_LEN = 72
MAX_COMPANY_LEN = 36
MAX_PAY_LEN = 28
MAX_CATEGORY_LEN = 22
TITLE_DIST_TOP_N = 25
TITLE_DIST_CHART_MAX = 56

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
    if not paths["title_filter"].exists():
        save_title_filters([])
    if not paths["company_filter"].exists():
        save_company_filters([])
    if not paths["category_filter"].exists():
        save_category_filters([])


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
        "Substring match, case-insensitive. Press **-** on a row in **Included jobs** to add a rule; **✕** here removes it."
    )

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


def render_hidden_insights(df_e: pd.DataFrame) -> None:
    if df_e.empty:
        st.caption("No listings in this cohort.")
        return
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**By category**")
        cat_counts = df_e.groupby("category").size().reset_index(name="count")
        fig_cat = px.bar(cat_counts, x="category", y="count", color="category", labels={"count": "Jobs"})
        fig_cat.update_layout(showlegend=False, xaxis_title=None)
        st.plotly_chart(fig_cat, use_container_width=True)
    with col_b:
        st.markdown("**Top companies**")
        comp_counts = df_e.groupby("company").size().reset_index(name="count").sort_values("count", ascending=False)
        top_n = min(25, len(comp_counts))
        fig_co = px.bar(comp_counts.head(top_n), x="company", y="count", labels={"count": "Jobs"})
        fig_co.update_layout(xaxis_tickangle=-45, showlegend=False)
        st.plotly_chart(fig_co, use_container_width=True)

    table = df_e.sort_values("company")
    if "job_id" not in table.columns:
        table = table.assign(job_id="")
    st.dataframe(
        table[["job_id", "title", "company", "category", "salary", "published_at", "url"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "job_id": st.column_config.TextColumn("Job ID"),
            "url": st.column_config.LinkColumn("Link"),
            "salary": st.column_config.TextColumn("Pay"),
        },
    )


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
) -> bool:
    t = job.get("title") or ""
    c = job.get("company") or ""
    g = job.get("category") or ""
    if matches_text_filter(t, title_filters):
        return False
    if matches_text_filter(c, company_filters):
        return False
    if matches_text_filter(g, category_filters):
        return False
    return True


def main() -> None:
    st.set_page_config(page_title="TalentHawk", layout="wide")
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

    jobs_not_yet_loaded = "jobs_source" not in st.session_state

    raw = st.session_state.get("jobs_raw") or []
    title_filters = load_title_filters()
    company_filters = load_company_filters()
    category_filters = load_category_filters()

    days_window = int(st.session_state.get("jobs_recency_days", 30) or 30)
    if days_window not in RECENCY_DAY_CHOICES:
        days_window = 30
    windowed = filter_last_n_days(raw, days=days_window)
    annotated = annotate_jobs(windowed)

    included = [j for j in annotated if job_is_included(j, title_filters, company_filters, category_filters)]
    excluded_title = [j for j in annotated if matches_text_filter(j["title"], title_filters)]
    excluded_company = [j for j in annotated if matches_text_filter(j["company"], company_filters)]
    excluded_category = [j for j in annotated if matches_text_filter(j["category"], category_filters)]

    with st.sidebar:
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

        if jobs_not_yet_loaded:
            st.caption("**Source:** not loaded yet")
        else:
            src = st.session_state.get("jobs_source", "?")
            st.caption(f"**Source:** {src}")
        err = st.session_state.get("jobs_error")
        if err and not jobs_not_yet_loaded:
            st.caption(f"Last fetch error: {err}")

        render_sidebar_filters(title_filters, company_filters, category_filters)

    st.title("TalentHawk")
    st.caption(
        f"Posted within {_recency_window_phrase(days_window)} when a date is known. **Remotive** is free; **SerpAPI** uses [Google Jobs](https://serpapi.com/google-jobs-api) (paid API key). "
        "Use **-** on a row to add a filter; **✕** in the sidebar removes it."
    )
    if jobs_not_yet_loaded:
        st.info("Click **Refresh jobs** in the sidebar to fetch from **Remotive** and/or **SerpAPI** (per your job source).")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Fetched (feed)", len(raw))
    c2.metric(_format_recency_days(days_window), len(windowed))
    c3.metric("Shown (included)", len(included))
    c4.metric("Hidden (title)", len(excluded_title))
    c5.metric("Hidden (company)", len(excluded_company))
    c6.metric("Hidden (category)", len(excluded_category))

    tab_inc, tab_hidden = st.tabs(["Included jobs", "Hidden jobs"])

    with tab_inc:
        q = st.text_input("Search included jobs (id, title, company, category, pay, source)", "")
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

            st.caption(
                "**Title**, **Company**, and **Category** each have **-** to exclude that value (add to the matching filter). "
                "**Pay** and **Open** come from the feed when available."
            )
            n_show = len(df_show)
            if n_show == 0:
                st.info("No rows match your search.")
            else:
                total_pages = max(1, (n_show + PAGE_SIZE - 1) // PAGE_SIZE)
                page_key = "included_jobs_page"
                if page_key in st.session_state and int(st.session_state[page_key]) > total_pages:
                    st.session_state[page_key] = total_pages
                page = st.number_input("Page", min_value=1, max_value=total_pages, step=1, key=page_key)
                start = (int(page) - 1) * PAGE_SIZE
                chunk = df_show.iloc[start : start + PAGE_SIZE]
                st.caption(f"Showing {start + 1}–{min(start + PAGE_SIZE, n_show)} of {n_show}")

                _colw = [0.52, 1.78, 0.26, 1.12, 0.26, 0.52, 0.26, 0.85, 0.44]
                hdr = st.columns(_colw, vertical_alignment="center")
                hdr[0].markdown("**Job ID**")
                hdr[1].markdown("**Title**")
                hdr[2].markdown("** **")
                hdr[3].markdown("**Company**")
                hdr[4].markdown("** **")
                hdr[5].markdown("**Cat**")
                hdr[6].markdown("** **")
                hdr[7].markdown("**Pay**")
                hdr[8].markdown("**Link**")

                for pos in range(len(chunk)):
                    row = chunk.iloc[pos]
                    job_id = str(row.get("job_id", "") or "").strip()
                    title = str(row.get("title", "") or "")
                    company = str(row.get("company", "") or "").strip()
                    category = str(row.get("category", "") or "")
                    salary = str(row.get("salary", "") or "").strip()
                    url = str(row.get("url", "") or "").strip()
                    row_key = f"{start}_{pos}"

                    cols = st.columns(_colw, vertical_alignment="center")
                    with cols[0]:
                        st.text(job_id if job_id else "—")
                    with cols[1]:
                        st.text(_truncate(title, MAX_TITLE_LEN))
                    with cols[2]:
                        t_disabled = not title or matches_text_filter(title, title_filters)
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
        else:
            if jobs_not_yet_loaded:
                st.caption("Load listings with **Refresh jobs** in the sidebar.")
            else:
                st.info(f"No jobs in {_recency_window_phrase(days_window)} (or feed is empty).")

        _render_top_n_pie(
            df_i,
            "category",
            subheader="Category distribution (included)",
            dimension_description="category inferred from job title",
            other_noun="categories",
            empty_caption="No categories to chart.",
        )
        _render_top_n_pie(
            df_i,
            "company",
            subheader="Company distribution (included)",
            dimension_description="company name",
            other_noun="companies",
            empty_caption="No companies to chart.",
        )
        _render_top_n_pie(
            df_i,
            "title",
            subheader="Job title distribution (included)",
            dimension_description="exact job title",
            other_noun="titles",
            empty_caption="No titles to chart.",
        )

    with tab_hidden:
        st.subheader("Hidden jobs")
        st.caption(
            f"Same time window as **Included jobs** ({_recency_window_phrase(days_window)}). Remove filter rules with **✕** in the left **Filters** panel."
        )

        st.markdown("### Hidden by title filter")
        st.caption(f"Rows whose **title** matches any title-filter rule ({_recency_window_phrase(days_window)}).")
        render_hidden_insights(pd.DataFrame(excluded_title))

        st.divider()
        st.markdown("### Hidden by company filter")
        st.caption(f"Rows whose **company** matches any company-filter rule ({_recency_window_phrase(days_window)}).")
        render_hidden_insights(pd.DataFrame(excluded_company))

        st.divider()
        st.markdown("### Hidden by category filter")
        st.caption(f"Rows whose **category** label matches any category-filter rule ({_recency_window_phrase(days_window)}).")
        render_hidden_insights(pd.DataFrame(excluded_category))


if __name__ == "__main__":
    main()
