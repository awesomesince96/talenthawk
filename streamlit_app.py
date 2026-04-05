"""
TalentHawk — browse recent remote jobs, filter by title, company, and derived category.

Run: uv run streamlit run streamlit_app.py
"""

from __future__ import annotations

import html

import pandas as pd
import plotly.express as px
import streamlit as st

from talenthawk.categorize import categorize_title
from talenthawk.fetch_jobs import (
    fetch_remotive_jobs,
    filter_last_n_days,
    matches_text_filter,
)
from talenthawk.storage import (
    load_category_filters,
    load_company_filters,
    load_title_filters,
    persistence_paths,
    save_category_filters,
    save_company_filters,
    save_title_filters,
)

PAGE_SIZE = 25
MAX_TITLE_LEN = 72
MAX_COMPANY_LEN = 36
MAX_PAY_LEN = 28
MAX_CATEGORY_LEN = 22
TITLE_DIST_TOP_N = 25
TITLE_DIST_CHART_MAX = 56


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

    st.markdown("**Title**")
    if not title_filters:
        st.caption("—")
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

    st.markdown("**Company**")
    if not company_filters:
        st.caption("—")
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

    st.markdown("**Category**")
    if not category_filters:
        st.caption("Inferred from title — none yet.")
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
            "job_id": st.column_config.TextColumn("ID"),
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


def load_jobs_into_session() -> None:
    try:
        raw = fetch_remotive_jobs()
        st.session_state["jobs_raw"] = raw
        st.session_state["jobs_source"] = "remotive_api"
        st.session_state.pop("jobs_error", None)
    except Exception as e:
        st.session_state["jobs_raw"] = []
        st.session_state["jobs_source"] = "none"
        st.session_state["jobs_error"] = str(e)


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

    if "jobs_raw" not in st.session_state:
        with st.spinner("Fetching jobs…"):
            load_jobs_into_session()

    raw = st.session_state.get("jobs_raw") or []
    title_filters = load_title_filters()
    company_filters = load_company_filters()
    category_filters = load_category_filters()

    windowed = filter_last_n_days(raw, days=30)
    annotated = annotate_jobs(windowed)

    included = [j for j in annotated if job_is_included(j, title_filters, company_filters, category_filters)]
    excluded_title = [j for j in annotated if matches_text_filter(j["title"], title_filters)]
    excluded_company = [j for j in annotated if matches_text_filter(j["company"], company_filters)]
    excluded_category = [j for j in annotated if matches_text_filter(j["category"], category_filters)]

    with st.sidebar:
        st.header("Jobs")
        if st.button("Refresh from Remotive API", type="primary"):
            with st.spinner("Fetching…"):
                try:
                    fresh = fetch_remotive_jobs()
                    st.session_state["jobs_raw"] = fresh
                    st.session_state["jobs_source"] = "remotive_api"
                    st.session_state.pop("jobs_error", None)
                    st.success(f"Loaded {len(fresh)} listings.")
                except Exception as e:
                    st.error(str(e))
        src = st.session_state.get("jobs_source", "?")
        st.caption(f"Source: **{src}**")
        err = st.session_state.get("jobs_error")
        if err:
            st.caption(f"Last fetch error: {err}")

        render_sidebar_filters(title_filters, company_filters, category_filters)

    st.title("TalentHawk")
    st.caption(
        "Last 30 days (Remotive). Use **-** on a row to add that value to a filter; use **✕** in the sidebar to remove a rule."
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Fetched (feed)", len(raw))
    c2.metric("Last 30 days", len(windowed))
    c3.metric("Shown (included)", len(included))
    c4.metric("Hidden (title)", len(excluded_title))
    c5.metric("Hidden (company)", len(excluded_company))
    c6.metric("Hidden (category)", len(excluded_category))

    tab_inc, tab_hidden = st.tabs(["Included jobs", "Hidden jobs"])

    with tab_inc:
        q = st.text_input("Search included jobs (id, title, company, category, pay)", "")
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
                hdr[0].markdown("**ID**")
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
            st.info("No jobs in the 30-day window (or feed is empty).")

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
            "Same 30-day window as **Included jobs**. Remove filter rules with **✕** in the left **Filters** panel."
        )

        st.markdown("### Hidden by title filter")
        st.caption("Rows whose **title** matches any title-filter rule (same 30-day window).")
        render_hidden_insights(pd.DataFrame(excluded_title))

        st.divider()
        st.markdown("### Hidden by company filter")
        st.caption("Rows whose **company** matches any company-filter rule (same 30-day window).")
        render_hidden_insights(pd.DataFrame(excluded_company))

        st.divider()
        st.markdown("### Hidden by category filter")
        st.caption("Rows whose **category** label matches any category-filter rule (same 30-day window).")
        render_hidden_insights(pd.DataFrame(excluded_category))


if __name__ == "__main__":
    main()
